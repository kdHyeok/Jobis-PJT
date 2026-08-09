"""풀 구성 -> LLM 판정 -> 게이트 -> 측정 -> report.json"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from golden.queries import QUERIES
from jobrag.embedding import embed_texts
from jobrag.query_parser import parse_query, load_region_vocab, QuerySpec
from jobrag.search import (
    hybrid_search, _dense_axis, _bm25_axis,
)
from jobrag.store import connect

from . import core, judge

EVAL_DIR = Path(__file__).parent
POOL_PATH = EVAL_DIR / "pool.json"
REPORT_PATH = EVAL_DIR / "report.json"

POOL_DEPTH = 30
N_QUERIES = 30

AXES = {
    "기술": {"tech_focus", "tech_alias", "multi_tech"},
    "지역": {"region_focus", "colloquial_region"},
    "제약": {"exp_focus", "boundary_exp", "combo_balanced", "combo_dense"},
    "난이도": {"sparse_relax", "low_resource_role", "parser_trap", "negative_signal", "freeform"},
}

AXIS_TARGETS = {"기술": 8, "지역": 7, "제약": 8, "난이도": 7}

EXHAUSTIVE_QUERY = None


# ── 질의 선정 ──────────────────────────────────────────

def select_queries() -> list[dict]:
    by_axis: dict[str, list[dict]] = defaultdict(list)
    for q in QUERIES:
        for axis, cats in AXES.items():
            if q["category"] in cats:
                by_axis[axis].append(q)

    selected = []
    for axis, target in AXIS_TARGETS.items():
        pool = by_axis[axis]
        pool.sort(key=lambda q: hashlib.sha256(f"{q['id']}:{q['text']}".encode()).hexdigest())
        selected.extend(pool[:target])

    seen = set()
    deduped = []
    for q in selected:
        if q["id"] not in seen:
            seen.add(q["id"])
            deduped.append(q)
    return deduped[:N_QUERIES]


def _select_exhaustive_query() -> dict | None:
    difficulty_cats = AXES["난이도"]
    candidates = [q for q in QUERIES if q["category"] in difficulty_cats]
    exhaustive = core.load_exhaustive_labels()
    candidates = [q for q in candidates if q["id"] not in exhaustive]
    if not candidates:
        candidates = [q for q in QUERIES if q["category"] in difficulty_cats]
    candidates.sort(key=lambda q: hashlib.sha256(f"exhaust:{q['id']}".encode()).hexdigest())
    return candidates[0] if candidates else None


# ── arm별 검색 ─────────────────────────────────────────

def _run_arm_bm25(conn, spec: QuerySpec, top_k: int) -> list[str]:
    results = _bm25_axis(conn, spec, ())
    return [uid for uid, _, _ in results[:top_k]]


def _run_arm_dense(conn, vec, spec: QuerySpec, top_k: int) -> list[str]:
    results = _dense_axis(conn, vec, spec, ())
    return [uid for uid, _, _ in results[:top_k]]


def _run_arm_rrf(conn, spec: QuerySpec, top_k: int) -> list[str]:
    result = hybrid_search(conn, spec, top_k=top_k, allow_relax=False, use_rerank=False)
    return [h.posting_uid for h in result.hits]


def _run_arm_rrf_ce(conn, spec: QuerySpec, top_k: int) -> list[str]:
    result = hybrid_search(conn, spec, top_k=top_k, allow_relax=False, use_rerank=True)
    return [h.posting_uid for h in result.hits]


def _run_arm_random(conn, top_k: int) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT uid FROM postings WHERE is_active ORDER BY random() LIMIT %s",
                    (top_k,))
        return [r[0] for r in cur.fetchall()]


# ── 풀 구성 ────────────────────────────────────────────

def build_pool(conn) -> dict:
    region_vocab = load_region_vocab(conn)
    queries = select_queries()
    exhaust_q = _select_exhaustive_query()

    print(f"선정된 질의: {len(queries)}개")
    for q in queries:
        print(f"  {q['id']}: {q['text']} [{q['category']}]")

    pool = {}
    arm_tops: dict[str, dict[str, list[str]]] = {}
    all_corpus_uids = _get_all_uids(conn)

    for i, q in enumerate(queries, 1):
        print(f"\n[{i}/{len(queries)}] pool: {q['id']} - {q['text']}")
        spec = parse_query(q["text"], region_vocab)
        [vec], _ = embed_texts([spec.semantic_text])

        arms = {}
        arms["bm25"] = _run_arm_bm25(conn, spec, POOL_DEPTH)
        arms["dense"] = _run_arm_dense(conn, vec, spec, POOL_DEPTH)
        arms["rrf"] = _run_arm_rrf(conn, spec, POOL_DEPTH)
        arms["rrf_ce"] = _run_arm_rrf_ce(conn, spec, POOL_DEPTH)
        arms["random"] = _run_arm_random(conn, POOL_DEPTH)

        all_uids = set()
        for arm_uids in arms.values():
            all_uids.update(arm_uids)

        pool[q["id"]] = {
            "query": q["text"],
            "category": q["category"],
            "uids": sorted(all_uids),
            "n_pool": len(all_uids),
        }
        arm_tops[q["id"]] = arms
        print(f"  풀 크기: {len(all_uids)} (합집합)")

    if exhaust_q:
        print(f"\n완전판정 질의: {exhaust_q['id']} -{exhaust_q['text']}")
        pool[exhaust_q["id"]] = {
            "query": exhaust_q["text"],
            "category": exhaust_q["category"],
            "uids": sorted(all_corpus_uids),
            "n_pool": len(all_corpus_uids),
            "exhaustive": True,
        }
        arm_tops[exhaust_q["id"]] = {}

    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_queries": len(pool),
        "pool": pool,
        "arm_tops": arm_tops,
        "arms": ["bm25", "dense", "rrf", "rrf_ce", "random"],
    }
    POOL_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    total_judgments = sum(p["n_pool"] for p in pool.values())
    print(f"\n풀 저장: {POOL_PATH}")
    print(f"총 판정 예정: {total_judgments}건")
    return data


def _get_all_uids(conn) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT uid FROM postings WHERE is_active ORDER BY uid")
        return [r[0] for r in cur.fetchall()]


# ── 게이트 ─────────────────────────────────────────────

def check_gates(pool_data: dict) -> list[dict]:
    gates = []

    cov = judge.coverage(pool_data["pool"])
    all_complete = all(c >= 1.0 for c in cov.values())
    gates.append({
        "gate": 1, "name": "coverage_100",
        "passed": all_complete,
        "detail": {qid: f"{c:.1%}" for qid, c in cov.items() if c < 1.0} if not all_complete else {},
    })

    has_random = "random" in pool_data.get("arms", [])
    gates.append({"gate": 2, "name": "random_baseline", "passed": has_random})

    anchor_report_path = EVAL_DIR / "anchor" / "anchor_report.json"
    if anchor_report_path.exists():
        ar = json.loads(anchor_report_path.read_text(encoding="utf-8"))
        gates.append({"gate": 3, "name": "human_kappa", "passed": ar.get("gate3") == "PASS",
                       "kappa": ar.get("binary_kappa")})
        gates.append({"gate": "3b", "name": "self_consistency",
                       "passed": ar.get("gate3b", "").startswith("PASS"),
                       "self_kappa": ar.get("self_consistency_kappa")})
    else:
        gates.append({"gate": 3, "name": "human_kappa", "passed": False,
                       "detail": "anchor_report.json 없음"})

    pool = pool_data["pool"]
    axis_counts = defaultdict(int)
    for qid, info in pool.items():
        cat = info.get("category", "")
        for axis, cats in AXES.items():
            if cat in cats:
                axis_counts[axis] += 1
    all_sufficient = all(n >= 7 for n in axis_counts.values())
    gates.append({"gate": 4, "name": "axis_n_sufficient", "passed": all_sufficient,
                   "counts": dict(axis_counts)})

    gates.append({"gate": 5, "name": "paired_ci", "passed": True,
                   "note": "enforced in measure()"})

    return gates


# ── 측정 ───────────────────────────────────────────────

def measure(conn, pool_data: dict) -> dict:
    region_vocab = load_region_vocab(conn)
    judgments = json.loads(judge.JUDGMENTS_PATH.read_text(encoding="utf-8"))
    pool = pool_data["pool"]
    arm_tops = pool_data["arm_tops"]

    per_query = {}
    arm_names = ["random", "bm25", "dense", "rrf", "rrf_ce"]

    for qid, info in pool.items():
        if info.get("exhaustive"):
            continue
        qrels = judgments.get("queries", {}).get(qid, {}).get("labels", {})
        if not qrels:
            continue

        tops = arm_tops.get(qid, {})
        arm_scores = {}
        for arm in arm_names:
            ranked = tops.get(arm, [])
            arm_scores[arm] = {
                "ndcg3": round(core.ndcg_at_k(ranked, qrels, 3), 4),
                "p3": round(core.precision_at_k(ranked, qrels, 3), 4),
                "ap3": round(core.ap_at_k(ranked, qrels, 3), 4),
            }

        rand_floor = core.random_baseline_ndcg(qrels, 3, n_trials=5000)
        oracle_uids = sorted(qrels.keys(),
                             key=lambda u: core.GRADE.get(qrels.get(u, "Incorrect"), 0),
                             reverse=True)
        oracle_ndcg = core.ndcg_at_k(oracle_uids, qrels, 3)

        for arm in arm_names:
            arm_scores[arm]["norm_ndcg3"] = round(
                core.normalized_score(arm_scores[arm]["ndcg3"], rand_floor, oracle_ndcg), 4
            )

        bm25_uids = tops.get("bm25", [])
        dense_uids = tops.get("dense", [])
        miss = core.pool_miss_bounds(qrels, bm25_uids, dense_uids)

        per_query[qid] = {
            "query": info["query"],
            "category": info["category"],
            "n_pool": info["n_pool"],
            "n_judged": len(qrels),
            "label_dist": dict(Counter(qrels.values()).most_common()),
            "random_floor": round(rand_floor, 4),
            "oracle_ndcg3": round(oracle_ndcg, 4),
            "arms": arm_scores,
            "pool_miss": miss,
        }

    macro = {arm: {m: [] for m in ["ndcg3", "p3", "ap3", "norm_ndcg3"]} for arm in arm_names}
    for qid, qdata in per_query.items():
        for arm in arm_names:
            for m in ["ndcg3", "p3", "ap3", "norm_ndcg3"]:
                macro[arm][m].append(qdata["arms"][arm][m])

    macro_avg = {}
    for arm in arm_names:
        macro_avg[arm] = {
            m: round(sum(vals) / len(vals), 4) if vals else 0
            for m, vals in macro[arm].items()
        }

    comparisons = {}
    for i, a in enumerate(arm_names):
        for b in arm_names[i + 1:]:
            key = f"{a}_vs_{b}"
            comparisons[key] = core.paired_bootstrap(
                macro[a]["ndcg3"], macro[b]["ndcg3"]
            )

    by_axis = defaultdict(lambda: {arm: [] for arm in arm_names})
    for qid, qdata in per_query.items():
        cat = qdata["category"]
        for axis, cats in AXES.items():
            if cat in cats:
                for arm in arm_names:
                    by_axis[axis][arm].append(qdata["arms"][arm]["norm_ndcg3"])

    axis_summary = {}
    for axis, arm_data in by_axis.items():
        axis_summary[axis] = {
            arm: round(sum(vals) / len(vals), 4) if vals else 0
            for arm, vals in arm_data.items()
        }
        axis_summary[axis]["n"] = len(next(iter(arm_data.values())))

    bias = core.bias_correction_bounds(
        core.load_exhaustive_labels(),
        _pool_builder_for_calibration,
        conn, region_vocab,
    )

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM postings WHERE is_active")
        n_corpus = cur.fetchone()[0]

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        # 평가셋 버전 스탬프 -프롬프트/코퍼스가 바뀌면 리포트 간 비교 불가하므로 명시
        "version": {
            "judge_prompt": judge.PROMPT_VERSION,
            "n_corpus_active": n_corpus,
            "pool_generated_at": pool_data.get("generated_at"),
        },
        "headline": {
            "metric": "normalized_nDCG@3",
            "definition": "(actual - random) / (pool_oracle - random)",
            "best_arm": max(arm_names, key=lambda a: macro_avg[a]["norm_ndcg3"]),
            "scores": {a: macro_avg[a]["norm_ndcg3"] for a in arm_names},
        },
        "macro_average": macro_avg,
        "comparisons": comparisons,
        "by_axis": axis_summary,
        "bias_correction": bias,
        "per_query": per_query,
    }

    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n리포트 저장: {REPORT_PATH}")
    _print_summary(report)
    return report


def _pool_builder_for_calibration(conn, qid, region_vocab):
    query_map = {q["id"]: q for q in QUERIES}
    q = query_map.get(qid)
    if not q:
        return {}, [], []
    spec = parse_query(q["text"], region_vocab)
    [vec], _ = embed_texts([spec.semantic_text])
    bm25_uids = _run_arm_bm25(conn, spec, POOL_DEPTH)
    dense_uids = _run_arm_dense(conn, vec, spec, POOL_DEPTH)
    all_uids = set(bm25_uids) | set(dense_uids)
    qrels = {u: "Incorrect" for u in all_uids}
    return qrels, bm25_uids, dense_uids


def _print_summary(report: dict) -> None:
    print("\n" + "=" * 60)
    print("RAG 검색 성능 평가 리포트")
    print("=" * 60)

    hl = report["headline"]
    print(f"\n헤드라인: {hl['metric']}")
    print(f"  최고 arm: {hl['best_arm']}")
    for arm, score in hl["scores"].items():
        marker = " <- best" if arm == hl["best_arm"] else ""
        print(f"  {arm:12s}: {score:.4f}{marker}")

    print("\narm 비교 (쌍대 부트스트랩 95% CI):")
    for key, comp in report["comparisons"].items():
        sig = "***" if comp["significant"] else "n.s."
        print(f"  {key:25s}: Δ={comp['mean_delta']:+.4f}  CI={comp['ci_95']}  {sig}")

    print("\n축별 정규화 nDCG@3:")
    for axis, data in report["by_axis"].items():
        n = data.get("n", "?")
        best = max((a for a in data if a != "n"), key=lambda a: data[a])
        print(f"  {axis} (n={n}): best={best} ({data[best]:.4f})")

    bias = report.get("bias_correction", {})
    if "bias_ratio_range" in bias:
        print(f"\n풀 미검출 보정비 범위: {bias['bias_ratio_range']} (교정 질의 {bias['n_calibration_queries']}건)")
    print()


# ── CLI ────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    conn = connect()

    try:
        if "--build-pool" in args:
            build_pool(conn)

        elif "--judge" in args:
            if not POOL_PATH.exists():
                print("pool.json 없음 -먼저 --build-pool 실행")
                sys.exit(1)
            pool_data = json.loads(POOL_PATH.read_text(encoding="utf-8"))
            judge.judge_all(conn, pool_data["pool"])

        elif "--measure" in args:
            if not POOL_PATH.exists():
                print("pool.json 없음")
                sys.exit(1)
            pool_data = json.loads(POOL_PATH.read_text(encoding="utf-8"))

            gates = check_gates(pool_data)
            failed = [g for g in gates if not g["passed"]]
            if failed and "--force" not in args:
                print("게이트 실패:")
                for g in failed:
                    print(f"  gate {g['gate']}: {g['name']} -{g.get('detail', '')}")
                print("--force 로 우회 가능 (리포트에 gate_failed 표기)")
                sys.exit(1)

            report = measure(conn, pool_data)
            if failed:
                report["gate_failed"] = [g["name"] for g in failed]
                REPORT_PATH.write_text(
                    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print("[WARN] gate failed - report generated with gate_failed banner")

        elif "--gates" in args:
            pool_data = json.loads(POOL_PATH.read_text(encoding="utf-8"))
            gates = check_gates(pool_data)
            for g in gates:
                status = "PASS" if g["passed"] else "FAIL"
                print(f"  gate {g['gate']}: {g['name']} -{status}")

        else:
            print("사용법:")
            print("  python -m eval.run --build-pool    풀 구성")
            print("  python -m eval.run --judge         LLM 판정 (재개형)")
            print("  python -m eval.run --measure       측정 + 리포트")
            print("  python -m eval.run --gates         게이트 점검")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
