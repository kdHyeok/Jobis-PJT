"""작업 3 — 질의 텍스트 구성 A/B. 사전 등록: eval/PREREG_query_text.md

측정 대상은 `QuerySpec.dense_text` 하나다. BM25 질의(`spec.text`)는 모든 변형에서
동일하게 고정하고, 의미 축(dense + 크로스인코더)이 보는 질의만 바꾼다.

핵심 설계 — **합동 풀(union pool)을 한 번만 판정한다**
------------------------------------------------------
변형마다 따로 판정하면 판정 대상 구성이 달라져 "변형 효과"와 "판정 구성 효과"가
분리되지 않는다. 4변형 × 5 arm × depth 10의 합집합을 만들어 한 번 판정하고, 각
변형을 그 **공유 qrels**로 채점한다 (TREC 풀링). 부수 효과로 판정 비용도 1/4이 된다.

`random` arm은 질의 텍스트와 무관하므로 변형별로 다시 뽑지 않고 1회만 뽑아 공유한다.
반대로 `bm25`는 변형별로 **실제 코드 경로를 그대로 다시 돌린다** — 모든 변형에서
같은 값이 나오는지가 사전등록 G1(배선 정합성) 검사이기 때문이다. 여기서 한 번만
계산해 재사용하면 그 검사가 무의미해진다.

실행: python -X utf8 -m eval.query_text_ab --pool | --judge | --measure | --all
"""
from __future__ import annotations

import json
import random
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from jobrag import query_text
from jobrag.embedding import embed_texts
from jobrag.query_parser import QuerySpec

from . import core, judge
from .spec_queries_ext import all_queries

EVAL_DIR = Path(__file__).parent
POOL_PATH = EVAL_DIR / "pool_qtext.json"
JUDGMENTS_PATH = EVAL_DIR / "judgments_qtext.json"
REPORT_PATH = EVAL_DIR / "report_query_text_ab.json"

POOL_DEPTH = 10
ARMS = ["random", "bm25", "dense", "rrf", "rrf_ce"]
TEXT_ARMS = ["bm25", "dense", "rrf", "rrf_ce"]     # 질의 텍스트에 의존하는 arm

PRIMARY_ARM = "dense"          # 사전등록 §3 주 종점
BASELINE = "V0"
N_COMPARISONS = 3              # V1·V2·V3 vs V0 -> Bonferroni
ALPHA_ADJ = 0.05 / N_COMPARISONS
G_TOL = -0.02                  # G2·G3 무퇴행 허용 하한
BM25_TOL = 1e-9                # G1 배선 정합성 허용오차


# ── 변형 정의 ──────────────────────────────────────────
# 변형 함수는 jobrag/query_text.py가 갖는다 — 서비스 코드와 **같은 함수**를 재는 것이
# 이 A/B의 요점이다. 여기서 따로 구현하면 A/B에서 이긴 구성과 배포되는 구성이 갈린다.
VARIANTS = {v: {"desc": d} for v, (_, d) in query_text.VARIANTS.items()}


def _spec(q: dict, variant: str) -> QuerySpec:
    """BM25용 text는 전 변형 고정. dense_text만 변형별로 달라진다."""
    role, tech = q["role"], list(q["tech"])
    return QuerySpec(text=query_text.lexical_text(role, tech),
                     dense_text=query_text.semantic_text(role, tech, q["exp_years"],
                                                         variant=variant),
                     tech=tech, regions=[],
                     exp_years=q["exp_years"], role_category=q["category"])


def _display(q: dict) -> str:
    exp = "신입" if q["exp_years"] is None else f"경력 {q['exp_years']}년"
    return f"{q['role']} {' '.join(q['tech'])} ({exp})"


# ── 풀 구성 ────────────────────────────────────────────

