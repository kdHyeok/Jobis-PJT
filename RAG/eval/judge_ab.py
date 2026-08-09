"""게이트 3 대안 트랙 — judge 모델 상향 A/B (HANDOFF §3-B).

가설: 게이트 3 FAIL(κ=0.4448)의 원인 일부가 judge 모델 용량(gemini-2.5-flash-lite)에
있다. 같은 프롬프트(v3)·같은 풀로 gemini-2.5-flash를 돌려 앵커 대비 κ가 오르는지 본다.

사전 등록 채택 기준 (실행 전 고정, HANDOFF §3-B):
    κ(flash vs 앵커) >= 0.60  또는  κ >= 0.4448 + 0.10 = 0.5448

설계 메모:
- 프롬프트는 judge.ACTIVE_PROMPT(v3) 그대로. 모델만 바꾼다 — 이게 이 A/B의 단일 변수다.
- 판정은 앵커 120쌍만이 아니라 pool_spec.json 풀 전량(439쌍)에 돌린다. 앵커만 뽑아
  재판정하면 배치 구성(같은 프롬프트에 함께 들어가는 공고 20건)이 lite 기준선과
  달라져 모델 외 변수가 섞인다. 전량이면 기준선과 동일 조건이고, 채택 시 그대로
  본판정 파일이 된다.
- 저장은 judgments_spec_flash.json. 기존 judgments_spec.json은 읽지도 쓰지도 않는다.
- κ 계산은 anchor._cohens_kappa_binary를 그대로 쓴다(본평가와 동일 정의).

실행:
    GMS_MODEL=gemini-2.5-flash python -X utf8 -m eval.judge_ab --judge
    python -X utf8 -m eval.judge_ab --compare
"""
from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# .env 를 읽은 뒤에 import 해야 한다 — anchor·judge 가 모듈 로드 시점에 환경변수를 읽는다.
from . import anchor, judge  # noqa: E402

EVAL_DIR = Path(__file__).parent
POOL_SPEC_PATH = EVAL_DIR / "pool_spec.json"
BASELINE_PATH = EVAL_DIR / "judgments_spec.json"          # v3 + flash-lite (기준선)
FLASH_PATH = EVAL_DIR / "judgments_spec_flash.json"       # v3 + flash   (실험군)
ANCHOR_DIR = EVAL_DIR / "anchor"
KEY_PATH = ANCHOR_DIR / "anchor_key.json"
REPORT_PATH = ANCHOR_DIR / "ab_report_flash.json"

BASELINE_KAPPA = 0.4448
ADOPT_ABS = 0.60
ADOPT_DELTA = 0.10


# ── 실험군 판정 ────────────────────────────────────────

def run_judge() -> None:
    model = os.environ.get("GMS_MODEL", "")
    if "lite" in model or not model:
        raise SystemExit(
            f"GMS_MODEL={model!r} — A/B 실험군은 비-lite 모델이어야 한다. "
            "예: GMS_MODEL=gemini-2.5-flash python -X utf8 -m eval.judge_ab --judge"
        )
    from jobrag.store import connect

    judge.JUDGMENTS_PATH = FLASH_PATH          # 기준선 파일 보호
    pool_data = json.loads(POOL_SPEC_PATH.read_text(encoding="utf-8"))
    print(f"실험군 판정: model={model}, prompt={judge.PROMPT_VERSION}, "
          f"저장={FLASH_PATH.name}")
    conn = connect()
    try:
        judge.judge_all(conn, pool_data["pool"])
    finally:
        conn.close()


# ── 라벨 로딩 ──────────────────────────────────────────

def _labels_from_judgments(path: Path) -> dict[str, str]:
    """{qid}:{uid} -> label"""
    data = json.loads(path.read_text(encoding="utf-8"))
    return {f"{qid}:{uid}": lab
            for qid, q in data.get("queries", {}).items()
            for uid, lab in q.get("labels", {}).items()}


def _anchor_labels(suffix: str) -> tuple[dict[str, str], dict[str, str]]:
    """앵커 시트에서 (primary, recheck) 라벨을 읽는다.

    suffix="_claude" -> session_*_claude.csv (Claude 앵커)
    suffix=""        -> session_easy.csv 등 (사람 채점본; 아직 공란이면 빈 dict)
    """
    primary, recheck = {}, {}
    for path in sorted(ANCHOR_DIR.glob("session_*.csv")):
        stem = path.stem
        is_claude = stem.endswith("_claude")
        if is_claude != bool(suffix):
            continue
        target = recheck if "recheck" in stem else primary
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                label = (row.get("label") or "").strip()
                if label in ("Correct", "Ambiguous", "Incorrect"):
                    target[f"{row['qid']}:{row['uid']}"] = label
    return primary, recheck


# ── 대조 ───────────────────────────────────────────────

def _binary(label: str) -> int:
    return 1 if label == "Correct" else 0


