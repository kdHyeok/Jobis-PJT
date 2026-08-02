"""청킹 -> 임베딩 -> pgvector 저장까지 배치 파이프라인 전체 실행.

사용: python run_embed.py [입력JSON]
사전조건: schema.sql 적용 완료 (run_setup_db.py), .env의 PG_DSN.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from pgvector.psycopg import register_vector

from jobrag import tokenizer
from jobrag.chunking import chunk_posting, chunk_stats
from jobrag.embedding import embed_texts
from jobrag.sources import load_postings
from jobrag.store import connect, unchanged_chunk_ids, upsert_chunks, upsert_postings
from jobrag.tracing import new_trace_id, node_span

ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT.parent / "all_job_postings.json"


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT
    trace = new_trace_id()
    print(f"trace_id={trace}  tokenizer={tokenizer.backend()}  input={src}")

    raw_records = json.loads(src.read_text(encoding="utf-8"))
    raw_by_uid = {f"{r.get('source')}:{r.get('posting_id')}": r for r in raw_records}

    with node_span(trace, "load_normalize", "batch", str(src)) as span:
        postings, stats = load_postings(src)
        span.metrics = stats
    print("[load_normalize]", json.dumps(stats, ensure_ascii=False))

    with node_span(trace, "chunking", "batch", f"{len(postings)} postings") as span:
        all_chunks = [c for p in postings for c in chunk_posting(p)]
        span.metrics = chunk_stats(all_chunks)
    print("[chunking]", json.dumps(span.metrics, ensure_ascii=False))

    conn = connect()
    register_vector(conn)

    # 내용이 그대로인 청크는 임베딩 자체를 건너뛴다 (재실행 비용 ≈ 0).
    with node_span(trace, "embedding", "batch", f"{len(all_chunks)} chunks") as span:
        unchanged = unchanged_chunk_ids(conn, all_chunks)
        todo = [c for c in all_chunks if c.chunk_id not in unchanged]
        vectors, embed_stats = embed_texts([c.text for c in todo])
        by_id = dict(zip((c.chunk_id for c in todo), vectors))
        embeddings = [by_id.get(c.chunk_id) for c in all_chunks]
        embed_stats["reused_unchanged"] = len(unchanged)
        embed_stats["reuse_ratio"] = (
            round(len(unchanged) / len(all_chunks), 3) if all_chunks else 0.0)
        span.metrics = embed_stats
    print("[embedding]", json.dumps(embed_stats, ensure_ascii=False))

    with node_span(trace, "store_postings", "batch", f"{len(postings)} postings") as span:
        span.metrics = upsert_postings(conn, postings, raw_by_uid)
    print("[store_postings]", json.dumps(span.metrics, ensure_ascii=False))

    with node_span(trace, "store_chunks", "batch", f"{len(all_chunks)} chunks") as span:
        store_stats = upsert_chunks(conn, all_chunks, embeddings)
        span.metrics = store_stats
    print("[store_chunks]", json.dumps(store_stats, ensure_ascii=False))
    conn.close()


if __name__ == "__main__":
    main()
