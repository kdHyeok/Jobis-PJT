# -*- coding: utf-8 -*-
"""대규모 질의에 대해 실제 DB 하이브리드 검색을 돌려 Tier-0 계약 검사를 수행한다.

LLM 호출 없음 — 100% 결정적, 빠름. 환각 테스트의 1층(검색)을 규모 있게 검증.
검사 항목(계약 위반 = 파이프라인이 "만들어낸" 결과):
  - dup_uid: 같은 공고가 결과에 중복
  - region_violation: 하드필터를 어겼는데도 결과에 포함(지역)
  - exp_violation: 연차 조건을 어겼는데도 결과에 포함
  - empty: 결과 0건
  - sorted: RRF/재순위 점수가 내림차순인지
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, r"c:\Users\SSAFY\Desktop\rag-pipeline\S15P11C202\RAG")
sys.stdout.reconfigure(encoding="utf-8")

from jobrag.store import connect  # noqa: E402  (위 sys.path 설정 뒤에 import 해야 한다)
from jobrag.query_parser import parse_query, load_region_vocab  # noqa: E402
from jobrag.search import hybrid_search  # noqa: E402

HERE = Path(__file__).parent


def region_ok(hit_regions, spec_regions):
    if not spec_regions:
        return True
    if not hit_regions:
        return False
    return any(r in hit_regions or any(r in hr for hr in hit_regions) for r in spec_regions)


def exp_ok(exp_min, spec_exp_years):
    if spec_exp_years is None:
        return True
    if exp_min is None:
        return True
    return spec_exp_years >= exp_min


def main():
    queries = json.loads((HERE / "queries_large.json").read_text(encoding="utf-8"))
    conn = connect()
    region_vocab = load_region_vocab(conn)

    rows = []
    t_all0 = time.time()
    for i, q in enumerate(queries):
        spec = parse_query(q["text"], region_vocab)
        t0 = time.time()
        try:
            result = hybrid_search(conn, spec, top_k=3, use_rerank=True)
            elapsed = time.time() - t0
            uids = [h.posting_uid for h in result.hits]
            dup = len(uids) != len(set(uids))
            reg_viol = sum(1 for h in result.hits if not region_ok(h.regions, spec.regions))
            exp_viol = sum(1 for h in result.hits if not exp_ok(h.exp_min, spec.exp_years))
            scores = [h.rrf for h in result.hits]
            sorted_ok = all(scores[j] >= scores[j + 1] for j in range(len(scores) - 1))
            rows.append({
                "id": q["id"], "text": q["text"], "category": q["category"],
                "n_hits": len(result.hits), "relaxed": result.relaxed,
                "dup_uid": dup, "region_violation": reg_viol, "exp_violation": exp_viol,
                "sorted_ok": sorted_ok, "elapsed_ms": round(elapsed * 1000, 1),
                "spec_regions": spec.regions, "spec_exp": spec.exp_years,
                "error": None,
            })
        except Exception as e:
            rows.append({"id": q["id"], "text": q["text"], "category": q["category"],
                         "error": str(e)})
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(queries)} 처리... ({time.time()-t_all0:.1f}s 경과)", file=sys.stderr)

    conn.close()
    total_elapsed = time.time() - t_all0

    (HERE / "retrieval_results.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    n = len(rows)
    errors = [r for r in rows if r.get("error")]
    ok_rows = [r for r in rows if not r.get("error")]
    empty = sum(1 for r in ok_rows if r["n_hits"] == 0)
    dup = sum(1 for r in ok_rows if r["dup_uid"])
    reg_v = sum(1 for r in ok_rows if r["region_violation"] > 0)
    exp_v = sum(1 for r in ok_rows if r["exp_violation"] > 0)
    unsorted = sum(1 for r in ok_rows if not r["sorted_ok"])
    avg_ms = sum(r["elapsed_ms"] for r in ok_rows) / len(ok_rows) if ok_rows else 0
    relaxed_used = sum(1 for r in ok_rows if r["relaxed"])

    print(f"\n===== 1층: 대규모 검색 계약 검증 (n={n}, 총 {total_elapsed:.1f}s, 질의당 평균 {avg_ms:.0f}ms) =====")
    print(f"오류(예외 발생): {len(errors)}/{n}")
    print(f"빈 결과: {empty}/{n}")
    print(f"중복 공고 포함: {dup}/{n}")
    print(f"지역 하드필터 위반 포함: {reg_v}/{n}  <- 있으면 안 됨(계약 위반)")
    print(f"연차 하드필터 위반 포함: {exp_v}/{n}  <- 있으면 안 됨(계약 위반)")
    print(f"정렬 위반(점수 역순): {unsorted}/{n}")
    print(f"조건 완화(relax) 발생: {relaxed_used}/{n} ({relaxed_used/n*100:.1f}%)")
    if errors:
        print("\n오류 샘플:")
        for e in errors[:5]:
            print(f"  {e['id']} ({e['text'][:30]}): {e['error'][:150]}")
    if reg_v or exp_v:
        print("\n하드필터 위반 샘플:")
        for r in ok_rows:
            if r["region_violation"] or r["exp_violation"]:
                print(f"  {r['id']} ({r['text']}): reg_viol={r['region_violation']} exp_viol={r['exp_violation']}")


if __name__ == "__main__":
    main()
