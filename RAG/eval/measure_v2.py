# -*- coding: utf-8 -*-
"""측정 v2 — pool_v2 원자 + 판정 캐시 위에서 모든 arm을 오프라인 재조합.

재검색·재판정 없이 계산되는 것:
  기본 arm: random / dense / bm25 / rrf / rrf_ce / rrf_noregion / rrf_nofilter / rrf_relax / alpha 융합
  스윕: RRF_K {10,20,40,60,90} · CANDIDATE_K {10..50} · RERANK_TOP_N {5..30}
        · min_results {3,5,8} · alpha {0.3,0.5,0.7} × 정규화 {minmax,zscore}
  소실 퍼널: 오라클 top-3 기준 상호배타 원인 귀속 (파이프라인 순서)
  원인 태깅: parser_error / data_missing_regions(recall) / data_missing_exp(precision)

결정 규칙(사전등록 §2·§3)을 리포트에 판정문으로 출력한다.

실행: python -m eval.measure_v2            # 게이트 통과 시 리포트
      python -m eval.measure_v2 --force    # 게이트 실패 배너 달고 강행
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import core, judge

EVAL_DIR = Path(__file__).parent
POOL_PATH = EVAL_DIR / "pool_v2.json"
REPORT_PATH = EVAL_DIR / "report_v2.json"

# v2 판정 캐시 고정 (judge_v2와 동일 — 구 판정과 혼용 금지)
judge.JUDGMENTS_PATH = EVAL_DIR / "judgments_v2.json"

TOP_K = 3
MIN_RESULTS_DEFAULT = 5

SWEEP_RRF_K = [10, 20, 40, 60, 90]
SWEEP_CAND_K = [10, 20, 30, 40, 50]
SWEEP_RERANK_N = [5, 10, 15, 20, 30]
SWEEP_MIN_RESULTS = [3, 5, 8]
SWEEP_ALPHA = [0.3, 0.5, 0.7]
DEFAULTS = {"rrf_k": 60, "cand_k": 30, "rerank_n": 15, "min_results": 5}
PLATEAU_EPS = 0.01

AXES = {
    "기술": {"tech_focus", "tech_alias", "multi_tech"},
    "지역": {"region_focus", "colloquial_region"},
    "제약": {"exp_focus", "boundary_exp", "combo_balanced", "combo_dense"},
    "난이도": {"sparse_relax", "low_resource_role", "parser_trap", "negative_signal", "freeform"},
}


# ── arm 재조합 프리미티브 ───────────────────────────────

def _competition_ranks(pairs: list[list]) -> dict[str, int]:
    """[[uid, score]…] → {uid: 경쟁순위}. 동점은 같은 순위(프로덕션 _search_once와 동일)."""
    ranks, prev_score, prev_rank = {}, None, 0
    for i, (uid, score) in enumerate(pairs, 1):
        rank = prev_rank if score == prev_score else i
        prev_score, prev_rank = score, rank
        ranks[uid] = rank
    return ranks


def rrf_fuse(dense_atom: list[list], bm25_atom: list[list],
             rrf_k: int = 60, cand_k: int = 30) -> list[tuple[str, float]]:
    """원자 top-cand_k 프리픽스를 RRF 병합 → [(uid, rrf)] 내림차순. 타이는 uid."""
    d_ranks = _competition_ranks(dense_atom[:cand_k])
    b_ranks = _competition_ranks(bm25_atom[:cand_k])
    scores: dict[str, float] = defaultdict(float)
    for uid, r in d_ranks.items():
        scores[uid] += 1.0 / (rrf_k + r)
    for uid, r in b_ranks.items():
        scores[uid] += 1.0 / (rrf_k + r)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def apply_ce(ranked: list[tuple[str, float]], ce: dict[str, float | None],
             top_n: int = 15) -> list[str]:
    """상위 top_n만 CE 점수로 재정렬(계층 없음 — full 구성은 전부 exact). CE 없는 항목은 최하."""
    pool, rest = ranked[:top_n], ranked[top_n:]
    pool = sorted(pool, key=lambda kv: (
        -(ce.get(kv[0]) if ce.get(kv[0]) is not None else float("-inf")),
        -kv[1], kv[0],
    ))
    return [u for u, _ in pool] + [u for u, _ in rest]


def alpha_fuse(dense_atom, bm25_atom, scores_cache: dict, alpha: float,
               norm: str, cand_k: int = 30) -> list[str]:
    """가중합 융합 — 후보는 RRF와 동일(양축 top-cand_k 합집합), 점수는 교차 캐시."""
    cands = {u for u, _ in dense_atom[:cand_k]} | {u for u, _ in bm25_atom[:cand_k]}
    d = {u: (scores_cache.get(u, {}).get("dense") or 0.0) for u in cands}
    b = {u: (scores_cache.get(u, {}).get("bm25") or 0.0) for u in cands}

    def normalize(vals: dict) -> dict:
        xs = list(vals.values())
        if norm == "minmax":
            lo, hi = min(xs), max(xs)
            return {u: (v - lo) / (hi - lo) if hi > lo else 0.0 for u, v in vals.items()}
        mu = statistics.mean(xs)
        sd = statistics.pstdev(xs)
        return {u: (v - mu) / sd if sd > 0 else 0.0 for u, v in vals.items()}

    dn, bn = normalize(d), normalize(b)
    fused = {u: alpha * dn[u] + (1 - alpha) * bn[u] for u in cands}
    return [u for u, _ in sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))]


def relax_merge(q: dict, rrf_k: int = 60, cand_k: int = 30,
                min_results: int = 5) -> list[str]:
    """hybrid_search 완화 병합 시뮬레이션 (수정 후 로직: 누적 병합 + 계층 정렬)."""
    sc = q["scores"]

    def exact(uid: str) -> bool:
        f = sc.get(uid, {})
        return f.get("ok_region", True) and f.get("ok_exp", True)

    merged = rrf_fuse(q["atoms"]["dense_full"], q["atoms"]["bm25_full"], rrf_k, cand_k)
    merged = [(u, r) for u, r in merged]
    spec = q["spec"]
    active = {"noregion": bool(spec["regions"]),
              "nofilter": bool(spec["regions"]) or spec["exp_years"] is not None}
    if len(merged) < min_results:
        seen = {u for u, _ in merged}
        for cfg in ("noregion", "nofilter"):
            if not active[cfg]:
                continue
            extra = rrf_fuse(q["atoms"][f"dense_{cfg}"], q["atoms"][f"bm25_{cfg}"],
                             rrf_k, cand_k)
            new = [(u, r) for u, r in extra if u not in seen]
            seen |= {u for u, _ in new}
            merged = merged + new
            merged.sort(key=lambda kv: (not exact(kv[0]), -kv[1], kv[0]))
            if len(merged) >= min_results:
                break
    return [u for u, _ in merged]


# ── arm 정의 ────────────────────────────────────────────

def build_arms(q: dict) -> dict[str, list[str]]:
    a, sc = q["atoms"], q["scores"]
    ce = {u: v.get("ce") for u, v in sc.items()}
    rrf_full = rrf_fuse(a["dense_full"], a["bm25_full"])
    arms = {
        "random": q["random"],
        "dense": [u for u, _ in a["dense_full"]],
        "bm25": [u for u, _ in a["bm25_full"]],
        "rrf": [u for u, _ in rrf_full],
        "rrf_ce": apply_ce(rrf_full, ce, DEFAULTS["rerank_n"]),
        "rrf_noregion": [u for u, _ in rrf_fuse(a["dense_noregion"], a["bm25_noregion"])],
        "rrf_nofilter": [u for u, _ in rrf_fuse(a["dense_nofilter"], a["bm25_nofilter"])],
        "rrf_relax": relax_merge(q),
        "alpha_0.5_minmax": alpha_fuse(a["dense_full"], a["bm25_full"], sc, 0.5, "minmax"),
    }
    return arms


ARM_NAMES = ["random", "dense", "bm25", "rrf", "rrf_ce",
             "rrf_noregion", "rrf_nofilter", "rrf_relax", "alpha_0.5_minmax"]


# ── 지표 ────────────────────────────────────────────────

def q_metrics(ranked: list[str], qrels: dict[str, str],
              rand_floor: float, oracle: float) -> dict:
    nd = core.ndcg_at_k(ranked, qrels, TOP_K)
    return {
        "ndcg3": round(nd, 4),
        "p3": round(core.precision_at_k(ranked, qrels, TOP_K), 4),
        "norm_ndcg3": round(core.normalized_score(nd, rand_floor, oracle), 4),
    }


def plateau_pick(curve: dict, default) -> dict:
    """스윕 곡선에서 고원 선택 — best-ε 이내 값들 중 기본값 우선, 없으면 최장 연속구간 중앙."""
    best = max(curve.values())
    eligible = [k for k, v in curve.items() if v >= best - PLATEAU_EPS]
    if default in eligible:
        chosen = default
    else:
        keys = list(curve.keys())
        runs, cur = [], []
        for k in keys:
            if k in eligible:
                cur.append(k)
            else:
                if cur:
                    runs.append(cur)
                cur = []
        if cur:
            runs.append(cur)
        longest = max(runs, key=len)
        chosen = longest[len(longest) // 2]
    return {"curve": {str(k): round(v, 4) for k, v in curve.items()},
            "best": max(curve, key=curve.get), "plateau_choice": chosen,
            "default": default, "changed": chosen != default}


# ── 소실 퍼널 (오라클 top-3 기준, 상호배타) ─────────────

def loss_funnel(q: dict, qrels: dict[str, str], parser: dict,
                final_arm: list[str]) -> dict:
    """오라클 top-3 문서별로 최초 소실 지점 1개를 귀속. 파이프라인 순서로 검사."""
    grade = core.GRADE
    oracle3 = sorted(qrels, key=lambda u: (-grade.get(qrels[u], 0), u))[:TOP_K]
    oracle3 = [u for u in oracle3 if grade.get(qrels[u], 0) >= 1]

    a, sc = q["atoms"], q["scores"]
    cand_full = ({u for u, _ in a["dense_full"][:DEFAULTS["cand_k"]]}
                 | {u for u, _ in a["bm25_full"][:DEFAULTS["cand_k"]]})
    deep_full = ({u for u, _ in a["dense_full"]} | {u for u, _ in a["bm25_full"]})
    nofilter_deep = ({u for u, _ in a["dense_nofilter"]} | {u for u, _ in a["bm25_nofilter"]})
    rrf3 = [u for u, _ in rrf_fuse(a["dense_full"], a["bm25_full"])[:TOP_K]]
    final3 = set(final_arm[:TOP_K])
    parser_bad = parser.get("has_expected") and not (
        parser.get("region_match", True) and parser.get("exp_match", True))

    tags = []
    for uid in oracle3:
        if uid in final3:
            continue
        f = sc.get(uid, {})
        if not (f.get("ok_region", True) and f.get("ok_exp", True)):
            # 하드필터에서 탈락 — recall 손실. 원인 세분화
            if parser_bad:
                cause = "parser_error_filtered"
            elif not f.get("ok_region", True) and not f.get("regions"):
                cause = "data_missing_regions"   # 메타데이터 공백이 지역필터 탈락 유발
            else:
                cause = "filter_region" if not f.get("ok_region", True) else "filter_exp"
        elif uid not in deep_full:
            cause = "both_axes_missed" if uid in nofilter_deep else "outside_pool_atoms"
        elif uid not in cand_full:
            cause = "candidate_window"           # 깊이 50엔 있으나 CANDIDATE_K=30 창 밖
        elif uid not in rrf3:
            cause = "fusion_rank"                # 후보엔 있으나 RRF가 top-3로 못 올림
        else:
            cause = "ce_demoted"                 # RRF top-3였는데 CE가 밀어냄
        tags.append({"uid": uid, "grade": qrels[uid], "cause": cause})

    # precision 방향: 최종 top-3에 들어온 비관련 문서의 원인
    prec = []
    for uid in final_arm[:TOP_K]:
        if grade.get(qrels.get(uid, "Incorrect"), 0) == 0:
            f = sc.get(uid, {})
            cause = "data_missing_exp" if f.get("exp_min") is None and \
                q["spec"]["exp_years"] is not None else "ranking_error"
            prec.append({"uid": uid, "cause": cause})
    return {"oracle_top3": oracle3, "recall_losses": tags, "precision_intrusions": prec}


# ── 메인 측정 ───────────────────────────────────────────

def measure() -> dict:
    pool = json.loads(POOL_PATH.read_text(encoding="utf-8"))
    judgments = json.loads(judge.JUDGMENTS_PATH.read_text(encoding="utf-8"))

    per_query, funnels = {}, {}
    macro: dict[str, list[float]] = defaultdict(list)
    macro_raw: dict[str, list[float]] = defaultdict(list)
    sweep_scores: dict[str, dict] = defaultdict(lambda: defaultdict(list))

    for qid, q in pool["queries"].items():
        qrels = judgments.get("queries", {}).get(qid, {}).get("labels", {})
        if not qrels:
            continue
        rand_floor = core.random_baseline_ndcg(qrels, TOP_K, n_trials=5000)
        oracle_uids = sorted(qrels, key=lambda u: -core.GRADE.get(qrels[u], 0))
        oracle = core.ndcg_at_k(oracle_uids, qrels, TOP_K)

        arms = build_arms(q)
        qm = {}
        for name, ranked in arms.items():
            m = q_metrics(ranked, qrels, rand_floor, oracle)
            qm[name] = m
            macro[name].append(m["norm_ndcg3"])
            macro_raw[name].append(m["ndcg3"])

        a, sc = q["atoms"], q["scores"]
        ce = {u: v.get("ce") for u, v in sc.items()}
        for k in SWEEP_RRF_K:
            r = [u for u, _ in rrf_fuse(a["dense_full"], a["bm25_full"], rrf_k=k)]
            sweep_scores["rrf_k"][k].append(
                q_metrics(r, qrels, rand_floor, oracle)["norm_ndcg3"])
        for ck in SWEEP_CAND_K:
            r = [u for u, _ in rrf_fuse(a["dense_full"], a["bm25_full"], cand_k=ck)]
            sweep_scores["cand_k"][ck].append(
                q_metrics(r, qrels, rand_floor, oracle)["norm_ndcg3"])
        rrf_full = rrf_fuse(a["dense_full"], a["bm25_full"])
        for n in SWEEP_RERANK_N:
            r = apply_ce(rrf_full, ce, n)
            sweep_scores["rerank_n"][n].append(
                q_metrics(r, qrels, rand_floor, oracle)["norm_ndcg3"])
        for mr in SWEEP_MIN_RESULTS:
            r = relax_merge(q, min_results=mr)
            sweep_scores["min_results"][mr].append(
                q_metrics(r, qrels, rand_floor, oracle)["norm_ndcg3"])
        for al in SWEEP_ALPHA:
            for nm in ("minmax", "zscore"):
                r = alpha_fuse(a["dense_full"], a["bm25_full"], sc, al, nm)
                sweep_scores["alpha"][f"{al}_{nm}"].append(
                    q_metrics(r, qrels, rand_floor, oracle)["norm_ndcg3"])

        funnels[qid] = loss_funnel(q, qrels, pool["parser_check"].get(qid, {}),
                                   arms["rrf_ce"])
        per_query[qid] = {
            "query": q["query"], "category": q["category"],
            "n_pool": q["n_pool"], "n_judged": len(qrels),
            "label_dist": dict(Counter(qrels.values())),
            "random_floor": round(rand_floor, 4), "oracle_ndcg3": round(oracle, 4),
            "arms": qm,
        }

    n_q = len(per_query)
    macro_avg = {name: round(sum(v) / len(v), 4) for name, v in macro.items()}

    # 결정 규칙 비교 (쌍대 부트스트랩, 정규화 nDCG@3)
    def cmp(a_name, b_name):
        return core.paired_bootstrap(macro[a_name], macro[b_name])

    decisions = {}
    c = cmp("rrf", "rrf_ce")
    decisions["CE_리랭커"] = {
        "rule": "rrf vs rrf_ce — CI가 0을 걸치면 제거",
        **c,
        "verdict": ("유지" if c["significant"] and c["mean_delta"] > 0 else "제거"),
    }
    c = cmp("dense", "rrf")
    decisions["BM25_축"] = {
        "rule": "dense vs rrf — rrf가 유의하게 낫지 않으면 BM25 축 제거",
        **c,
        "verdict": ("유지" if c["significant"] and c["mean_delta"] > 0 else "제거"),
    }
    c = cmp("rrf_nofilter", "rrf")
    decisions["하드필터"] = {
        "rule": "rrf vs rrf_nofilter — 필터 이득 없으면 랭킹 주장에서 제외",
        **c,
        "verdict": ("유지" if c["significant"] and c["mean_delta"] > 0
                    else "UX요구사항으로만_유지"),
    }
    c = cmp("rrf", "rrf_relax")
    decisions["완화_로직"] = {
        "rule": "rrf vs rrf_relax — nDCG를 깎으면 제거·단순화",
        **c,
        "verdict": ("제거_또는_단순화" if c["significant"] and c["mean_delta"] < 0 else "유지"),
    }
    best_alpha = max(sweep_scores["alpha"],
                     key=lambda k: sum(sweep_scores["alpha"][k]) / n_q)
    c = core.paired_bootstrap(macro["rrf"], sweep_scores["alpha"][best_alpha])
    decisions["융합_방식"] = {
        "rule": "alpha 가중합 vs RRF — 유의차 없으면 단순한 쪽(RRF) 유지",
        "best_alpha": best_alpha, **c,
        "verdict": ("가중합_채택" if c["significant"] and c["mean_delta"] > 0 else "RRF_유지"),
    }
    decisions["role_category_필터"] = {
        "rule": "role_on vs role_off — adapter 시나리오",
        "verdict": "측정불가_이번회차제외",
        "note": "role_category 하드필터는 이미 코드에서 제거됨(search.py). adapter 경유 "
                "시나리오는 골든셋에 role 지정 질의가 없어 이번 풀로는 측정 불가.",
    }
    decisions["쿼리_파서"] = {
        "rule": "rrf vs rrf_rawtext — 파서 기여 없으면 단순화",
        "note": "spec.text가 원문 그대로라 rawtext arm ≡ rrf_nofilter(필터만 파서 산출물).",
        "delegated_to": "하드필터",
    }

    sweeps = {
        "rrf_k": plateau_pick({k: sum(v) / n_q for k, v in sweep_scores["rrf_k"].items()},
                              DEFAULTS["rrf_k"]),
        "cand_k": plateau_pick({k: sum(v) / n_q for k, v in sweep_scores["cand_k"].items()},
                               DEFAULTS["cand_k"]),
        "rerank_n": plateau_pick({k: sum(v) / n_q for k, v in sweep_scores["rerank_n"].items()},
                                 DEFAULTS["rerank_n"]),
        "min_results": plateau_pick({k: sum(v) / n_q
                                     for k, v in sweep_scores["min_results"].items()},
                                    DEFAULTS["min_results"]),
        "alpha": {k: round(sum(v) / n_q, 4) for k, v in sweep_scores["alpha"].items()},
    }

    # 축별 집계
    by_axis = defaultdict(lambda: defaultdict(list))
    for qid, qd in per_query.items():
        for axis, cats in AXES.items():
            if qd["category"] in cats:
                for arm in ARM_NAMES:
                    by_axis[axis][arm].append(qd["arms"][arm]["norm_ndcg3"])
    axis_summary = {
        axis: {**{arm: round(sum(v) / len(v), 4) for arm, v in arms.items()},
               "n": len(next(iter(arms.values())))}
        for axis, arms in by_axis.items()
    }

    # 퍼널 집계
    funnel_counts = Counter(t["cause"] for f in funnels.values() for t in f["recall_losses"])
    prec_counts = Counter(t["cause"] for f in funnels.values()
                          for t in f["precision_intrusions"])

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pool_meta": pool["meta"],
        "judge_backend": judge.backend_id(),
        "n_queries_scored": n_q,
        "headline": {
            "metric": "normalized nDCG@3 (dev 30, 풀 오라클 대비)",
            "best_arm": max(macro_avg, key=macro_avg.get),
            "scores": macro_avg,
            "raw_ndcg3": {k: round(sum(v) / len(v), 4) for k, v in macro_raw.items()},
        },
        "decisions": decisions,
        "sweeps": sweeps,
        "by_axis": axis_summary,
        "loss_funnel": {
            "recall_causes": dict(funnel_counts.most_common()),
            "precision_causes": dict(prec_counts.most_common()),
            "per_query": funnels,
        },
        "parser_check_summary": {
            "n_mismatch": sum(1 for p in pool["parser_check"].values()
                              if p.get("has_expected") and
                              not (p["region_match"] and p["exp_match"])),
            "mismatched": [qid for qid, p in pool["parser_check"].items()
                           if p.get("has_expected") and
                           not (p["region_match"] and p["exp_match"])],
        },
        "scope_notes": [
            "판정자: " + judge.backend_id() + " — 단일 모델·단일 프롬프트, 앵커 대리 검증(사전등록 §5)",
            "지역/구어체 축 절대수치는 참고용 (사람 앵커 미커버)",
            "holdout 35질의 봉인 — 스윕 확정 후 개봉해 재확인",
        ],
        "per_query": per_query,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    return report


# ── 게이트 ──────────────────────────────────────────────

def check_gates(pool: dict) -> list[dict]:
    gates = []
    judgments = json.loads(judge.JUDGMENTS_PATH.read_text(encoding="utf-8")) \
        if judge.JUDGMENTS_PATH.exists() else {"queries": {}}
    cov_fail = {}
    for qid, q in pool["queries"].items():
        labels = judgments.get("queries", {}).get(qid, {}).get("labels", {})
        missing = [u for u in q["uids"] if u not in labels]
        if missing:
            cov_fail[qid] = len(missing)
    gates.append({"gate": 1, "name": "coverage_100", "passed": not cov_fail,
                  "detail": cov_fail})
    gates.append({"gate": 2, "name": "random_baseline",
                  "passed": all("random" in q for q in pool["queries"].values())})

    precal = EVAL_DIR / "anchor" / f"precal_report_{judge.PROMPT_VERSION}.json"
    if precal.exists():
        pr = json.loads(precal.read_text(encoding="utf-8"))
        gates.append({"gate": "3a", "name": "judge_kappa_anchor120",
                      "passed": pr.get("gate_3a") == "PASS",
                      "kappa_binary_strict": pr.get("kappa_binary_strict")})
    else:
        gates.append({"gate": "3a", "name": "judge_kappa_anchor120", "passed": False,
                      "detail": f"{precal.name} 없음"})

    diff = EVAL_DIR / "anchor" / "difficulty_check_report.json"
    if diff.exists():
        dr = json.loads(diff.read_text(encoding="utf-8"))
        # 사전등록 §4-3b: 미달 시 리포트 차단이 아니라 난이도 축 결론 conclusive:false
        gates.append({"gate": "3b", "name": "difficulty_15pairs",
                      "passed": dr.get("passed", False),
                      "agree": f"{dr.get('n_agree')}/{dr.get('n_scored')}",
                      "soft": True})
    else:
        gates.append({"gate": "3b", "name": "difficulty_15pairs", "passed": False,
                      "detail": "difficulty_check_report.json 없음 — 04 시트 채점 후 생성",
                      "soft": True})   # 난이도 축 결론만 conclusive:false 처리 가능

    sc = EVAL_DIR / "anchor" / "self_consistency_report.json"
    if sc.exists() and precal.exists():
        s = json.loads(sc.read_text(encoding="utf-8"))
        p = json.loads(precal.read_text(encoding="utf-8"))
        ok = s.get("kappa_binary_strict", 0) >= p.get("kappa_binary_strict", 1)
        gates.append({"gate": 4, "name": "self_consistency_vs_judge", "passed": ok,
                      "human_self": s.get("kappa_binary_strict"),
                      "judge": p.get("kappa_binary_strict"),
                      "note": "사람 자기일관성 < judge κ면 게이트3 해석 무효"})
    axis_n = Counter()
    for q in pool["queries"].values():
        for axis, cats in AXES.items():
            if q["category"] in cats:
                axis_n[axis] += 1
    gates.append({"gate": 5, "name": "axis_n>=7",
                  "passed": all(axis_n[a] >= 7 for a in AXES), "counts": dict(axis_n)})
    return gates


def _print_summary(report: dict) -> None:
    print("\n" + "=" * 64)
    print("RAG 검색 성능 리포트 v2 (dev 30)")
    print("=" * 64)
    hl = report["headline"]
    print(f"\n[정규화 nDCG@3] best={hl['best_arm']}")
    for arm, s in sorted(hl["scores"].items(), key=lambda kv: -kv[1]):
        print(f"  {arm:18s} {s:.4f}")
    print("\n[결정]")
    for name, d in report["decisions"].items():
        extra = f" Δ={d.get('mean_delta', '')} CI={d.get('ci_95', '')}" \
            if "mean_delta" in d else ""
        print(f"  {name}: {d['verdict'] if 'verdict' in d else d.get('delegated_to', '')}{extra}")
    print("\n[스윕 고원 선택]")
    for k in ("rrf_k", "cand_k", "rerank_n", "min_results"):
        s = report["sweeps"][k]
        print(f"  {k}: {s['plateau_choice']} (기본 {s['default']}, 변경={s['changed']})")
    print("\n[소실 퍼널 — recall]")
    for cause, n in report["loss_funnel"]["recall_causes"].items():
        print(f"  {cause}: {n}")
    print("[precision 침입]")
    for cause, n in report["loss_funnel"]["precision_causes"].items():
        print(f"  {cause}: {n}")
    print(f"\n파서 불일치: {report['parser_check_summary']['n_mismatch']}건 "
          f"{report['parser_check_summary']['mismatched']}")
    print(f"리포트: {REPORT_PATH}")


def main():
    pool = json.loads(POOL_PATH.read_text(encoding="utf-8"))
    gates = check_gates(pool)
    print("게이트:")
    for g in gates:
        print(f"  {g['gate']}: {g['name']} — {'PASS' if g['passed'] else 'FAIL'}"
              + (f" {g.get('detail', '')}" if not g["passed"] else ""))
    hard_fail = [g for g in gates if not g["passed"] and not g.get("soft")]
    if hard_fail and "--force" not in sys.argv:
        print("하드 게이트 실패 — --force로 강행 가능(리포트에 배너)")
        sys.exit(1)
    report = measure()
    if hard_fail:
        report["gate_failed"] = [g["name"] for g in hard_fail]
    soft_fail = [g for g in gates if not g["passed"] and g.get("soft")]
    if soft_fail:
        report["difficulty_axis_conclusive"] = False
    report["gates"] = gates
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    _print_summary(report)


if __name__ == "__main__":
    main()
