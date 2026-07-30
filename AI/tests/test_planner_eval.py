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


def _run(agents=(), asked=False, path="planner", confidence=0.9) -> dict:
    return {"agents": tuple(agents), "asked": asked, "path": path,
            "confidence": confidence}


def test_score_case_exact_sequence_match():
    case = {"caseId": "c", "expectedAgents": ["fit_analysis", "coverletter_draft"], "expectAsk": False}
    ok = score_case(case, [_run(("fit_analysis", "coverletter_draft"))])
    assert ok["correct"] and ok["ask_accuracy"] == 1.0

    wrong_order = score_case(case, [_run(("coverletter_draft", "fit_analysis"))])
    assert not wrong_order["correct"]


def test_score_case_ask_expected():
    case = {"caseId": "c", "expectedAgents": [], "expectAsk": True}
    asked = score_case(case, [_run(asked=True)])
    assert asked["correct"]

    executed = score_case(case, [_run(("fit_analysis",))])
    assert not executed["correct"] and executed["ask_accuracy"] == 0.0


# --- 정확도와 안정성을 갈라 센다 (이식해 온 지표의 개선점) --------------------------
def test_stable_correct():
    """N회 모두 기대와 같다 — 정확하고 안정적."""

    case = {"caseId": "c", "expectedAgents": ["fit_analysis"], "expectAsk": False}
    r = score_case(case, [_run(("fit_analysis",))] * 3)
    assert (r["accuracy"], r["stability"], r["verdict"]) == (1.0, 1.0, "stable-correct")


def test_stable_wrong_is_not_flaky():
    """**N회 모두 똑같이 틀렸다** — 재실행해도 안 낫는 명세·프롬프트 결함이다.

    "일관성 0/3" 하나로는 이걸 flaky 와 구분할 수 없다. 원인과 처방이 다르므로 갈라 센다.
    """

    case = {"caseId": "c", "expectedAgents": ["fit_analysis"], "expectAsk": False}
    r = score_case(case, [_run(("posting_analysis",))] * 3)
    assert (r["accuracy"], r["stability"], r["verdict"]) == (0.0, 1.0, "stable-wrong")


def test_unstable_is_reported_with_every_observed_outcome():
    """결과가 갈리면 불안정 — 무엇이 몇 번 나왔는지 전부 남긴다(이탈을 덮지 않는다)."""

    case = {"caseId": "c", "expectedAgents": ["fit_analysis"], "expectAsk": False}
    r = score_case(case, [_run(("fit_analysis",)), _run(("fit_analysis",)), _run(asked=True)])
    assert r["verdict"] == "unstable"
    assert r["accuracy"] == round(2 / 3, 4)
    assert r["stability"] == round(2 / 3, 4)
    assert r["observed"] == {"fit_analysis": 2, "ASK": 1}


def test_single_run_stays_compatible_with_the_old_baseline_axis():
    """1회 실행이면 예전 baseline 과 같은 값이 나온다 — 축을 바꾸지 않고 늘렸다."""

    case = {"caseId": "c", "expectedAgents": ["fit_analysis"], "expectAsk": False}
    r = score_case(case, [_run(("fit_analysis",))])
    assert r["runs"] == 1 and r["accuracy"] == 1.0 and r["correct"] is True


def test_weak_model_failure_mode_is_distinguishable():
    """**모델을 갈아 끼울 때 원인을 가르는 지표.**

    약한 모델의 알려진 실패 모드는 "에이전트는 맞게 고르면서 confidence 를 0.00 으로 채우는"
    것이다(2026-07-28 gpt-4.1-nano 실측). 그러면 임계값에 걸려 전부 대화형으로 후퇴하는데,
    결과만 보면 "라우팅을 못 한다"로 오진한다. path 분포와 confidence 가 그것을 구분한다.
    """

    case = {"caseId": "c", "expectedAgents": ["fit_analysis"], "expectAsk": False}
    weak = score_case(case, [_run(("career_chat",), path="fallback", confidence=0.0)] * 3)
    assert weak["paths"] == {"fallback": 3}
    assert weak["mean_confidence"] == 0.0

    summary = aggregate([weak])
    assert summary["fallback_rate"] == 1.0, "폴백으로 후퇴한 비율이 드러나야 한다"
    assert summary["mean_confidence"] == 0.0


def test_aggregate_counts():
    case_ok = {"caseId": "a", "expectedAgents": ["fit_analysis"], "expectAsk": False}
    case_bad = {"caseId": "b", "expectedAgents": ["fit_analysis"], "expectAsk": False}
    results = [
        score_case(case_ok, [_run(("fit_analysis",))] * 2),                       # stable-correct
        score_case(case_bad, [_run(("posting_analysis",))] * 2),                  # stable-wrong
        score_case(case_bad, [_run(("fit_analysis",)), _run(("career_chat",))]),  # unstable
        score_case(case_ok, [_run(path="llm_failed"), _run(("fit_analysis",))]),  # unstable
    ]
    summary = aggregate(results)
    assert summary["cases"] == 4
    assert summary["runs_per_case"] == 2
    assert summary["stable_correct"] == 1
    assert summary["stable_wrong"] == 1
    assert summary["unstable"] == 2
    assert summary["llm_failed"] == 1
    assert 0.0 <= summary["mean_stability"] <= 1.0


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
