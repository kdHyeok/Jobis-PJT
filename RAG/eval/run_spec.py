"""정규화 질의 트랙 본평가 — 사람 검증된 라벨 기준 (HANDOFF §3-C).

기존 report.json은 **자연어 30질의** 트랙이고, 사람 채점은 **정규화 15질의** 트랙에서
이뤄졌다(PLAN_v5 §6.5 경고: 두 트랙의 κ는 서로 대입 불가). 사람 검증이 붙은 수치를
내려면 정규화 트랙에서 지표를 계산해야 한다 — 이 모듈이 그것이다.

두 가지 qrels로 각각 측정해 라벨 민감도를 본다:
  judge      — judgments_spec.json 전량 (439쌍, gemini-lite v3)
  human_patch— 위와 같으나 사람이 라벨한 118쌍은 사람 라벨로 덮어씀

arm 순위가 두 qrels에서 같으면 그 순위 결론은 '라벨 강건'하다. 절대 수치는 달라질 수 있다.

지표·부트스트랩은 core.py를 그대로 쓴다(자연어 트랙과 동일 정의여야 비교 가능).
편향 보정(bias_correction)은 자연어 트랙의 전수 라벨 3건에서 나온 값이므로 여기선 N/A.

실행: python -X utf8 -m eval.run_spec
"""
from __future__ import annotations

import csv
import json
import random
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import core, judge

EVAL_DIR = Path(__file__).parent
POOL_SPEC_PATH = EVAL_DIR / "pool_spec.json"
JUDGMENTS_SPEC_PATH = EVAL_DIR / "judgments_spec.json"
ANCHOR_DIR = EVAL_DIR / "anchor"
REPORT_PATH = EVAL_DIR / "report_spec.json"

ARMS = ["random", "bm25", "dense", "rrf", "rrf_ce"]
CANON = {"correct": "Correct", "ambiguous": "Ambiguous", "incorrect": "Incorrect"}

# 직군 12종을 성격이 비슷한 축으로 묶는다 — 질의당 n이 1~3이라 개별 직군은 잡음이 크다
ROLE_AXES = {
    "서버·백엔드": ["backend"],
    "클라이언트": ["frontend", "fullstack", "mobile"],
    "인프라·운영": ["devops", "sre"],
    "데이터·ML": ["data_engineer", "data_scientist", "ml_engineer", "data_analyst"],
    "품질·보안": ["qa", "security"],
}


def _human_labels() -> dict[str, str]:
    out = {}
    for name in ("session_easy.csv", "session_ambiguous.csv"):
        path = ANCHOR_DIR / name
        if not path.exists():
            continue
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                lab = CANON.get((row.get("label") or "").strip().lower())
                if lab:
                    out[f"{row['qid']}:{row['uid']}"] = lab
    return out


def _ndcg_k_grade(ranked: list[str], qrels: dict[str, str], k: int,
                  grade: dict[str, int]) -> float:
    """등급 배점을 바꿔 계산하는 nDCG@k — core.GRADE를 전역 변경하지 않기 위해 분리."""
    gains = [grade.get(qrels.get(u, "Incorrect"), 0) for u in ranked[:k]]
    ideal = sorted((grade.get(v, 0) for v in qrels.values()), reverse=True)
    idcg = core._dcg(ideal, k)
    return core._dcg(gains, k) / idcg if idcg > 0 else 0.0


