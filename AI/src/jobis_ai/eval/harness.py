"""평가 러너 (설계 18.3 실험·개선 루프).

평가셋을 로드해 파이프라인 노드를 실행하고, 케이스별/전체 지표를 집계해 리포트한다.
baseline 을 저장해 두면 프롬프트·구조 변경 후 동일 회귀셋으로 개선 전후를 비교할 수 있다.

    python -m jobis_ai.eval.harness evals/dataset.sample.json
    python -m jobis_ai.eval.harness evals/dataset.sample.json --save evals/baseline.json

주의: 실제 LLM 을 호출한다(비용·시간). 순수 지표 로직 검증은 tests/test_eval_metrics.py 가 담당.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from jobis_ai.eval import metrics
from jobis_ai.graph.nodes import (
    analyze_gap,
    build_user_profile,
    parse_job_posting,
    plan_roadmap,
)
from jobis_ai.verify_rules import iter_user_facing_texts

_ROOT = Path(__file__).resolve().parents[3]


def _resolve(source: dict | None) -> dict | None:
    """dataset 의 상대 파일 경로를 레포 루트 기준 절대경로로 바꾼다."""

    if source and source.get("sourceType") == "file":
        p = Path(source["value"])
        if not p.is_absolute():
            source = {**source, "value": str((_ROOT / p).resolve())}
    return source


def run_case(case: dict) -> dict[str, Any]:
    """한 케이스에 대해 파이프라인을 돌리고 지표를 계산한다."""

    constraints = case.get("constraints", {})
    weeks = constraints.get("preparationPeriodWeeks", 0)
    weekly = constraints.get("availableHoursPerWeek", 0)

    state: dict[str, Any] = {
        "jobPostingInput": _resolve(case.get("jobPosting")),
        "resumeInput": _resolve(case.get("resume")),
        "preparationPeriodWeeks": weeks,
        "availableHoursPerWeek": weekly,
    }

    posting = parse_job_posting(state)["normalizedJobPosting"]
    state["normalizedJobPosting"] = posting
    profile = build_user_profile(state)["normalizedUserProfile"]
    state["normalizedUserProfile"] = profile
    gap = analyze_gap(state)["gapAnalysisResult"]
    state["gapAnalysisResult"] = gap
    roadmap = plan_roadmap(state)["roadmapResult"]

    result: dict[str, Any] = {"caseId": case.get("caseId", "?")}

    # 1) 공고 파싱 F1 (정답 라벨이 있을 때만)
    labels = case.get("labels") or {}
    gold = (labels.get("requiredRequirements") or []) + (labels.get("preferredRequirements") or [])
    if gold:
        predicted = [r["text"] for r in posting.get("requiredRequirements", [])] + \
                    [r["text"] for r in posting.get("preferredRequirements", [])]
        result["requirement_f1"] = metrics.requirement_f1(predicted, gold)

    # 2) 근거성
    evidence_ids = [e.get("evidenceId") for e in profile.get("evidenceMap", []) if e.get("evidenceId")]
    result["groundedness"] = metrics.groundedness(gap.get("requirementStatus", []), evidence_ids)

    # 3) 표현 정책
    result["policy"] = metrics.policy_violations(iter_user_facing_texts(gap, roadmap))

    # 4) 로드맵 제약 준수
    result["roadmap"] = metrics.roadmap_compliance(roadmap, weeks, weekly)

    return result


def aggregate(case_results: list[dict]) -> dict[str, Any]:
    """케이스별 지표를 전체 요약으로 집계한다."""

    n = len(case_results) or 1
    f1s = [c["requirement_f1"]["f1"] for c in case_results if "requirement_f1" in c]
    grounds = [c["groundedness"]["groundedness"] for c in case_results]
    violations = sum(c["policy"]["violations"] for c in case_results)
    compliant = sum(1 for c in case_results if c["roadmap"]["compliant"])
    return {
        "cases": len(case_results),
        "avg_requirement_f1": round(sum(f1s) / len(f1s), 4) if f1s else None,
        "avg_groundedness": round(sum(grounds) / n, 4),
        "total_policy_violations": violations,
        "roadmap_compliance_rate": round(compliant / n, 4),
    }


def load_dataset(path: str | Path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data["cases"] if isinstance(data, dict) else data


def _print_report(case_results: list[dict], summary: dict) -> None:
    print("\n===== 케이스별 지표 =====")
    for c in case_results:
        f1 = c.get("requirement_f1", {}).get("f1", "-")
        g = c["groundedness"]["groundedness"]
        v = c["policy"]["violations"]
        rc = "OK" if c["roadmap"]["compliant"] else "X"
        print(f"  {c['caseId']:32} F1={f1}  근거성={g}  금지표현={v}  로드맵={rc}")
    print("\n===== 전체 요약 =====")
    for k, val in summary.items():
        print(f"  {k}: {val}")


def main() -> None:
    parser = argparse.ArgumentParser(description="자비스 에이전트 평가 하네스 (설계 18장)")
    parser.add_argument("dataset", nargs="?", default=str(_ROOT / "evals" / "dataset.sample.json"))
    parser.add_argument("--save", help="baseline 리포트를 저장할 경로(개선 전후 비교용)")
    args = parser.parse_args()

    from jobis_ai.eval import provenance

    meta = provenance()
    cases = load_dataset(args.dataset)
    print(f"평가셋 {len(cases)}건 실행 (실 LLM 호출) — "
          f"provider={meta['provider']} model={meta['model']}…")
    case_results = [run_case(c) for c in cases]
    summary = aggregate(case_results)
    _print_report(case_results, summary)

    if args.save:
        # meta 를 맨 앞에 둔다 — 파일을 열면 "무엇으로 잰 수치인가"가 첫 줄에 보여야 한다.
        Path(args.save).write_text(
            json.dumps({"meta": meta, "dataset": args.dataset,
                        "summary": summary, "cases": case_results},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nbaseline 저장: {args.save} ({meta['provider']}/{meta['model']}, {meta['measuredAt']})")


if __name__ == "__main__":
    main()