def _compare_arm(name: str, judge_labels: dict[str, str],
                 anchor_primary: dict[str, str]) -> dict:
    """judge 한 팔을 앵커에 대조 — κ, 일치율, 라벨별 정밀도, McNemar."""
    pairs = {k: v for k, v in anchor_primary.items() if k in judge_labels}
    kappa = anchor._cohens_kappa_binary(pairs, judge_labels)

    agree = sum(1 for k, h in pairs.items()
                if _binary(h) == _binary(judge_labels[k]))
    b = sum(1 for k, h in pairs.items()
            if _binary(h) == 1 and _binary(judge_labels[k]) == 0)
    c = sum(1 for k, h in pairs.items()
            if _binary(h) == 0 and _binary(judge_labels[k]) == 1)

    per_label = {}
    for judged_as in ("Correct", "Ambiguous", "Incorrect"):
        sampled = [(k, h) for k, h in pairs.items() if judge_labels[k] == judged_as]
        if not sampled:
            continue
        ok = sum(1 for _, h in sampled
                 if (h == "Correct") == (judged_as == "Correct"))
        per_label[judged_as] = {"n_sampled": len(sampled), "anchor_agrees": ok,
                                "rate": round(ok / len(sampled), 4)}

    return {
        "arm": name,
        "n_compared": len(pairs),
        "n_judged_total": len(judge_labels),
        "binary_kappa": round(kappa, 4),
        "binary_agreement": round(agree / len(pairs), 4) if pairs else None,
        "agreement_by_judge_label": per_label,
        "mcnemar": {
            "b_anchor_pos_llm_neg": b,
            "c_anchor_neg_llm_pos": c,
            "statistic": round((abs(b - c) - 1) ** 2 / (b + c), 4) if b + c else None,
            "direction": ("LLM inflates positives" if c > b else
                          "LLM deflates positives" if b > c else "balanced"),
        },
    }


def compare() -> dict:
    if not FLASH_PATH.exists():
        raise SystemExit(f"{FLASH_PATH.name} 없음 — 먼저 --judge 를 실행하라.")

    anchor_primary, _ = _anchor_labels("_claude")
    if len(anchor_primary) < 100:
        raise SystemExit(f"Claude 앵커 {len(anchor_primary)}쌍 — 120쌍이어야 한다.")

    baseline = _labels_from_judgments(BASELINE_PATH)
    flash = _labels_from_judgments(FLASH_PATH)

    arm_lite = _compare_arm("gemini-2.5-flash-lite (기준선)", baseline, anchor_primary)
    arm_flash = _compare_arm("gemini-2.5-flash (실험군)", flash, anchor_primary)

    k_lite, k_flash = arm_lite["binary_kappa"], arm_flash["binary_kappa"]
    delta = round(k_flash - k_lite, 4)
    adopt = k_flash >= ADOPT_ABS or delta >= ADOPT_DELTA

    # 두 judge 팔이 서로 얼마나 다른가 — κ가 안 움직여도 판정이 바뀐 건 아닌지 본다.
    common = set(baseline) & set(flash)
    flipped = [k for k in common if _binary(baseline[k]) != _binary(flash[k])]

    report = {
        "experiment": "judge 모델 상향 A/B (HANDOFF §3-B)",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "single_variable": "judge 모델만 교체. 프롬프트·풀·앵커 동일",
        "prompt_version": judge.PROMPT_VERSION,
        "anchor_source": anchor.ANCHOR_SOURCE,
        "n_anchor_primary": len(anchor_primary),
        "preregistered_criterion": {
            "rule": f"κ >= {ADOPT_ABS} 또는 기준선 대비 +{ADOPT_DELTA} 이상",
            "baseline_kappa_recorded": BASELINE_KAPPA,
            "baseline_kappa_recomputed": k_lite,
        },
        "arms": [arm_lite, arm_flash],
        "delta_kappa": delta,
        "judge_disagreement": {
            "n_common_pairs": len(common),
            "n_binary_flips": len(flipped),
            "flip_rate": round(len(flipped) / len(common), 4) if common else None,
        },
        "decision": "ADOPT" if adopt else "REJECT",
        "gate3_if_adopted": "PASS" if k_flash >= 0.60 else "FAIL (여전히 사람 채점 필요)",
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                           encoding="utf-8")

    print(f"\n앵커 대조 ({len(anchor_primary)}쌍, 앵커={anchor.ANCHOR_SOURCE})")
    for arm in (arm_lite, arm_flash):
        print(f"  {arm['arm']:<34} κ={arm['binary_kappa']:.4f}  "
              f"일치={arm['binary_agreement']:.4f}  n={arm['n_compared']}")
    print(f"  Δκ = {delta:+.4f}  (판정 뒤집힘 {len(flipped)}/{len(common)}쌍)")
    print(f"\n사전 등록 기준: κ>={ADOPT_ABS} 또는 Δ>=+{ADOPT_DELTA}  ->  {report['decision']}")
    print(f"게이트 3: {report['gate3_if_adopted']}")
    print(f"리포트: {REPORT_PATH}")
    return report


def main():
    args = sys.argv[1:]
    if "--judge" in args:
        run_judge()
    if "--compare" in args:
        compare()
    if not args:
        print("사용법: python -X utf8 -m eval.judge_ab --judge | --compare")


if __name__ == "__main__":
    main()
