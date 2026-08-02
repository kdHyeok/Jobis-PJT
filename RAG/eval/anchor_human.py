"""사람 채점 반영 — 게이트 3 판정 + 판정자 4자 비교 (HANDOFF §3-A).

2026-07-29 사람이 앵커 시트 3종을 손수 라벨링했다. 이 모듈은 그 라벨을 기준(ground truth)으로
삼아 판정자들을 대조한다. 지금까지의 κ는 전부 'LLM 대 LLM'이었고, 이제 처음으로
**사람 기준** 측정이 된다.

anchor.score()를 쓰지 않는 이유: 그 함수는 `session_*.csv`를 glob으로 읽어서 사람 시트와
`*_claude.csv`가 같이 잡힌다(HANDOFF §3-A 2번 경고). 파일을 임시로 옮기는 대신 읽을 파일을
명시적으로 지정한다 — 파일 이동은 중간에 실패하면 상태가 깨진다.

대조 대상 4자:
  human        — 사람 손수 라벨 (기준)
  gemini-lite  — judgments_spec.json      (본판정, v3 프롬프트)
  gemini-flash — judgments_spec_flash.json (§3-B 실험군, 미채택)
  claude       — session_*_claude.csv      (기존 LLM 앵커)

실행: python -X utf8 -m eval.anchor_human
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import anchor, judge

EVAL_DIR = Path(__file__).parent
ANCHOR_DIR = EVAL_DIR / "anchor"
KEY_PATH = ANCHOR_DIR / "anchor_key.json"
REPORT_PATH = ANCHOR_DIR / "anchor_report_human.json"

HUMAN_SHEETS = {"primary": ["session_easy.csv", "session_ambiguous.csv"],
                "recheck": ["session_recheck.csv"]}
CLAUDE_SHEETS = {"primary": ["session_easy_claude.csv", "session_ambiguous_claude.csv"],
                 "recheck": ["session_recheck_claude.csv"]}

GATE3_THRESHOLD = 0.60
CANON = {"correct": "Correct", "ambiguous": "Ambiguous", "incorrect": "Incorrect"}


# ── 로딩 ───────────────────────────────────────────────

def _read_sheets(names: list[str]) -> dict[str, str]:
    """라벨은 대소문자를 구분하지 않는다 — 사람이 손으로 채운 시트에는
    Incorrect/incorrect/InCorrect가 섞인다(2026-07-29 실측 54건). 정규화해 읽는다."""
    out = {}
    for name in names:
        path = ANCHOR_DIR / name
        if not path.exists():
            continue
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                raw = (row.get("label") or "").strip()
                label = CANON.get(raw.lower())
                if label:
                    out[f"{row['qid']}:{row['uid']}"] = label
    return out


def _read_judgments(filename: str) -> dict[str, str]:
    path = EVAL_DIR / filename
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {f"{qid}:{uid}": lab
            for qid, q in data.get("queries", {}).items()
            for uid, lab in q.get("labels", {}).items()}


# ── 지표 ───────────────────────────────────────────────

def _bin(label: str) -> int:
    """이진화: Correct만 양성. Ambiguous는 음성으로 접는다 — 본평가 지표(P@3)가
    Correct만 적합으로 세므로 게이트도 같은 기준이어야 한다."""
    return 1 if label == "Correct" else 0


def _compare(name: str, pred: dict[str, str], truth: dict[str, str]) -> dict:
    pairs = {k: v for k, v in truth.items() if k in pred}
    if not pairs:
        return {"judge": name, "n_compared": 0}

    kappa = anchor._cohens_kappa_binary(pairs, pred)
    agree = sum(1 for k, h in pairs.items() if _bin(h) == _bin(pred[k]))
    b = sum(1 for k, h in pairs.items() if _bin(h) == 1 and _bin(pred[k]) == 0)
    c = sum(1 for k, h in pairs.items() if _bin(h) == 0 and _bin(pred[k]) == 1)

    # 3분류 완전일치 — 이진화가 감추는 Ambiguous 처리 차이를 본다
    exact = sum(1 for k, h in pairs.items() if h == pred[k])

    per_label = {}
    for judged_as in ("Correct", "Ambiguous", "Incorrect"):
        sampled = [(k, h) for k, h in pairs.items() if pred[k] == judged_as]
        if not sampled:
            continue
        ok = sum(1 for _, h in sampled if (h == "Correct") == (judged_as == "Correct"))
        per_label[judged_as] = {"n": len(sampled), "agrees": ok,
                                "rate": round(ok / len(sampled), 4)}

    # 사람이 Correct라 한 것 중 판정기가 잡아낸 비율 = 재현율 관점
    human_pos = [k for k, h in pairs.items() if _bin(h) == 1]
    recall = (sum(1 for k in human_pos if _bin(pred[k]) == 1) / len(human_pos)
              if human_pos else None)
    pred_pos = [k for k in pairs if _bin(pred[k]) == 1]
    precision = (sum(1 for k in pred_pos if _bin(pairs[k]) == 1) / len(pred_pos)
                 if pred_pos else None)

    return {
        "judge": name,
        "n_compared": len(pairs),
        "binary_kappa": round(kappa, 4),
        "binary_agreement": round(agree / len(pairs), 4),
        "exact_3class_agreement": round(exact / len(pairs), 4),
        "precision_vs_human": round(precision, 4) if precision is not None else None,
        "recall_vs_human": round(recall, 4) if recall is not None else None,
        "agreement_by_judge_label": per_label,
        "mcnemar": {
            "b_human_pos_judge_neg": b,
            "c_human_neg_judge_pos": c,
            "statistic": round((abs(b - c) - 1) ** 2 / (b + c), 4) if b + c else None,
            "direction": ("judge inflates positives" if c > b else
                          "judge deflates positives" if b > c else "balanced"),
        },
        "gate3": "PASS" if kappa >= GATE3_THRESHOLD else "FAIL",
    }


# ── 경계 기준 역추출 ───────────────────────────────────

def _kappa_ci(pred: dict[str, str], truth: dict[str, str],
              n_resamples: int = 10000, seed: int = 42) -> dict:
    """κ의 부트스트랩 95% CI.

    n=118에서 κ=0.5921을 점추정치만 보고 '기준 0.60 미달'로 단정하면 표본 오차를
    무시하는 것이다. CI가 0.60을 포함하면 그 FAIL은 통계적으로 확정된 실패가 아니다.
    """
    import random as _r
    keys = [k for k in truth if k in pred]
    rng = _r.Random(seed)
    n = len(keys)
    vals = []
    for _ in range(n_resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        t = {i: truth[keys[j]] for i, j in enumerate(idx)}
        p = {i: pred[keys[j]] for i, j in enumerate(idx)}
        vals.append(anchor._cohens_kappa_binary(t, p))
    vals.sort()
    return {"lo": round(vals[int(n_resamples * 0.025)], 4),
            "hi": round(vals[int(n_resamples * 0.975)], 4)}


def _boundary_analysis(human: dict[str, str], lite: dict[str, str]) -> dict:
    """사람이 실제로 어떤 기준을 적용했는지 불일치 사례에서 역추출한다.

    사전에 기준 2건을 확정하지 못한 채 채점이 끝났으므로, 확정 대신 '적용된 기준'을
    사후 기록한다(HANDOFF §3-A 1번의 대체 이행). qid에 직군·연차가 인코딩돼 있어
    질의 쪽 조건으로 분류할 수 있다.
    """
    pool = json.loads((EVAL_DIR / "pool_spec.json").read_text(encoding="utf-8"))["pool"]
    qmeta = {qid: p["spec"] for qid, p in pool.items()}

    buckets = {"신입_질의": Counter(), "경력_질의": Counter(),
               "풀스택_질의": Counter(), "그외_질의": Counter()}
    disagree = {"신입_질의": 0, "경력_질의": 0, "풀스택_질의": 0, "그외_질의": 0}
    totals = dict.fromkeys(buckets, 0)

    for pk, h in human.items():
        qid = pk.split(":")[0]
        spec = qmeta.get(qid)
        if not spec:
            continue
        if spec["exp_years"] is None:
            key = "신입_질의"
        elif "풀스택" in spec["role"]:
            key = "풀스택_질의"
        elif spec["exp_years"] is not None:
            key = "경력_질의"
        else:
            key = "그외_질의"
        buckets[key][h] += 1
        totals[key] += 1
        if pk in lite and _bin(h) != _bin(lite[pk]):
            disagree[key] += 1

    return {
        "note": "사전 확정 대신 사람이 실제 적용한 기준을 사후 기록 (HANDOFF §3-A 1번 대체 이행)",
        "by_query_type": {
            k: {"n": totals[k], "human_label_dist": dict(v),
                "judge_disagreements": disagree[k],
                "disagree_rate": round(disagree[k] / totals[k], 4) if totals[k] else None}
            for k, v in buckets.items() if totals[k]
        },
    }


# ── 실행 ───────────────────────────────────────────────

def run() -> dict:
    human = _read_sheets(HUMAN_SHEETS["primary"])
    human_recheck = _read_sheets(HUMAN_SHEETS["recheck"])
    claude = _read_sheets(CLAUDE_SHEETS["primary"])
    lite = _read_judgments("judgments_spec.json")
    flash = _read_judgments("judgments_spec_flash.json")

    arms = [_compare("gemini-2.5-flash-lite (본판정 v3)", lite, human),
            _compare("gemini-2.5-flash (§3-B 실험군)", flash, human),
            _compare("claude-fable-5 (기존 LLM 앵커)", claude, human)]
    for a, pred in zip(arms, (lite, flash, claude)):
        if a.get("n_compared"):
            a["kappa_ci_95"] = _kappa_ci(pred, human)

    # 사람 자기일관성 (게이트 3b) — LLM 앵커에서는 temperature 0 때문에 구조적으로 1.0이 되어
    # 아무것도 검출하지 못했다. 사람 재검사는 처음으로 이 게이트가 실제로 작동하는 경우다.
    overlap = {k: human[k] for k in human_recheck if k in human}
    self_kappa = (anchor._cohens_kappa_binary(overlap, human_recheck)
                  if len(overlap) >= 10 else None)
    self_exact = (sum(1 for k in overlap if overlap[k] == human_recheck[k]) / len(overlap)
                  if overlap else None)
    # 원일치율을 따로 남긴다. κ는 우연 일치를 보정한 값이라 (1-κ)는 뒤집힘 비율이 아니다 —
    # 여기서는 κ 0.855 대 원일치 0.947로 3배 가까이 벌어진다.
    self_raw = (sum(1 for k in overlap if _bin(overlap[k]) == _bin(human_recheck[k]))
                / len(overlap) if overlap else None)

    best = max((a for a in arms if a.get("n_compared")),
               key=lambda a: a["binary_kappa"])

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ground_truth": "사람 손수 라벨 (2026-07-29)",
        "judge_prompt_version": judge.PROMPT_VERSION,
        "n_human_primary": len(human),
        "n_human_recheck": len(human_recheck),
        "human_label_dist": dict(Counter(human.values()).most_common()),
        "note_label_case": "사람 시트의 대소문자 변형 54건을 정규화해 반영",
        "gate3": {
            "threshold": GATE3_THRESHOLD,
            "metric": "Cohen's κ (이진: Correct vs 그외), 본판정 judge 대 사람",
            "value": arms[0]["binary_kappa"],
            "verdict": arms[0]["gate3"],
        },
        "gate3b_human_self_consistency": {
            "n_overlap": len(overlap),
            "binary_kappa": round(self_kappa, 4) if self_kappa is not None else None,
            "binary_agreement_raw": round(self_raw, 4) if self_raw is not None else None,
            "exact_3class_agreement": round(self_exact, 4) if self_exact is not None else None,
            "verdict": ("N/A -재검사 부족" if self_kappa is None else
                        "PASS" if self_kappa >= arms[0]["binary_kappa"] else
                        "FAIL -사람 자기일관성이 judge-사람 κ보다 낮음"),
            "note": "LLM 앵커는 temperature 0으로 κ가 구조적으로 1.0이라 무의미했다. "
                    "사람 재검사는 이 게이트가 실제로 작동하는 첫 사례다.",
        },
        # 사람 자기일관성이 판정 상한이다 — 기준 자체가 흔들리는 만큼 judge-사람 κ는
        # 구조적으로 그 위로 못 올라간다. 게이트 기준 0.60은 이 천장을 모른 채 정해졌으므로
        # '천장 대비 달성률'을 함께 봐야 0.60이 애초에 도달 가능한 수준인지 판단할 수 있다.
        "noise_ceiling": {
            "human_self_kappa": round(self_kappa, 4) if self_kappa is not None else None,
            "judge_kappa": arms[0]["binary_kappa"],
            "attainment_vs_ceiling": (round(arms[0]["binary_kappa"] / self_kappa, 4)
                                      if self_kappa else None),
            "threshold_as_pct_of_ceiling": (round(GATE3_THRESHOLD / self_kappa, 4)
                                            if self_kappa else None),
            "note": "사람의 이진 원일치율은 0.947 — 뒤집은 것은 5.3%다. "
                    "(1-κ)=14.5%를 뒤집힘 비율로 읽으면 3배 과장된다. "
                    "그래도 이 잡음이 judge-사람 κ의 상한을 만든다.",
        },
        "closest_to_human": best["judge"],
        "arms": arms,
        "boundary_criteria_applied": _boundary_analysis(human, lite),
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"기준: 사람 라벨 {len(human)}쌍 (재검사 {len(human_recheck)}쌍)")
    print(f"사람 라벨 분포: {report['human_label_dist']}\n")
    print(f"{'판정자':<34} {'κ':>7} {'이진일치':>9} {'3분류':>7} {'정밀도':>7} {'재현율':>7}")
    for a in arms:
        if not a.get("n_compared"):
            continue
        print(f"{a['judge']:<34} {a['binary_kappa']:>7.4f} {a['binary_agreement']:>9.4f} "
              f"{a['exact_3class_agreement']:>7.4f} "
              f"{a['precision_vs_human'] or 0:>7.4f} {a['recall_vs_human'] or 0:>7.4f}")
    print(f"\n게이트 3 (본판정 κ >= {GATE3_THRESHOLD}): "
          f"{report['gate3']['value']:.4f} -> {report['gate3']['verdict']}")
    g3b = report["gate3b_human_self_consistency"]
    print(f"게이트 3b 사람 자기일관성: κ={g3b['binary_kappa']} "
          f"(3분류 {g3b['exact_3class_agreement']}) -> {g3b['verdict']}")
    print(f"사람에 가장 가까운 판정자: {best['judge']}")
    print(f"\n리포트: {REPORT_PATH}")
    return report


if __name__ == "__main__":
    run()