def build_pool(conn) -> dict:
    from .run import (_run_arm_bm25, _run_arm_dense, _run_arm_random,
                      _run_arm_rrf, _run_arm_rrf_ce)

    queries = all_queries()
    pool, arm_tops = {}, {}
    for i, q in enumerate(queries, 1):
        qid, disp = q["id"], _display(q)
        print(f"[{i}/{len(queries)}] {qid} — {disp}", flush=True)

        # 질의 무관 arm — 1회만 뽑아 전 변형이 공유한다
        rnd = _run_arm_random(conn, POOL_DEPTH)
        per_variant: dict[str, dict[str, list[str]]] = {}
        for v in VARIANTS:
            spec = _spec(q, v)
            [vec], _ = embed_texts([spec.semantic_text])
            per_variant[v] = {
                "bm25": _run_arm_bm25(conn, spec, POOL_DEPTH),
                "dense": _run_arm_dense(conn, vec, spec, POOL_DEPTH),
                "rrf": _run_arm_rrf(conn, spec, POOL_DEPTH),
                "rrf_ce": _run_arm_rrf_ce(conn, spec, POOL_DEPTH),
                "random": rnd,
            }
        uids = sorted({u for arms in per_variant.values()
                       for lst in arms.values() for u in lst})
        pool[qid] = {"query": disp, "category": q["category"],
                     "spec": {"role": q["role"], "tech": q["tech"],
                              "exp_years": q["exp_years"]},
                     "uids": uids, "n_pool": len(uids)}
        arm_tops[qid] = per_variant
        dt = {v: _spec(q, v).semantic_text for v in VARIANTS}
        print(f"    합동 풀 {len(uids)}건 · V1={dt['V1']!r}", flush=True)

    data = {"generated_at": datetime.now(timezone.utc).isoformat(),
            "prereg": "eval/PREREG_query_text.md",
            "corpus_snapshot": core.snapshot_hash(conn),
            "pool_depth": POOL_DEPTH, "n_queries": len(pool),
            "variants": {v: VARIANTS[v]["desc"] for v in VARIANTS},
            "pool": pool, "arm_tops_by_variant": arm_tops, "arms": ARMS}
    POOL_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(p["n_pool"] for p in pool.values())
    print(f"\n합동 풀 저장: {POOL_PATH.name} — 판정 예정 {total}쌍 "
          f"(변형별 개별 판정 대비 약 1/{len(VARIANTS)})")
    return data


# ── 판정 (합동 풀 1회) ─────────────────────────────────

def judge_pool(conn) -> None:
    judge.JUDGMENTS_PATH = JUDGMENTS_PATH
    data = json.loads(POOL_PATH.read_text(encoding="utf-8"))
    print(f"=== 합동 풀 판정 (prompt {judge.PROMPT_VERSION}) ===")
    judge.judge_all(conn, data["pool"])


# ── 측정 ───────────────────────────────────────────────

def _score_variant(pool: dict, arm_tops: dict, qrels_all: dict,
                   variant: str, norm: dict) -> dict:
    """변형 하나를 공유 qrels로 채점. norm에는 질의별 (floor, oracle)을 캐시한다."""
    per_query, series = {}, {a: [] for a in ARMS}
    for qid, info in pool.items():
        qrels = qrels_all.get(qid) or {}
        if not qrels:
            continue
        tops = arm_tops[qid][variant]
        floor, oracle = norm[qid]
        scores = {}
        for a in ARMS:
            ranked = tops.get(a, [])
            nd = core.ndcg_at_k(ranked, qrels, 3)
            scores[a] = {"ndcg3": round(nd, 4),
                         "p3": round(core.precision_at_k(ranked, qrels, 3), 4),
                         "norm_ndcg3": round(core.normalized_score(nd, floor, oracle), 4)}
            series[a].append(scores[a]["norm_ndcg3"])
        per_query[qid] = {"query": info["query"], "category": info["category"],
                          "n_judged": len(qrels), "arms": scores}
    macro = {a: {m: round(sum(per_query[q]["arms"][a][m] for q in per_query) / len(per_query), 4)
                 for m in ("ndcg3", "p3", "norm_ndcg3")} for a in ARMS}
    return {"macro_average": macro, "series_norm_ndcg3": series, "per_query": per_query,
            "n_queries": len(per_query)}


