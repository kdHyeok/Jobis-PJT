"""잡코리아 신규 코퍼스 실험 — 자동 질의 생성 -> 후보 풀 -> LLM 라벨 -> 평가.

기존 golden/·eval/ 자산을 건드리지 않는 자체 완결형 실험. 산출은 exp/ 에만 쓴다.
파싱(질의->쿼리) 규칙은 미확정이라, 현재 규칙 파서(query_parser)를 그대로 쓰되
질의 자체를 새 코퍼스의 실제 분포(상위 기술/지역/직군/연차)에서 임의 생성한다.

단계:
  1. build_queries   — DB 분포에서 대표 질의 N개 생성 (축별 층화)
  2. build_pools     — 질의별 후보 풀링 (system + dense/bm25 필터오프)  ← run_pool.py 로직 재사용
  3. label_pools     — 질의당 1콜로 후보 전체를 C/A/I 배치 라벨 (Gemini)
  4. evaluate        — recall@k / MRR (Correct=정답) + 완화율/직군분산
                       + CRAG 그레이더(jobrag.grader) vs 골든 라벨 일치도

사용: python run_experiment.py            # 전체 (라벨 재사용)
      python run_experiment.py --relabel  # 라벨 캐시 무시하고 재라벨
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from pgvector.psycopg import register_vector

from jobrag.embedding import embed_texts
from jobrag.generate import GmsClient
from jobrag.query_parser import load_region_vocab, parse_query
from jobrag.search import _bm25_axis, _dense_axis, hybrid_search
from jobrag.store import connect

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "exp"
POOL_OUT = OUT_DIR / "pool_jobkorea.json"
REPORT_OUT = OUT_DIR / "report_jobkorea.json"

POOL_K = 8
MAX_CANDIDATES = 10
POOL_RESERVE = 3
RECALL_KS = (5, 10)


# ---------- 1. 코퍼스 분포 기반 질의 자동 생성 ----------

def _top_values(conn, sql: str, limit: int) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(sql, (limit,))
        return [r[0] for r in cur.fetchall()]


def build_queries(conn) -> list[dict]:
    """새 코퍼스의 실제 상위 값으로 축별 층화 질의 생성 — 빈 풀을 피한다."""
    techs = _top_values(conn, """
        SELECT t, count(*) c FROM (SELECT unnest(tech) t FROM postings WHERE is_active) s
        GROUP BY t ORDER BY c DESC LIMIT %s""", 8)
    # 지역은 시군구 단위(공백 포함)만 — 구어체·필터가 실제로 걸리는 단위
    regions = _top_values(conn, """
        SELECT r, count(*) c FROM (SELECT unnest(regions) r FROM postings WHERE is_active) s
        WHERE r LIKE '%% %%' GROUP BY r ORDER BY c DESC LIMIT %s""", 4)
    roles = _top_values(conn, """
        SELECT role_category, count(*) c FROM postings
        WHERE is_active AND role_category IS NOT NULL AND role_category<>''
        GROUP BY role_category ORDER BY c DESC LIMIT %s""", 3)

    q: list[dict] = []

    def add(cat, text):
        q.append({"id": f"q{len(q)+1:02d}", "text": text, "category": cat})

    for t in techs[:6]:
        add("tech_only", f"{t} 개발자")
    for r in regions[:4]:
        add("region_only", f"{r} 개발자 채용")
    for text in ("신입 개발자 채용", "경력 3년 이상 개발자", "시니어 개발자"):
        add("exp_only", text)
    # 콤보 — 상위 지역 x 상위 기술
    if regions and techs:
        add("combo2", f"{regions[0].split()[-1]} {techs[0]} 개발자")   # 구어체 지역(시군구명만)
    if len(regions) > 1 and len(techs) > 1:
        add("combo2", f"{regions[1]} {techs[1]} 백엔드")
    for role in roles[:3]:
        add("role", f"{role} 채용")
    return q


# ---------- 2. 후보 풀링 (run_pool.py 로직 재사용) ----------

def _snippet(text: str, n: int = 200) -> str:
    return (text or "").replace("\n", " ")[:n]


def _build_candidate(row: dict, tags: set[str]) -> dict:
    return {
        "posting_uid": row["uid"], "company": row["company"], "title": row["title"],
        "regions": row["regions"], "tech": row["tech"], "exp_min": row["exp_min"],
        "snippet": _snippet(row.get("detail_text", "")),
        "source_axes": sorted(tags), "label": None,
    }


def build_pools(conn, vocab, queries: list[dict]) -> dict:
    result: dict = {}
    for q in queries:
        spec = parse_query(q["text"], vocab)
        [vec], _ = embed_texts([spec.text])
        system = hybrid_search(conn, spec, top_k=10)
        dense_pool = _dense_axis(conn, vec, spec, ("region", "exp"))[:POOL_K]
        bm25_pool = _bm25_axis(conn, spec, ("region", "exp"))[:POOL_K]

        pool_uids = {d[0] for d in dense_pool} | {t[0] for t in bm25_pool}
        with conn.cursor() as cur:
            cur.execute(
                """SELECT uid, company, title, regions, tech, exp_min, raw->>'detail_text'
                   FROM postings WHERE uid = ANY(%s)""",
                (list(pool_uids | {h.posting_uid for h in system.hits}),))
            cols = ("uid", "company", "title", "regions", "tech", "exp_min", "detail_text")
            rows = {r[0]: dict(zip(cols, r)) for r in cur.fetchall()}

        tags: dict[str, set[str]] = defaultdict(set)
        for h in system.hits:
            tags[h.posting_uid].add("system")
        for uid, _, _ in dense_pool:
            tags[uid].add("dense_pool")
        for uid, _, _ in bm25_pool:
            tags[uid].add("bm25_pool")

        sys_uids = [h.posting_uid for h in system.hits]
        pool_only = [uid for uid, _, _ in dense_pool if "system" not in tags[uid]]
        pool_only += [uid for uid, _, _ in bm25_pool
                      if "system" not in tags[uid] and uid not in pool_only]
        reserve = min(len(pool_only), POOL_RESERVE)
        order = sys_uids[:MAX_CANDIDATES - reserve]
        order += [u for u in pool_only if u not in order][:MAX_CANDIDATES - len(order)]
        order += [u for u in sys_uids if u not in order][:MAX_CANDIDATES - len(order)]

        result[q["id"]] = {
            "query": q["text"], "category": q["category"],
            "parsed": {"tech": spec.tech, "regions": spec.regions, "exp_years": spec.exp_years},
            "candidates": [_build_candidate(rows[uid], tags[uid]) for uid in order if uid in rows],
        }
    return result


# ---------- 3. 배치 LLM 라벨링 (질의당 1콜) ----------

LABEL_SYSTEM = """당신은 채용공고 검색결과의 관련성을 채점하는 평가자입니다.
[질문] 하나와 여러 개의 [공고]가 주어집니다. 각 공고를 질문 기준으로 채점하세요.
- C(Correct): 질문의 핵심 조건(직무/기술/경력/지역)에 실제로 부합
- A(Ambiguous): 일부만 부합하거나 애매함
- I(Incorrect): 관련 없거나 조건에 명백히 어긋남
출력은 공고 번호 순서대로 C/A/I 문자만 이어 붙인 한 줄. 다른 말 금지.
예: 공고 5개면 정확히 'CCAIC' 형식."""

_CODE = {"C": "Correct", "A": "Ambiguous", "I": "Incorrect"}


def _label_one_query(client: GmsClient, entry: dict) -> None:
    cands = entry["candidates"]
    if not cands:
        return
    lines = []
    for i, c in enumerate(cands, 1):
        exp = "무관" if c["exp_min"] is None else f"{c['exp_min']}년+"
        loc = ", ".join(c["regions"][:2]) or "미상"
        lines.append(f"[공고 {i}] {c['company']} | {c['title']} "
                     f"({exp} · {loc} · 기술: {', '.join(c['tech'][:6]) or '없음'})\n{c['snippet']}")
    user = f"[질문]\n{entry['query']}\n\n" + "\n\n".join(lines)
    try:
        raw = client._call(LABEL_SYSTEM, user, max_tokens=64).strip().upper()
    except Exception as e:  # noqa: BLE001
        raw = ""
        entry["label_error"] = f"{type(e).__name__}: {e}"
    codes = [ch for ch in raw if ch in _CODE]
    for i, c in enumerate(cands):
        c["label"] = _CODE.get(codes[i], "Ambiguous") if i < len(codes) else "Ambiguous"
        c["labeler"] = "llm-batch"


def label_pools(pools: dict, relabel: bool) -> None:
    client = GmsClient()
    for qid, entry in pools.items():
        if not relabel and all(c["label"] is not None for c in entry["candidates"]):
            continue
        _label_one_query(client, entry)


# ---------- 4. 평가 ----------

def evaluate(conn, vocab, pools: dict) -> dict:
    from jobrag.grader import grade_hit  # CRAG 그레이더(신규 기능) 검증용

    per_query = {}
    grader_confusion = defaultdict(int)   # (golden, grader) 쌍 카운트
    for qid, entry in pools.items():
        labels = {c["posting_uid"]: c["label"] for c in entry["candidates"]}
        rel = {uid for uid, label in labels.items() if label == "Correct"}
        judged = set(labels)
        spec = parse_query(entry["query"], vocab)
        r = hybrid_search(conn, spec, top_k=30)
        got = [h.posting_uid for h in r.hits if h.posting_uid in judged]

        recall = {k: (len(set(got[:k]) & rel) / len(rel) if rel else None) for k in RECALL_KS}
        rr = 0.0
        for i, u in enumerate(got[:10], 1):
            if u in rel:
                rr = 1 / i
                break
        roles = {h.role_category for h in r.hits[:10] if h.role_category}

        # CRAG 그레이더를 상위 5개(골든에 있는 것만)에 돌려 골든 라벨과 대조
        for h in r.hits[:5]:
            gold = labels.get(h.posting_uid)
            if gold is None:
                continue
            g = grade_hit(entry["query"], h)  # correct/ambiguous/incorrect
            grader_confusion[(gold.lower(), g)] += 1

        per_query[qid] = {
            "query": entry["query"], "category": entry["category"],
            "n_relevant": len(rel), "n_judged": len(judged),
            "recall": recall, "mrr": round(rr, 3),
            "relaxed": list(r.relaxed), "role_dispersion_at_10": len(roles),
            "reranked": r.reranked,
        }

    def _mean(vals):
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    label_dist = defaultdict(int)
    for entry in pools.values():
        for c in entry["candidates"]:
            label_dist[c["label"]] += 1

    # 그레이더-골든 일치도: 3x3을 correct/not으로 접어 정확도 계산
    total_pairs = sum(grader_confusion.values())
    agree = sum(v for (gold, g), v in grader_confusion.items() if gold == g)

    return {
        "n_queries": len(per_query),
        "recall_at_5": _mean([v["recall"][5] for v in per_query.values()]),
        "recall_at_10": _mean([v["recall"][10] for v in per_query.values()]),
        "mrr": _mean([v["mrr"] for v in per_query.values()]),
        "relaxed_rate": round(sum(1 for v in per_query.values() if v["relaxed"]) / len(per_query), 3),
        "role_dispersion_at_10": _mean([v["role_dispersion_at_10"] for v in per_query.values()]),
        "golden_label_distribution": dict(label_dist),
        "grader_vs_golden": {
            "n_pairs": total_pairs,
            "agreement": round(agree / total_pairs, 3) if total_pairs else None,
            "confusion": {f"{gold}->{g}": v for (gold, g), v in sorted(grader_confusion.items())},
        },
        "recall_by_category": _by_category(per_query),
        "per_query": per_query,
    }


def _by_category(per_query: dict) -> dict:
    by_cat = defaultdict(list)
    for v in per_query.values():
        if v["recall"][10] is not None:
            by_cat[v["category"]].append(v["recall"][10])
    return {c: round(sum(x) / len(x), 3) for c, x in sorted(by_cat.items())}


# ---------- main ----------

def main():
    relabel = "--relabel" in sys.argv
    OUT_DIR.mkdir(exist_ok=True)
    conn = connect()
    register_vector(conn)
    vocab = load_region_vocab(conn)

    # 풀 캐시 재사용(라벨 보존) — 없으면 새로 생성
    if POOL_OUT.exists() and not relabel:
        pools = json.loads(POOL_OUT.read_text(encoding="utf-8"))
        print(f"[pool] 캐시 로드 {len(pools)}질의")
    else:
        queries = build_queries(conn)
        print(f"[queries] {len(queries)}개 생성: {[q['text'] for q in queries]}")
        pools = build_pools(conn, vocab, queries)
        total = sum(len(v["candidates"]) for v in pools.values())
        print(f"[pool] {len(pools)}질의 / 후보 {total}건")

    print("[label] LLM 배치 라벨링...")
    label_pools(pools, relabel)
    POOL_OUT.write_text(json.dumps(pools, ensure_ascii=False, indent=2), encoding="utf-8")

    print("[eval] recall/MRR + 그레이더 대조...")
    report = evaluate(conn, vocab, pools)
    REPORT_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    conn.close()
    print(f"\n-> {REPORT_OUT}")
    summary = {k: v for k, v in report.items() if k not in ("per_query",)}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
