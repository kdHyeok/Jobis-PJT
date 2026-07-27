"""플래너 평가 러너 — 발화 × 기대 실행 시퀀스 (llm-planner-design.md §4).

플래너 경로(plan_agents → validate_plan)의 끝단 결과를 기대값과 비교한다.
기대값은 "최종 실행 시퀀스"라서 플래너의 선택 실수가 검증기 보정으로 살아나는 것까지
포함해 측정한다 — 사용자에게 실제로 일어나는 일이 평가 대상.

    python -m jobis_ai.eval.planner_harness evals/planner_dataset.json
    python -m jobis_ai.eval.planner_harness evals/planner_dataset.json --save evals/planner_baseline.json

지표 로직 검증은 tests/test_planner_eval.py 가 담당.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from jobis_ai.orchestrator.planner import CONFIDENCE_THRESHOLD, plan_agents
from jobis_ai.orchestrator.router import validate_plan

_ROOT = Path(__file__).resolve().parents[3]

# 평가용 더미 세션 자산 — 존재 여부만 판정에 쓰이므로 내용은 최소로.
_DUMMY_ASSETS: dict[str, Any] = {
    "resume": {"sourceType": "text", "value": "Python Django 백엔드 3년"},
    "job_posting": {"sourceType": "text", "value": "백엔드 개발자 채용 공고"},
    "analysis": {"fitGrade": "중", "gaps": [{"requirementId": "r1"}]},
    "roadmap": {"roadmap": [{"title": "학습"}]},
    "preferences": {"roles": ["백엔드"], "companies": [], "domains": [], "turns": 1},
}


def build_session(assets: list[str]) -> dict[str, Any]:
    """케이스의 자산 이름 목록을 더미 세션으로 확장한다."""

    return {name: _DUMMY_ASSETS[name] for name in assets}


def dispatch_case(case: dict) -> dict[str, Any]:
    """한 케이스를 플래너 경로로 돌려 최종 실행 시퀀스를 얻는다."""

    session = build_session(case.get("assets", []))
    message = case["message"]

    plan, _warnings = plan_agents(message, session)
    if plan is None:
        # LLM 실패 — 운영에선 대화형 에이전트가 받지만, 평가에선 플래너 실패로 따로 센다.
        return {"agents": (), "asked": True, "path": "llm_failed"}
    if not plan.agents or plan.confidence < CONFIDENCE_THRESHOLD:
        # 확신이 낮아 판단을 못 한 경우 — 대화로 넘긴 것이므로 "실행 없음"으로 센다.
        return {"agents": (), "asked": True, "path": "planner",
                "selected": list(plan.agents), "confidence": plan.confidence}
    dispatch = validate_plan(plan.agents, session)
    return {"agents": dispatch.agents, "asked": False, "path": "planner",
            "selected": list(plan.agents), "confidence": plan.confidence}


def score_case(case: dict, outcome: dict[str, Any]) -> dict[str, Any]:
    """기대값 대비 채점. 정답 = (되묻기 일치) AND (실행이면 시퀀스 완전 일치)."""

    expect_ask = bool(case.get("expectAsk"))
    expected = tuple(case.get("expectedAgents", []))
    ask_match = outcome["asked"] == expect_ask
    seq_match = ask_match and (expect_ask or outcome["agents"] == expected)
    return {
        "caseId": case.get("caseId", "?"),
        "correct": seq_match,
        "ask_match": ask_match,
        "expected": list(expected) if not expect_ask else "ASK",
        "actual": "ASK" if outcome["asked"] else list(outcome["agents"]),
        "path": outcome["path"],
    }


def aggregate(results: list[dict]) -> dict[str, Any]:
    n = len(results) or 1
    correct = sum(1 for r in results if r["correct"])
    ask_match = sum(1 for r in results if r["ask_match"])
    llm_failed = sum(1 for r in results if r["path"] == "llm_failed")
    return {
        "cases": len(results),
        "sequence_accuracy": round(correct / n, 4),
        "ask_accuracy": round(ask_match / n, 4),
        "llm_failed": llm_failed,
    }


def run_dataset(path: str | Path) -> tuple[list[dict], dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = data["cases"] if isinstance(data, dict) else data
    results = [score_case(c, dispatch_case(c)) for c in cases]
    return results, aggregate(results)


def _print_report(results: list[dict], summary: dict) -> None:
    print("\n===== 케이스별 =====")
    for r in results:
        mark = "O" if r["correct"] else "X"
        print(f"  [{mark}] {r['caseId']:32} 기대={r['expected']}  실제={r['actual']}")
    print("\n===== 전체 요약 =====")
    for k, val in summary.items():
        print(f"  {k}: {val}")


def main() -> None:
    parser = argparse.ArgumentParser(description="플래너 평가 하네스 (llm-planner-design.md §4)")
    parser.add_argument("dataset", nargs="?", default=str(_ROOT / "evals" / "planner_dataset.json"))
    parser.add_argument("--save", help="baseline 리포트 저장 경로")
    args = parser.parse_args()

    mode = "플래너(실 LLM 호출)"
    print(f"플래너 평가 — {mode} 모드")
    results, summary = run_dataset(args.dataset)
    _print_report(results, summary)

    if args.save:
        Path(args.save).write_text(
            json.dumps({"mode": mode, "summary": summary, "cases": results},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nbaseline 저장: {args.save}")


if __name__ == "__main__":
    main()
