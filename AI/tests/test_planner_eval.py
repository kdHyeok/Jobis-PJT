"""플래너 평가 하네스 테스트 — 채점·집계 로직과 폴백 모드 실행 (LLM 없음).

실 LLM 정확도 측정은 planner_harness CLI 가 담당. 여기서는 지표 로직이 맞는지,
데이터셋이 스키마대로 읽히는지, 폴백 모드가 결정론으로 도는지만 검증한다.
"""

from __future__ import annotations

from pathlib import Path

from jobis_ai.eval.planner_harness import (
    aggregate,
    build_session,
    dispatch_case,
    run_dataset,
    score_case,
)

_DATASET = Path(__file__).resolve().parents[1] / "evals" / "planner_dataset.json"


def test_score_case_exact_sequence_match():
    case = {"caseId": "c", "expectedAgents": ["fit_analysis", "coverletter_draft"], "expectAsk": False}
    ok = score_case(case, {"agents": ("fit_analysis", "coverletter_draft"), "asked": False, "path": "planner"})
    assert ok["correct"] and ok["ask_match"]

    wrong_order = score_case(case, {"agents": ("coverletter_draft", "fit_analysis"), "asked": False, "path": "planner"})
    assert not wrong_order["correct"]


def test_score_case_ask_expected():
    case = {"caseId": "c", "expectedAgents": [], "expectAsk": True}
    asked = score_case(case, {"agents": (), "asked": True, "path": "planner"})
    assert asked["correct"]

    executed = score_case(case, {"agents": ("fit_analysis",), "asked": False, "path": "planner"})
    assert not executed["correct"] and not executed["ask_match"]


def test_aggregate_counts():
    results = [
        {"correct": True, "ask_match": True, "path": "planner"},
        {"correct": False, "ask_match": True, "path": "planner"},
        {"correct": False, "ask_match": False, "path": "llm_failed"},
        {"correct": True, "ask_match": True, "path": "planner"},
    ]
    summary = aggregate(results)
    assert summary["cases"] == 4
    assert summary["sequence_accuracy"] == 0.5
    assert summary["ask_accuracy"] == 0.75
    assert summary["llm_failed"] == 1


def test_build_session_expands_assets():
    session = build_session(["resume", "analysis"])
    assert set(session) == {"resume", "analysis"}
    assert session["analysis"]["fitGrade"] == "중"


def test_dispatch_case_without_llm_counts_as_planner_failure():
    """LLM 미설정(conftest)이면 플래너 실패로 집계된다 — 폴백으로 점수를 가리지 않는다."""

    case = {"message": "자소서 써줘", "assets": ["resume", "job_posting"]}
    outcome = dispatch_case(case)
    assert outcome["path"] == "llm_failed"


def test_dataset_runs_without_crashing():
    """데이터셋 전체가 크래시 없이 돌고 스키마가 유효해야 한다."""

    results, summary = run_dataset(_DATASET)
    assert summary["cases"] == len(results) == 46
    assert summary["llm_failed"] == len(results)     # LLM 미설정 — 전 케이스 플래너 실패
    assert 0.0 <= summary["sequence_accuracy"] <= 1.0