def measure() -> dict:
    random.seed(20260729)          # 정규화 분모 재현성 (run_spec과 동일 정책)
    pool_data = json.loads(POOL_PATH.read_text(encoding="utf-8"))
    pool, arm_tops = pool_data["pool"], pool_data["arm_tops_by_variant"]
    jd = json.loads(JUDGMENTS_PATH.read_text(encoding="utf-8"))
    qrels_all = {q: v["labels"] for q, v in jd.get("queries", {}).items()}

    # 질의별 랜덤 바닥·오라클은 qrels만의 함수 — 변형 간 공유해야 분모가 같아진다
    norm = {}
    for qid in pool:
        qr = qrels_all.get(qid) or {}
        if not qr:
            continue
        floor = core.random_baseline_ndcg(qr, 3, n_trials=5000)
        ideal = sorted(qr, key=lambda u: core.GRADE.get(qr[u], 0), reverse=True)
        norm[qid] = (floor, core.ndcg_at_k(ideal, qr, 3))

    scored = {v: _score_variant(pool, arm_tops, qrels_all, v, norm) for v in VARIANTS}
    base = scored[BASELINE]

    # ── 사전등록 기준 판정 ──
    verdicts = {}
    for v in VARIANTS:
        if v == BASELINE:
            continue
        s = scored[v]
        primary = core.paired_bootstrap(base["series_norm_ndcg3"][PRIMARY_ARM],
                                        s["series_norm_ndcg3"][PRIMARY_ARM],
                                        alpha=ALPHA_ADJ)
        primary_95 = core.paired_bootstrap(base["series_norm_ndcg3"][PRIMARY_ARM],
                                           s["series_norm_ndcg3"][PRIMARY_ARM])
        # G1: bm25는 어휘 축이므로 전 변형 동일해야 한다 (배선 누출 검사)
        d_bm25 = abs(s["macro_average"]["bm25"]["norm_ndcg3"]
                     - base["macro_average"]["bm25"]["norm_ndcg3"])
        guards = {}
        for arm, name in (("rrf_ce", "G2"), ("rrf", "G3")):
            g = core.paired_bootstrap(base["series_norm_ndcg3"][arm],
                                      s["series_norm_ndcg3"][arm])
            guards[name] = {"arm": arm, "delta": g["mean_delta"], "ci_95": g["ci_95"],
                            "pass": g["ci_95"][0] >= G_TOL}
        checks = {
            "P1_primary": {"arm": PRIMARY_ARM, "delta": primary["mean_delta"],
                           "ci_bonferroni": primary["ci_95"],
                           "conf_level": primary["conf_level"],
                           "ci_95_unadjusted": primary_95["ci_95"],
                           "pass": primary["ci_95"][0] > 0},
            "G1_bm25_identity": {"abs_diff": round(d_bm25, 12),
                                 "pass": d_bm25 <= BM25_TOL},
            **guards,
        }
        verdicts[v] = {"desc": VARIANTS[v]["desc"], "checks": checks,
                       "adopt": all(c["pass"] for c in checks.values())}

    passed = [v for v, r in verdicts.items() if r["adopt"]]
    winner = max(passed, key=lambda v: scored[v]["macro_average"]["rrf_ce"]["norm_ndcg3"],
                 default=None)

    out = {"generated_at": datetime.now(timezone.utc).isoformat(),
           "prereg": "eval/PREREG_query_text.md",
           "judge_prompt": judge.PROMPT_VERSION,
           "corpus_snapshot": pool_data.get("corpus_snapshot"),
           "n_queries": base["n_queries"], "pool_depth": POOL_DEPTH,
           "primary_endpoint": f"{PRIMARY_ARM} 정규화 nDCG@3",
           "multiplicity": {"n_comparisons": N_COMPARISONS, "alpha_adjusted": ALPHA_ADJ,
                            "method": "Bonferroni"},
           "variants": {v: {"desc": VARIANTS[v]["desc"],
                            "macro_average": scored[v]["macro_average"],
                            "per_query": scored[v]["per_query"]} for v in VARIANTS},
           "verdicts": verdicts,
           "winner": winner,
           "decision": ("채택: " + winner if winner else
                        "채택 없음 — 현행 V0 유지 (사전등록 §4 '통과가 없을 경우')"),
           "caveat": ("qrels 전량 LLM 판정. 판정자는 사람 118쌍 대비 κ=0.5921. "
                      "같은 합동 풀·같은 판정자 내부의 상대 비교이므로 변형 간 차이에는 "
                      "판정자 편향이 1차적으로 상쇄되지만, 절대 수준에는 상쇄되지 않는다.")}
    REPORT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── 출력 ──
    print(f"\n질의 {base['n_queries']}종 · 합동 풀 · 판정 {judge.PROMPT_VERSION}\n")
    hdr = f"{'변형':6} {'bm25':>8} {'dense':>8} {'rrf':>8} {'rrf_ce':>8}   설명"
    print(hdr); print("-" * len(hdr) * 1)
    for v in VARIANTS:
        m = scored[v]["macro_average"]
        print(f"{v:6} {m['bm25']['norm_ndcg3']:>8.4f} {m['dense']['norm_ndcg3']:>8.4f} "
              f"{m['rrf']['norm_ndcg3']:>8.4f} {m['rrf_ce']['norm_ndcg3']:>8.4f}   "
              f"{VARIANTS[v]['desc']}")
    print(f"\n사전등록 기준 판정 (주 종점 {PRIMARY_ARM}, Bonferroni "
          f"{100 * (1 - ALPHA_ADJ):.2f}% CI):")
    for v, r in verdicts.items():
        c = r["checks"]
        p1 = c["P1_primary"]
        print(f"  {v}: {'채택' if r['adopt'] else '기각'}"
              f" | P1 Δ={p1['delta']:+.4f} CI{p1['ci_bonferroni']} {'OK' if p1['pass'] else 'X'}"
              f" | G1 {'OK' if c['G1_bm25_identity']['pass'] else 'X'}"
              f" | G2 Δ={c['G2']['delta']:+.4f} {'OK' if c['G2']['pass'] else 'X'}"
              f" | G3 Δ={c['G3']['delta']:+.4f} {'OK' if c['G3']['pass'] else 'X'}")
    print(f"\n=> {out['decision']}")
    print(f"리포트: {REPORT_PATH}")
    return out


