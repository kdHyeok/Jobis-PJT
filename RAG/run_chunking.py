"""배치 파이프라인 청킹 단계까지 실행 + 노드 지표 출력.

사용: python run_chunking.py [입력JSON]
기본 입력: 프로젝트 상위 폴더의 all_job_postings.json
산출: chunks.jsonl (청크 전량), logs/trace.jsonl (표준 로그)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from jobrag import tokenizer
from jobrag.chunking import chunk_posting, chunk_stats
from jobrag.sources import load_postings
from jobrag.tracing import new_trace_id, node_span

ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT.parent / "all_job_postings.json"


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT
    trace = new_trace_id()
    print(f"trace_id={trace}  tokenizer={tokenizer.backend()}  input={src}")

    with node_span(trace, "load_normalize", "batch", str(src)) as span:
        postings, stats = load_postings(src)
        span.metrics = stats
        span.output_summary = f"{stats['indexed']}/{stats['total']} indexed"
    print("[load_normalize]", json.dumps(stats, ensure_ascii=False))

    with node_span(trace, "chunking", "batch", f"{len(postings)} postings") as span:
        all_chunks = [c for p in postings for c in chunk_posting(p)]
        span.metrics = chunk_stats(all_chunks)
        span.output_summary = f"{len(all_chunks)} chunks"
    print("[chunking]", json.dumps(span.metrics, ensure_ascii=False))

    out = ROOT / "chunks.jsonl"
    with open(out, "w", encoding="utf-8") as f:
        for c in all_chunks:
            f.write(json.dumps(c.__dict__, ensure_ascii=False) + "\n")
    print(f"wrote {out} ({len(all_chunks)} chunks)")

    # 샘플 1건 눈검증
    sample = next(c for c in all_chunks if c.part == "full")
    print("\n--- sample chunk ---")
    print(sample.text[:400])


if __name__ == "__main__":
    main()