def _k_analysis(pool: dict, arm_tops: dict, all_qrels: dict[str, dict[str, str]],
                per_query: dict, macro: dict) -> dict:
    """절단 k=3이라는 조건에서 이 수치를 어디까지 믿을 수 있는지 진단한다.

    k는 제품이 실제로 상위 3건을 생성부 컨텍스트로 넘기므로(ragas_prep.TOP_K=3) 운영
    정합성은 맞다. 문제는 지표의 해상도다 — 아래 셋을 수치로 남긴다.
      1) 천장 포화: 만점 질의가 많으면 개선을 측정할 여지가 없다
      2) Ambiguous 반값: nDCG는 애매 판정에 절반을 주지만 P@3는 주지 않는다
      3) 기준선 이원화: 정규화 분모(풀 내부 무작위)와 random arm(코퍼스 무작위)은 다른 값이다
    """
    scored = [a for a in ARMS if a != "random"]
    BASE = {"Correct": 2, "Ambiguous": 1, "Incorrect": 0}
    STRICT = {"Correct": 2, "Ambiguous": 0, "Incorrect": 0}

    saturation, ambiguous_credit, p3_attain, dists = {}, {}, {}, {}
    for arm in scored:
        vals = sorted(per_query[q]["arms"][arm]["ndcg3"] for q in per_query)
        dists[arm] = vals
        saturation[arm] = {
            "n_at_ceiling": sum(1 for v in vals if v >= 0.999),
            "n_queries": len(vals),
            "ceiling_rate": round(sum(1 for v in vals if v >= 0.999) / len(vals), 4),
            "n_distinct_values": len(set(round(v, 4) for v in vals)),
        }
        base = sum(_ndcg_k_grade(arm_tops[q].get(arm, []), all_qrels[q], 3, BASE)
                   for q in per_query) / len(per_query)
        strict = sum(_ndcg_k_grade(arm_tops[q].get(arm, []), all_qrels[q], 3, STRICT)
                     for q in per_query) / len(per_query)
        ambiguous_credit[arm] = {"base": round(base, 4), "strict": round(strict, 4),
                                 "delta": round(strict - base, 4)}
        hits = sum(per_query[q]["arms"][arm]["p3"] * 3 for q in per_query)
        attainable = sum(min(3, per_query[q]["n_relevant"]) for q in per_query)
        p3_attain[arm] = {"relevant_hits": round(hits, 1), "attainable": attainable,
                          "rate": round(hits / attainable, 4) if attainable else None}

    # ARMS의 나열 순서를 최고 성능 순서로 착각하면 안 된다 — 매크로 점수로 정한다.
    best_arm = max(scored, key=lambda a: macro[a]["norm_ndcg3"])
    zero_rel = [{"qid": q, "query": d["query"],
                 "n_ambiguous": d["label_dist"].get("Ambiguous", 0),
                 "best_arm": best_arm,
                 "ndcg3_of_best_arm": d["arms"][best_arm]["ndcg3"],
                 "p3_of_best_arm": d["arms"][best_arm]["p3"]}
                for q, d in per_query.items() if d["n_relevant"] == 0]
    thin_rel = [{"qid": q, "n_relevant": d["n_relevant"],
                 "p3_ceiling": round(min(3, d["n_relevant"]) / 3, 4)}
                for q, d in per_query.items() if d["n_relevant"] < 3]

    floors = [per_query[q]["random_floor"] for q in per_query]
    grades = {"Correct": 0, "Ambiguous": 0, "Incorrect": 0}
    for q in per_query:
        for lab, n in per_query[q]["label_dist"].items():
            grades[lab] = grades.get(lab, 0) + n

    return {
        "metric_cutoff_k": 3,
        "product_cutoff": "생성부가 상위 3건을 컨텍스트로 사용 (ragas_prep.TOP_K=3) — 지표 k와 일치",
        "verdict": "운영 정합성은 성립. 단 천장 포화·Ambiguous 반값·기준선 이원화로 "
                   "절대 수치는 낙관 편향된다",
        "grade_composition": grades,
        "saturation": saturation,
        "ndcg3_distribution": dists,
        "ambiguous_credit": ambiguous_credit,
        "p3_vs_attainable": p3_attain,
        "zero_relevant_queries": zero_rel,
        "thin_relevant_queries": thin_rel,
        "random_baselines": {
            "pool_internal_mean": round(sum(floors) / len(floors), 4),
            "corpus_random_arm_ndcg3": macro["random"]["ndcg3"],
            "note": "정규화의 0은 '풀 내부 무작위'다. random arm(코퍼스 무작위)은 그보다 "
                    "낮아 정규화 시 0으로 절단된다 — 즉 정규화는 보수적이다",
        },
    }


