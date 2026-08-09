"""골든셋 후보 풀링 — 질의 50개 각각에 대해 라벨링 대상 공고를 뽑는다.

표준 IR 풀링 기법: 시스템의 필터링된 결과만 모으면 "필터가 잘못 걸러낸 정답"을
영원히 발견할 수 없다(순환성). 그래서 세 출처를 합친다.
  1. system   — 실제 hybrid_search 출력 (완화 포함). 이게 평가 대상.
  2. dense_pool — 지역/연차 필터를 끈 dense top-N. 필터가 정답을 잘못 쳐냈는지 검증용.
  3. bm25_pool  — 필터를 끈 BM25 축 top-N. 동일 목적.
쿼리당 최대 10건(평가계획 §3 "쿼리당 평균 10개 문서"와 정합) — 시스템 출력을
우선 채우고, 남는 슬롯을 풀링 출처로 채워 다양성을 확보한다.

expected_parsed는 현재 파서로 프리필해두되 parsed_verified=false로 표시한다.
파서 출력을 그대로 정답으로 쓰면 파서 버그가 골든셋에 그대로 박제되므로,
라벨링 도구에서 사람이 확인/수정하게 한다.
"""
from __future__ import annotations

import json
from pathlib import Path

from pgvector.psycopg import register_vector

from golden.queries import QUERIES
from jobrag.embedding import embed_texts
from jobrag.query_parser import load_region_vocab, parse_query
from jobrag.search import _bm25_axis, _dense_axis, hybrid_search
from jobrag.store import connect

OUT = Path(__file__).resolve().parent / "golden" / "pool.json"
# v3(top_k=3 서비스 대응): 풀 깊이를 늘렸다. Precision@3의 분모는 3이지만 Recall의
# 분모(정답 총수)는 풀 안에서만 셀 수 있어, 풀이 얕으면 recall이 구조적으로 부풀려진다.
POOL_K = 15
MAX_CANDIDATES = 20
POOL_RESERVE = 6   # 풀 전용(시스템이 못 찾은) 후보에 보장하는 최소 슬롯
SYSTEM_K = 20      # 시스템 축 풀링 깊이. 10이면 11~20위 정답을 영원히 발견 못 함.


def _snippet(text: str, n: int = 300) -> str:
    return (text or "").replace("\n", " ")[:n]


def build_candidate(row: dict, tags: set[str]) -> dict:
    return {
        "posting_uid": row["uid"], "company": row["company"], "title": row["title"],
        "regions": row["regions"], "tech": row["tech"], "exp_min": row["exp_min"],
        "snippet": _snippet(row.get("detail_text", "")),
        "source_axes": sorted(tags), "label": None,
    }


def main():
    conn = connect()
    register_vector(conn)
    vocab = load_region_vocab(conn)

    existing: dict = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}

    result: dict = {}
    for q in QUERIES:
        spec = parse_query(q["text"], vocab)
        [vec], _ = embed_texts([spec.text])

        system = hybrid_search(conn, spec, top_k=SYSTEM_K)
        dense_pool = _dense_axis(conn, vec, spec, ("region", "exp"))[:POOL_K]
        bm25_pool = _bm25_axis(conn, spec, ("region", "exp"))[:POOL_K]

        pool_uids = {d[0] for d in dense_pool} | {t[0] for t in bm25_pool}
        with conn.cursor() as cur:
            cur.execute(
                """SELECT uid, company, title, regions, tech, exp_min, raw->>'detail_text'
                   FROM postings WHERE uid = ANY(%s)""",
                (list(pool_uids | {h.posting_uid for h in system.hits}),),
            )
            cols = ("uid", "company", "title", "regions", "tech", "exp_min", "detail_text")
            rows = {r[0]: dict(zip(cols, r)) for r in cur.fetchall()}

        tags: dict[str, set[str]] = {}
        for h in system.hits:
            tags.setdefault(h.posting_uid, set()).add("system")
        for uid, _, _ in dense_pool:
            tags.setdefault(uid, set()).add("dense_pool")
        for uid, _, _ in bm25_pool:
            tags.setdefault(uid, set()).add("bm25_pool")

        # 슬롯 배분: 시스템이 10슬롯을 다 채우면 풀 전용 후보(시스템이 못 찾은 것)가
        # 전부 밀려나 풀링이 무의미해진다. 풀 전용에 최소 슬롯을 보장한다.
        sys_uids = [h.posting_uid for h in system.hits]
        pool_only = [uid for uid, _, _ in dense_pool if uid not in tags or "system" not in tags[uid]]
        pool_only += [uid for uid, _, _ in bm25_pool
                      if ("system" not in tags.get(uid, set())) and uid not in pool_only]
        reserve = min(len(pool_only), POOL_RESERVE)
        order = sys_uids[:MAX_CANDIDATES - reserve]
        order += [u for u in pool_only if u not in order][:MAX_CANDIDATES - len(order)]
        order += [u for u in sys_uids if u not in order][:MAX_CANDIDATES - len(order)]

        candidates = [build_candidate(rows[uid], tags[uid]) for uid in order if uid in rows]

        # 이전 라벨링 결과가 있으면 보존 (재풀링해도 사람이 매긴 라벨은 유지)
        prev_labels = {
            c["posting_uid"]: c["label"]
            for c in existing.get(q["id"], {}).get("candidates", [])
            if c.get("label") is not None
        }
        for c in candidates:
            if c["posting_uid"] in prev_labels:
                c["label"] = prev_labels[c["posting_uid"]]

        prev = existing.get(q["id"], {})
        # 사람이 확인(parsed_verified)한 파싱 정답만 보존한다. 미검증 프리필까지
        # 보존하면 파서를 고쳐도 옛 버그 출력이 골든셋에 남는다.
        keep_parsed = prev.get("parsed_verified", False)
        result[q["id"]] = {
            "query": q["text"], "category": q["category"],
            "expected_parsed": prev["expected_parsed"] if keep_parsed else {
                "tech": spec.tech, "regions": spec.regions, "exp_years": spec.exp_years,
            },
            "parsed_verified": keep_parsed,
            "candidates": candidates,
        }

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(len(v["candidates"]) for v in result.values())
    print(f"질의 {len(result)}개, 후보 {total}건 -> {OUT}")
    conn.close()


if __name__ == "__main__":
    main()