# ── 확인 측정 (입력 B 실입력 경로) ─────────────────────

CONFIRM_POOL = EVAL_DIR / "pool_qtext_confirm.json"
CONFIRM_JUDGMENTS = EVAL_DIR / "judgments_qtext_confirm.json"
CONFIRM_REPORT = EVAL_DIR / "report_query_text_confirm.json"


def _confirm_specs(variant: str):
    """골든 profile 36건을 **실제 진입점**(_spec_from_profile)으로 통과시킨다.

    주 측정(정규화 60종)은 질의 dict에서 직접 QuerySpec을 조립하므로 매핑 단계를
    우회한다. 확인 측정은 명세서가 규정한 입력 B 경로를 그대로 태워, 채택 변형이
    실제 서비스 경로에서도 같은 방향으로 작동하는지 본다.
    """
    from jobrag import query_text as qt
    from jobrag.spec_adapter import _spec_from_profile
    from .golden_profiles import GOLDEN_PROFILES, profile_payload

    prev, qt.ACTIVE = qt.ACTIVE, variant
    try:
        out = []
        for p in GOLDEN_PROFILES:
            m = p["_meta"]
            spec, _ = _spec_from_profile(profile_payload(p))
            out.append((m["id"], f"{m['role']} (profile, 연차 {m['target_exp_years']})",
                        m["category"], spec))
        return out
    finally:
        qt.ACTIVE = prev