def _recall_at_k(ranked: list[str], qrels: dict[str, str], k: int) -> float:
    rel = {u for u, v in qrels.items() if core.GRADE.get(v, 0) >= 2}
    if not rel:
        return 0.0
    return len([u for u in ranked[:k] if u in rel]) / len(rel)


def _multi_k(arm_tops: dict, all_qrels: dict[str, dict[str, str]],
             ks: tuple[int, ...] = (1, 3, 5, 10)) -> dict:
    """절단 k를 바꿔가며 재측정한다 — 추가 라벨링 없이 가능하다.

    풀이 5개 arm의 top-10 '합집합'으로 만들어졌으므로, 어떤 arm의 top-10에 있는 항목도
    전부 판정돼 있다(750건 중 미판정 0건 확인). 따라서 k<=10은 기존 라벨로 즉시 계산된다.
    앵커셋은 라벨 신뢰도(κ)를 재는 별도 표본이라 절단 k와 무관하다 — 사람 라벨은 영향 없음.

    k>10은 arm이 결과를 10건만 보유해 불가하고, 풀을 더 깊게 파면 새 적합 공고가 나와
    recall 분모가 커지므로 그때는 재판정·재채점이 필요하다.
    """
    scored = [a for a in ARMS if a != "random"] + ["random"]
    out = {}
    for k in ks:
        per_arm, series = {}, {}
        for arm in scored:
            nd = [core.ndcg_at_k(arm_tops[q].get(arm, []), all_qrels[q], k) for q in all_qrels]
            pr = [core.precision_at_k(arm_tops[q].get(arm, []), all_qrels[q], k) for q in all_qrels]
            rc = [_recall_at_k(arm_tops[q].get(arm, []), all_qrels[q], k) for q in all_qrels]
            series[arm] = nd
            per_arm[arm] = {
                "ndcg": round(sum(nd) / len(nd), 4),
                "precision": round(sum(pr) / len(pr), 4),
                "recall": round(sum(rc) / len(rc), 4),
                "n_at_ceiling": sum(1 for v in nd if v >= 0.999),
                "n_distinct": len(set(round(v, 4) for v in nd)),
            }
        # recall의 구조적 상한: 적합 n건이면 상위 k건으로 최대 min(k,n)/n
        ceil_r = [min(k, sum(1 for v in q.values() if core.GRADE.get(v, 0) >= 2))
                  / max(1, sum(1 for v in q.values() if core.GRADE.get(v, 0) >= 2))
                  for q in all_qrels.values()
                  if any(core.GRADE.get(v, 0) >= 2 for v in q.values())]
        comps = {}
        for i, a in enumerate(scored):
            for b in scored[i + 1:]:
                comps[f"{a}_vs_{b}"] = core.paired_bootstrap(series[a], series[b])
        out[f"k={k}"] = {
            "arms": per_arm,
            "recall_ceiling": round(sum(ceil_r) / len(ceil_r), 4),
            "n_significant": sum(1 for v in comps.values() if v["significant"]),
            "n_comparisons": len(comps),
            "comparisons": comps,
        }
    return out


