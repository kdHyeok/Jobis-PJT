"""명세서 실입력 경로 평가 — 입력 A(직업명) / 입력 B(profile JSON) 트랙.

왜 필요한가: 기존 15종 트랙(`spec_anchor.SPEC_QUERIES`)은 "직군+기술+연차"를 이미 합쳐놓은
문자열이고, 이는 `spec_adapter`가 입력 B로부터 **내부적으로 만들어내는 QuerySpec**을 흉내낸
것이다. 명세서가 규정한 실제 진입점은 (A) 직업명 문자열, (B) profile JSON 두 개뿐이다.
따라서 15종 트랙 수치는 매핑 단계를 우회한 **상한**이며, 실입력 기준 수치가 아니다.

세 트랙을 같은 깊이(depth 10)·같은 arm·같은 판정 프롬프트로 재서 비교한다:

  A: parse_query(직업명)          — 기술 [] , 연차 None. 신호가 가장 빈약
  B: _spec_from_profile(profile)  — skills/techStack -> 기술, period 합산 -> 연차
  기존 15종: 합성 중간형          — 상한선

이러면 "성능 손실이 검색에서 오는지 입력 매핑에서 오는지"가 분리된다.

실행: python -X utf8 -m eval.io_tracks --pool | --judge | --measure | --all
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from jobrag.embedding import embed_texts
from jobrag.query_parser import load_region_vocab, parse_query
from jobrag.spec_adapter import _spec_from_profile
from jobrag.store import connect

from . import core, judge
from .golden_profiles import GOLDEN_PROFILES, INPUT_A_QUERIES, SYNTHETIC_NOTE, profile_payload

EVAL_DIR = Path(__file__).parent
POOL_DEPTH = 10          # 기존 15종 트랙과 동일 — 3자 비교의 전제
ARMS = ["random", "bm25", "dense", "rrf", "rrf_ce"]

TRACKS = {
    "inputA": {"pool": EVAL_DIR / "pool_inputA.json",
               "judgments": EVAL_DIR / "judgments_inputA.json",
               "desc": "입력 A — 직업명 문자열 (명세서 §2 입력 A)"},
    "inputB": {"pool": EVAL_DIR / "pool_inputB.json",
               "judgments": EVAL_DIR / "judgments_inputB.json",
               "desc": "입력 B — profile JSON (명세서 §2 입력 B, 합성 골든 12건)"},
}
REPORT_PATH = EVAL_DIR / "report_io_tracks.json"


# ── 풀 구성 ────────────────────────────────────────────

def _specs(conn):
    """트랙별 (qid, 표시질의, category, QuerySpec) 목록. 실제 진입점 코드를 그대로 쓴다."""
    rv = load_region_vocab(conn)
    a = [(q["id"], q["query"], q["category"], parse_query(q["query"], rv))
         for q in INPUT_A_QUERIES]
    b = []
    for p in GOLDEN_PROFILES:
        m = p["_meta"]
        spec, _ = _spec_from_profile(profile_payload(p))
        b.append((m["id"], f"{m['role']} (profile, 연차 {m['target_exp_years']})",
                  m["category"], spec))
    return {"inputA": a, "inputB": b}


def build_pools(conn) -> None:
    from .run import (_run_arm_bm25, _run_arm_dense, _run_arm_random,
                      _run_arm_rrf, _run_arm_rrf_ce)

    for track, items in _specs(conn).items():
        pool, arm_tops = {}, {}
        for i, (qid, disp, cat, spec) in enumerate(items, 1):
            print(f"[{track} {i}/{len(items)}] {qid} — {disp}")
            [vec], _ = embed_texts([spec.semantic_text])
            arms = {
                "bm25": _run_arm_bm25(conn, spec, POOL_DEPTH),
                "dense": _run_arm_dense(conn, vec, spec, POOL_DEPTH),
                "rrf": _run_arm_rrf(conn, spec, POOL_DEPTH),
                "rrf_ce": _run_arm_rrf_ce(conn, spec, POOL_DEPTH),
                "random": _run_arm_random(conn, POOL_DEPTH),
            }
            uids = sorted({u for v in arms.values() for u in v})
            pool[qid] = {"query": disp, "category": cat,
                         "spec": {"text": spec.text, "tech": spec.tech,
                                  "exp_years": spec.exp_years,
                                  "role_category": spec.role_category},
                         "uids": uids, "n_pool": len(uids)}
            arm_tops[qid] = arms
            print(f"    기술 {len(spec.tech)}개 · 연차 {spec.exp_years} · 풀 {len(uids)}건")

        data = {"generated_at": datetime.now(timezone.utc).isoformat(),
                "track": TRACKS[track]["desc"],
                "entry_point": ("jobrag.query_parser.parse_query" if track == "inputA"
                                else "jobrag.spec_adapter._spec_from_profile"),
                "synthetic_note": SYNTHETIC_NOTE if track == "inputB" else None,
                "pool_depth": POOL_DEPTH, "n_queries": len(pool),
                "pool": pool, "arm_tops": arm_tops, "arms": ARMS}
        TRACKS[track]["pool"].write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
        total = sum(p["n_pool"] for p in pool.values())
        print(f"  -> {TRACKS[track]['pool'].name} (판정 예정 {total}쌍)\n")


# ── 판정 ───────────────────────────────────────────────

def judge_pools(conn) -> None:
    for track, cfg in TRACKS.items():
        if not cfg["pool"].exists():
            print(f"{cfg['pool'].name} 없음 — --pool 먼저")
            continue
        judge.JUDGMENTS_PATH = cfg["judgments"]      # 트랙별 분리 저장
        data = json.loads(cfg["pool"].read_text(encoding="utf-8"))
        print(f"=== {track} 판정 (prompt {judge.PROMPT_VERSION}) ===")
        judge.judge_all(conn, data["pool"])


# ── 측정 ───────────────────────────────────────────────

def _measure_track(pool_data: dict, qrels_all: dict) -> dict:
    pool, arm_tops = pool_data["pool"], pool_data["arm_tops"]
    per_query, series = {}, {a: [] for a in ARMS}
    for qid, info in pool.items():
        qrels = qrels_all.get(qid, {})
        if not qrels:
            continue
        tops = arm_tops.get(qid, {})
        scores = {}
        for a in ARMS:
            ranked = tops.get(a, [])
            scores[a] = {"ndcg3": round(core.ndcg_at_k(ranked, qrels, 3), 4),
                         "p3": round(core.precision_at_k(ranked, qrels, 3), 4),
                         "ap3": round(core.ap_at_k(ranked, qrels, 3), 4)}
        floor = core.random_baseline_ndcg(qrels, 3, n_trials=5000)
        oracle_uids = sorted(qrels, key=lambda u: core.GRADE.get(qrels[u], 0), reverse=True)
        oracle = core.ndcg_at_k(oracle_uids, qrels, 3)
        for a in ARMS:
            scores[a]["norm_ndcg3"] = round(
                core.normalized_score(scores[a]["ndcg3"], floor, oracle), 4)
            series[a].append(scores[a]["norm_ndcg3"])
        per_query[qid] = {"query": info["query"], "category": info["category"],
                          "spec": info["spec"], "n_judged": len(qrels),
                          "n_relevant": sum(1 for v in qrels.values()
                                            if core.GRADE.get(v, 0) >= 2),
                          "label_dist": dict(Counter(qrels.values()).most_common()),
                          "arms": scores}
    macro = {a: {m: round(sum(per_query[q]["arms"][a][m] for q in per_query) / len(per_query), 4)
                 for m in ("ndcg3", "p3", "ap3", "norm_ndcg3")} for a in ARMS}
    ndcg = {a: [per_query[q]["arms"][a]["ndcg3"] for q in per_query] for a in ARMS}
    comps = {}
    for i, x in enumerate(ARMS):
        for y in ARMS[i + 1:]:
            comps[f"{x}_vs_{y}"] = core.paired_bootstrap(ndcg[x], ndcg[y])
    return {"n_queries": len(per_query), "macro_average": macro,
            "comparisons": comps, "per_query": per_query,
            "best_arm": max(ARMS, key=lambda a: macro[a]["norm_ndcg3"])}


def measure() -> dict:
    import random
    random.seed(20260729)          # 정규화 분모 재현성 (run_spec과 동일 정책)
    out = {"generated_at": datetime.now(timezone.utc).isoformat(),
           "judge_prompt": judge.PROMPT_VERSION,
           "pool_depth": POOL_DEPTH,
           "note": "명세서 실입력 경로 기준. 15종 트랙은 매핑을 우회한 상한선이므로 참고용 병기",
           "tracks": {}}
    for track, cfg in TRACKS.items():
        if not (cfg["pool"].exists() and cfg["judgments"].exists()):
            continue
        pool_data = json.loads(cfg["pool"].read_text(encoding="utf-8"))
        jd = json.loads(cfg["judgments"].read_text(encoding="utf-8"))
        qrels = {q: v["labels"] for q, v in jd.get("queries", {}).items()}
        res = _measure_track(pool_data, qrels)
        res["desc"] = cfg["desc"]
        res["entry_point"] = pool_data.get("entry_point")
        out["tracks"][track] = res

    # 상한선: 정규화 트랙 (사람 반영 qrels). 질의 수는 리포트에서 읽어온다 —
    # 15종에서 60종으로 확장됐으므로 하드코딩하면 리포트가 거짓말을 한다.
    spec_rep = EVAL_DIR / "report_spec.json"
    if spec_rep.exists():
        s = json.loads(spec_rep.read_text(encoding="utf-8"))
        nq = s.get("version", {}).get("n_queries")
        out["upper_bound_normalized"] = {
            "desc": (f"합성 중간형 {nq}종 (직군+기술+연차 문자열) — 매핑 우회, 상한선"),
            "n_queries": nq,
            "caveat": ("질의 집합이 다르므로(이 트랙 골든 profile vs 정규화 질의) "
                       "질의별 쌍대 비교가 아니라 거시평균 대조로만 읽어야 한다"),
            "macro_average": s["qrels_human_patched"]["macro_average"],
        }
    REPORT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'트랙':34} {'best':8} {'norm nDCG@3':>12} {'P@3':>8} {'유의비교':>8}")
    for t, r in out["tracks"].items():
        nsig = sum(1 for v in r["comparisons"].values() if v["significant"])
        print(f"{t + ' — ' + r['desc'][:26]:34} {r['best_arm']:8} "
              f"{r['macro_average'][r['best_arm']]['norm_ndcg3']:>12.4f} "
              f"{r['macro_average'][r['best_arm']]['p3']:>8.4f} "
              f"{nsig:>6}/{len(r['comparisons'])}")
    if "upper_bound_normalized" in out:
        ub = out["upper_bound_normalized"]["macro_average"]
        nq = out["upper_bound_normalized"]["n_queries"]
        best = max(ARMS, key=lambda a: ub[a]["norm_ndcg3"])
        print(f"{f'(상한) {nq}종 합성 중간형':34} {best:8} {ub[best]['norm_ndcg3']:>12.4f} "
              f"{ub[best]['p3']:>8.4f} {'—':>8}")
    print(f"\n리포트: {REPORT_PATH}")
    return out


def main():
    args = sys.argv[1:]
    need_db = any(a in args for a in ("--pool", "--judge", "--all"))
    conn = connect() if need_db else None
    try:
        if "--pool" in args or "--all" in args:
            build_pools(conn)
        if "--judge" in args or "--all" in args:
            judge_pools(conn)
        if "--measure" in args or "--all" in args:
            measure()
        if not args:
            print(__doc__)
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    main()