def confirm_pool(conn, variant: str) -> None:
    from .run import (_run_arm_bm25, _run_arm_dense, _run_arm_random,
                      _run_arm_rrf, _run_arm_rrf_ce)

    variants = [BASELINE, variant]
    items = {v: _confirm_specs(v) for v in variants}
    pool, arm_tops = {}, {}
    n = len(items[BASELINE])
    for i in range(n):
        qid, disp, cat, _ = items[BASELINE][i]
        print(f"[{i + 1}/{n}] {qid} — {disp}", flush=True)
        rnd = _run_arm_random(conn, POOL_DEPTH)
        per_variant = {}
        for v in variants:
            spec = items[v][i][3]
            [vec], _ = embed_texts([spec.semantic_text])
            per_variant[v] = {
                "bm25": _run_arm_bm25(conn, spec, POOL_DEPTH),
                "dense": _run_arm_dense(conn, vec, spec, POOL_DEPTH),
                "rrf": _run_arm_rrf(conn, spec, POOL_DEPTH),
                "rrf_ce": _run_arm_rrf_ce(conn, spec, POOL_DEPTH),
                "random": rnd,
            }
        uids = sorted({u for a in per_variant.values() for lst in a.values() for u in lst})
        pool[qid] = {"query": disp, "category": cat, "uids": uids, "n_pool": len(uids)}
        arm_tops[qid] = per_variant
        print(f"    합동 풀 {len(uids)}건", flush=True)

    CONFIRM_POOL.write_text(json.dumps(
        {"generated_at": datetime.now(timezone.utc).isoformat(),
         "track": "입력 B — profile JSON (명세서 §2), 합성 골든 36건",
         "entry_point": "jobrag.spec_adapter._spec_from_profile",
         "corpus_snapshot": core.snapshot_hash(conn),
         "variants": variants, "pool_depth": POOL_DEPTH,
         "pool": pool, "arm_tops_by_variant": arm_tops, "arms": ARMS},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n확인 풀 저장: {CONFIRM_POOL.name} "
          f"(판정 예정 {sum(p['n_pool'] for p in pool.values())}쌍)")


def confirm_judge(conn) -> None:
    judge.JUDGMENTS_PATH = CONFIRM_JUDGMENTS
    data = json.loads(CONFIRM_POOL.read_text(encoding="utf-8"))
    judge.judge_all(conn, data["pool"])


def confirm_measure() -> dict:
    random.seed(20260729)
    data = json.loads(CONFIRM_POOL.read_text(encoding="utf-8"))
    pool, arm_tops, variants = data["pool"], data["arm_tops_by_variant"], data["variants"]
    jd = json.loads(CONFIRM_JUDGMENTS.read_text(encoding="utf-8"))
    qrels_all = {q: v["labels"] for q, v in jd.get("queries", {}).items()}

    norm = {}
    for qid in pool:
        qr = qrels_all.get(qid) or {}
        if not qr:
            continue
        ideal = sorted(qr, key=lambda u: core.GRADE.get(qr[u], 0), reverse=True)
        norm[qid] = (core.random_baseline_ndcg(qr, 3, n_trials=5000),
                     core.ndcg_at_k(ideal, qr, 3))

    scored = {v: _score_variant(pool, arm_tops, qrels_all, v, norm) for v in variants}
    cand = [v for v in variants if v != BASELINE][0]
    base = scored[BASELINE]
    deltas = {}
    for arm in TEXT_ARMS:
        deltas[arm] = core.paired_bootstrap(base["series_norm_ndcg3"][arm],
                                            scored[cand]["series_norm_ndcg3"][arm])
    direction_ok = deltas[PRIMARY_ARM]["mean_delta"] > 0

    out = {"generated_at": datetime.now(timezone.utc).isoformat(),
           "prereg": "eval/PREREG_query_text.md §4 확인 측정",
           "track": data["track"], "entry_point": data["entry_point"],
           "corpus_snapshot": data.get("corpus_snapshot"),
           "n_queries": base["n_queries"], "candidate": cand,
           "macro_average": {v: scored[v]["macro_average"] for v in variants},
           "deltas_vs_V0": deltas,
           "requirement": f"{PRIMARY_ARM} 점추정치 > 0 (유의성 불요)",
           "direction_pass": direction_ok,
           "verdict": ("확인 통과 — 실입력 경로에서도 같은 방향" if direction_ok else
                       "확인 실패 — 방향 불일치. 채택 보류하고 두 트랙 차이를 먼저 규명"),
           "per_query": {v: scored[v]["per_query"] for v in variants}}
    CONFIRM_REPORT.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print(f"\n입력 B 확인 측정 (골든 profile {base['n_queries']}건, 실입력 경로)")
    print(f"{'arm':8} {'V0':>9} {cand:>9} {'Δ':>9}   95% CI")
    for arm in TEXT_ARMS:
        print(f"{arm:8} {base['macro_average'][arm]['norm_ndcg3']:>9.4f} "
              f"{scored[cand]['macro_average'][arm]['norm_ndcg3']:>9.4f} "
              f"{deltas[arm]['mean_delta']:>+9.4f}   {deltas[arm]['ci_95']}")
    print(f"\n=> {out['verdict']}")
    return out


# ── 승격 (합동 풀 -> 본평가 자산) ──────────────────────

def promote(variant: str | None = None) -> None:
    """채택 변형의 arm_tops를 pool_spec.json으로, 합동 판정을 judgments_spec.json으로 승격.

    합동 풀은 이미 4변형 × 5 arm의 합집합을 전량 판정했으므로, 본평가용 풀을
    따로 다시 만들고 다시 판정할 이유가 없다 — 채택 변형의 순위만 뽑아 쓰면 된다.
    기존 자산은 덮기 전에 _archive/corpus1172/로 옮긴다(코퍼스가 달라 재현 불가).
    """
    import shutil

    rep = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    variant = variant or rep.get("winner") or BASELINE
    pool_data = json.loads(POOL_PATH.read_text(encoding="utf-8"))

    arch = EVAL_DIR / "_archive" / "corpus1172"
    arch.mkdir(parents=True, exist_ok=True)
    for name in ("pool_spec.json", "judgments_spec.json", "report_spec.json"):
        src = EVAL_DIR / name
        if src.exists() and not (arch / name).exists():
            shutil.copy2(src, arch / name)
            print(f"  보존: _archive/corpus1172/{name}")

    out = {"generated_at": datetime.now(timezone.utc).isoformat(),
           "input_contract": "RAG_입출력_명세서.md — 정규화 고정형(직군+기술+연차, 지역 없음)",
           "promoted_from": {"pool": POOL_PATH.name, "variant": variant,
                             "variant_desc": VARIANTS[variant]["desc"],
                             "prereg": "eval/PREREG_query_text.md"},
           "corpus_snapshot": pool_data.get("corpus_snapshot"),
           "n_queries": pool_data["n_queries"],
           "pool": pool_data["pool"],
           "arm_tops": {q: v[variant] for q, v in
                        pool_data["arm_tops_by_variant"].items()},
           "arms": ARMS}
    (EVAL_DIR / "pool_spec.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.copy2(JUDGMENTS_PATH, EVAL_DIR / "judgments_spec.json")
    print(f"승격 완료: 변형 {variant} -> pool_spec.json / judgments_spec.json "
          f"({out['n_queries']}질의)")


def main():
    args = sys.argv[1:]
    v_arg = next((a.split("=", 1)[1] for a in args if a.startswith("--variant=")), None)
    conn = None
    if any(a in args for a in ("--pool", "--judge", "--all",
                               "--confirm-pool", "--confirm-judge")):
        from jobrag.store import connect
        conn = connect()
    try:
        if "--pool" in args or "--all" in args:
            build_pool(conn)
        if "--judge" in args or "--all" in args:
            judge_pool(conn)
        if "--measure" in args or "--all" in args:
            measure()
        # 채택 변형이 없으면 확인 측정은 성립하지 않는다(V0 vs V0). 조용히 건너뛴다 —
        # 오케스트레이터가 실패로 보고 멈추면 뒤 단계가 전부 막힌다.
        winner = v_arg or json.loads(REPORT_PATH.read_text(encoding="utf-8")).get("winner") \
            if REPORT_PATH.exists() else v_arg
        skip_confirm = not winner or winner == BASELINE
        if any(a.startswith("--confirm") for a in args) and skip_confirm:
            print("채택 변형 없음 — 확인 측정 건너뜀 (사전등록 §4: 현행 V0 유지)")
        else:
            if "--confirm-pool" in args:
                confirm_pool(conn, winner)
            if "--confirm-judge" in args:
                confirm_judge(conn)
            if "--confirm-measure" in args:
                confirm_measure()
        if "--promote" in args:
            promote(v_arg)
        if not args:
            print(__doc__)
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    main()