def _measure(pool: dict, arm_tops: dict, all_qrels: dict[str, dict[str, str]]) -> dict:
    # core.random_baseline_ndcg는 시드 없는 random.sample로 몬테카를로를 돌린다 —
    # 그대로 두면 실행마다 정규화 분모가 ±0.001 흔들려 리포트가 재현되지 않는다.
    # 버전 스탬프로 회귀 비교를 하는 체계에서는 재현성이 조건이므로 여기서 시드를 고정한다.
    random.seed(20260729)

    per_query = {}
    for qid, info in pool.items():
        qrels = all_qrels.get(qid, {})
        if not qrels:
            continue
        tops = arm_tops.get(qid, {})
        arm_scores = {}
        for arm in ARMS:
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
        oracle = core.ndcg_at_k(oracle_uids, qrels, 3)
        for arm in ARMS:
            arm_scores[arm]["norm_ndcg3"] = round(
                core.normalized_score(arm_scores[arm]["ndcg3"], rand_floor, oracle), 4)

        per_query[qid] = {
            "query": info["query"],
            "category": info["category"],
            "n_judged": len(qrels),
            "label_dist": dict(Counter(qrels.values()).most_common()),
            "n_relevant": sum(1 for v in qrels.values() if core.GRADE.get(v, 0) >= 2),
            "random_floor": round(rand_floor, 4),
            "oracle_ndcg3": round(oracle, 4),
            "arms": arm_scores,
            "pool_miss": core.pool_miss_bounds(qrels, tops.get("bm25", []),
                                               tops.get("dense", [])),
        }

    metrics = ["ndcg3", "p3", "ap3", "norm_ndcg3"]
    series = {arm: {m: [per_query[q]["arms"][arm][m] for q in per_query] for m in metrics}
              for arm in ARMS}
    macro = {arm: {m: round(sum(v) / len(v), 4) if v else 0
                   for m, v in series[arm].items()} for arm in ARMS}

    comparisons = {}
    for i, a in enumerate(ARMS):
        for b in ARMS[i + 1:]:
            comparisons[f"{a}_vs_{b}"] = core.paired_bootstrap(
                series[a]["ndcg3"], series[b]["ndcg3"])

    by_axis = {}
    for axis, cats in ROLE_AXES.items():
        qs = [q for q, d in per_query.items() if d["category"] in cats]
        if not qs:
            continue
        by_axis[axis] = {arm: round(sum(per_query[q]["arms"][arm]["norm_ndcg3"]
                                       for q in qs) / len(qs), 4) for arm in ARMS}
        by_axis[axis]["n"] = len(qs)

    return {
        "headline": {
            "metric": "normalized_nDCG@3",
            "definition": "(actual - random_floor) / (pool_oracle - random_floor)",
            "best_arm": max(ARMS, key=lambda a: macro[a]["norm_ndcg3"]),
            "scores": {a: macro[a]["norm_ndcg3"] for a in ARMS},
        },
        "macro_average": macro,
        "comparisons": comparisons,
        "by_role_axis": by_axis,
        "per_query": per_query,
    }


