# -*- coding: utf-8 -*-
"""생성층 대량 테스트용: 질의 표본에 대해 실검색 실행 후 [회사]/[핵심조건] 형식
컨텍스트 문자열을 만들어 저장한다 (ragas_dataset.json과 동일 포맷).
"""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, r"c:\Users\SSAFY\Desktop\rag-pipeline\S15P11C202\RAG")
sys.stdout.reconfigure(encoding="utf-8")

from jobrag.store import connect  # noqa: E402  (위 sys.path 설정 뒤에 import 해야 한다)
from jobrag.query_parser import parse_query, load_region_vocab  # noqa: E402
from jobrag.search import hybrid_search  # noqa: E402

HERE = Path(__file__).parent
random.seed(7)

N_SAMPLE = 120


def ctx_from_hit(h) -> str:
    exp = "경력무관" if h.exp_min is None else f"{h.exp_min}년+"
    loc = ", ".join(h.regions[:2]) if h.regions else "지역 미상"
    tech = ", ".join(h.tech[:8]) if h.tech else "명시 없음"
    return (f"[회사] {h.company}\n[직무] {h.title}\n"
            f"[핵심조건] {exp} · {loc} · 기술: {tech}")


def main():
    queries = json.loads((HERE / "queries_large.json").read_text(encoding="utf-8"))
    sample = random.sample(queries, min(N_SAMPLE, len(queries)))

    conn = connect()
    region_vocab = load_region_vocab(conn)

    out = []
    for i, q in enumerate(sample):
        spec = parse_query(q["text"], region_vocab)
        result = hybrid_search(conn, spec, top_k=3, use_rerank=True)
        contexts = [ctx_from_hit(h) for h in result.hits]
        out.append({
            "qid": f"GEN{i+1:04d}", "text": q["text"], "category": q["category"],
            "n_hits": len(result.hits), "contexts": contexts,
            "companies": [h.company for h in result.hits],
        })
        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(sample)}", file=sys.stderr)

    conn.close()
    (HERE / "gen_samples.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"{len(out)}건 컨텍스트 덤프 완료 -> gen_samples.json")


if __name__ == "__main__":
    main()