def run() -> dict:
    pool_data = json.loads(POOL_SPEC_PATH.read_text(encoding="utf-8"))
    pool, arm_tops = pool_data["pool"], pool_data["arm_tops"]
    jdata = json.loads(JUDGMENTS_SPEC_PATH.read_text(encoding="utf-8"))
    judge_qrels = {qid: dict(q["labels"]) for qid, q in jdata["queries"].items()}

    human = _human_labels()
    patched = {qid: dict(labels) for qid, labels in judge_qrels.items()}
    n_over, n_flip = 0, 0
    for pk, hl in human.items():
        qid, uid = pk.split(":", 1)
        if qid in patched and uid in patched[qid]:
            n_over += 1
            if (patched[qid][uid] == "Correct") != (hl == "Correct"):
                n_flip += 1
            patched[qid][uid] = hl

    res_judge = _measure(pool, arm_tops, judge_qrels)
    res_human = _measure(pool, arm_tops, patched)

    rank_j = sorted(ARMS, key=lambda a: -res_judge["macro_average"][a]["norm_ndcg3"])
    rank_h = sorted(ARMS, key=lambda a: -res_human["macro_average"][a]["norm_ndcg3"])

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "track": (f"정규화 질의 {len(pool)}종 "
                  "(RAG_입출력_명세서 고정형: 직군+기술+연차)"),
        "version": {
            "judge_prompt": judge.PROMPT_VERSION,
            "pool_generated_at": pool_data.get("generated_at"),
            "pool_depth": pool_data.get("pool_depth", 10),
            "n_queries": len(pool),
            "n_judged_pairs": sum(len(v) for v in judge_qrels.values()),
            "corpus_snapshot": pool_data.get("corpus_snapshot"),
            "promoted_from": pool_data.get("promoted_from"),
        },
        "label_provenance": {
            "base": (f"gemini-2.5-flash-lite {judge.PROMPT_VERSION} 전량 판정 "
                     f"({sum(len(v) for v in judge_qrels.values())}쌍)"),
            "human_verified_pairs": n_over,
            "human_binary_flips": n_flip,
            "human_flip_rate": round(n_flip / n_over, 4) if n_over else None,
            "coverage": round(n_over / sum(len(v) for v in judge_qrels.values()), 4),
        },
        "bias_correction": {"note": "자연어 트랙 전수 라벨 기반이라 이 트랙에는 N/A"},
        "qrels_judge_only": res_judge,
        "qrels_human_patched": res_human,
        "label_sensitivity": {
            "ranking_judge": rank_j,
            "ranking_human_patched": rank_h,
            "ranking_stable": rank_j == rank_h,
            "delta_norm_ndcg3": {
                a: round(res_human["macro_average"][a]["norm_ndcg3"]
                         - res_judge["macro_average"][a]["norm_ndcg3"], 4) for a in ARMS},
        },
        "k_analysis": _k_analysis(pool, arm_tops, patched,
                                 res_human["per_query"], res_human["macro_average"]),
        # Recall@3의 천장은 1.0이 아니다 — 적합이 n건이면 상위 3건으로 회수할 수 있는 건
        # 최대 min(3,n)건이다. 적합 19건인 질의의 Recall@3 상한은 0.158에 불과하다.
        # 이 천장을 모르면 RAGAS의 context recall 0.41을 "낮다"고 오독한다.
        # 절단 k를 1·3·5·10으로 바꿔 재측정 — 추가 라벨링 0건. 사람 라벨 그대로 유지된다.
        "multi_k": _multi_k(arm_tops, patched),
        # 코퍼스가 1,172 -> 약 6,900건으로 커지면서 재현율 계열은 **더 비관적**이 된다.
        # 분모(적합 공고 수)는 풀 안에서만 세므로, 코퍼스가 커져 풀 밖의 적합 공고가
        # 늘어나면 실제 재현율은 여기 적힌 값보다 낮다. nDCG@3·P@3는 상위 3건만 보므로
        # 이 영향을 받지 않는다 — 재현율만 골라 해석할 때 주의해야 한다.
        "recall_is_pool_bounded": {
            "pool_depth": pool_data.get("pool_depth", 10),
            "note": ("Recall@k의 분모는 풀(5 arm × depth의 합집합) 안에서 판정된 적합 "
                     "공고 수다. 코퍼스가 6배 커졌으므로 풀 밖 적합 공고 비율이 늘어 "
                     "여기 값은 실제 재현율의 상한이다."),
        },
        "recall_at_3_ceiling": {
            track: round(
                sum(min(3, d["n_relevant"]) / d["n_relevant"]
                    for d in res["per_query"].values() if d["n_relevant"] > 0)
                / sum(1 for d in res["per_query"].values() if d["n_relevant"] > 0), 4)
            for track, res in (("judge_only", res_judge), ("human_patched", res_human))
        },
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"트랙: 정규화 질의 {len(pool)}종 / 판정 {report['version']['n_judged_pairs']}쌍")
    print(f"사람 검증: {n_over}쌍 ({report['label_provenance']['coverage']:.1%}), "
          f"이진 뒤집힘 {n_flip}건 ({report['label_provenance']['human_flip_rate']:.1%})\n")
    print(f"{'arm':<8} {'judge qrels':>12} {'human-patched':>15} {'Δ':>8}")
    for a in ARMS:
        j = res_judge["macro_average"][a]["norm_ndcg3"]
        h = res_human["macro_average"][a]["norm_ndcg3"]
        print(f"{a:<8} {j:>12.4f} {h:>15.4f} {h - j:>+8.4f}")
    print(f"\n순위(judge)        : {' > '.join(rank_j)}")
    print(f"순위(human-patched): {' > '.join(rank_h)}")
    print(f"순위 안정성: {'동일 — 라벨 강건' if rank_j == rank_h else '변동 — 라벨 의존'}")
    print(f"\n리포트: {REPORT_PATH}")
    return report


if __name__ == "__main__":
    run()
