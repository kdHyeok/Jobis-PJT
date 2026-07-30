"""관찰 규칙 — 실행 뒤 남은 계획을 다시 정한다 (`orchestrator/observe_rules.py`).

전에는 이 자리에서 경량 LLM(`planner.observe_after`)이 결과 요약을 보고 continue/finish/call
을 냈다. 규칙으로 내린 근거는 모듈 docstring 에 있다. 여기서는 **규칙이 LLM 이 못 하던 일을
하는지**를 검사한다 — 특히 전제 붕괴 가드(실측 결함).

프로토타입 대응: `tests/checks.py` 가 조건엣지 함수를 LLM 없이 직접 호출해 검사한 것과 같다.
"""

from __future__ import annotations

from jobis_ai.agents import AgentResult
from jobis_ai.orchestrator.observe_rules import drop_unrunnable, observe

_RESUME = {"sourceType": "text", "value": "Python Django 백엔드 3년"}
_POSTING = {"sourceType": "text", "value": "백엔드 채용. 자격요건 Rust 7년"}
_ANALYSIS = {"status": "completed", "fitGrade": "상", "overallScore": 0.81}


# --- ② 전제 붕괴 → 제외 -----------------------------------------------------------
def test_forward_simulation_keeps_steps_a_predecessor_will_enable():
    """**큐를 앞에서부터 시뮬레이션한다.**

    `job_recommend` 는 지금 전제(resume·preferences)가 하나도 없어 못 돌지만, 앞에 있는
    `preference_intake` 가 `preferences` 를 만든다. "지금 못 돈다"는 이유로 빼면 정상
    파이프라인을 부순다 — 이 가드가 없으면 규칙이 버그가 된다.
    """

    queue, note = drop_unrunnable(["preference_intake", "job_recommend"], [], {})
    assert queue == ["preference_intake", "job_recommend"]
    assert note == ""


def test_step_with_no_producer_is_dropped_with_reason():
    """아무도 만들지 않는 전제면 제외하고, **왜 못 했는지 말한다.**"""

    session = {"resume": _RESUME}
    queue, note = drop_unrunnable(["coverletter_draft"], [], session)
    assert queue == []
    assert "진행하지 못했" in note
    assert "적합도 분석 결과" in note, "결측 자산을 사람이 읽는 이름으로 말한다"


def test_broken_precondition_is_the_measured_defect():
    """실측 결함 재현 방지: 판정이 실패해 analysis 가 없으면 자소서를 실행하지 않는다.

    2026-07-29 재현: `fit_analysis` 가 `analysis` 를 못 만들었는데 `coverletter_draft` 가
    그대로 돌아 **analysis=None 위에서 초안을 썼다.** 예전 판정("하나라도 돌 수 있으면 계속")은
    못 도는 항목을 그대로 실행했다 — 그게 직접 원인이다.
    """

    session = {"resume": _RESUME, "job_posting": _POSTING}      # analysis 없음
    result = observe(["fit_analysis"], {"fit_analysis": AgentResult(data={"status": "failed"})},
                     ["coverletter_draft"], ["fit_analysis"], session)
    assert result.action == "finish"
    assert result.queue == ()
    assert result.rule == "preconditions_broken"
    assert "진행하지 못했" in result.note


def test_runnable_steps_survive_alongside_dropped_ones():
    """못 도는 것만 빼고 도는 것은 남긴다 — 하나가 막혀 전부 죽이지 않는다."""

    session = {"resume": _RESUME, "roadmap": [{"title": "학습"}]}
    queue, note = drop_unrunnable(["coverletter_draft", "roadmap_manager"], [], session)
    assert queue == ["roadmap_manager"]
    assert note


def test_already_dispatched_is_cleared_from_queue():
    """같은 턴에 이미 돈 것은 큐에서 정리한다(재실행 방어) — 제외 문구는 내지 않는다."""

    session = {"resume": _RESUME}
    queue, note = drop_unrunnable(["resume_diagnosis"], ["resume_diagnosis"], session)
    assert queue == []
    assert note == ""


def test_unknown_name_is_left_for_the_caller():
    """미등록 이름은 규칙이 삼키지 않는다 — 호출부가 '준비 중' 안내를 따로 한다."""

    queue, note = drop_unrunnable(["nope"], [], {})
    assert queue == ["nope"]
    assert note == ""


# --- 합성 -------------------------------------------------------------------------
def test_continue_when_nothing_to_change():
    """규칙이 손댈 것이 없으면 continue — 관찰이 LLM 이던 때의 기본 동작 그대로."""

    session = {"resume": _RESUME, "analysis": _ANALYSIS}
    result = observe(["fit_analysis"], {"fit_analysis": AgentResult(data=_ANALYSIS)},
                     ["coverletter_draft"], ["fit_analysis"], session)
    assert result.action == "continue"
    assert result.queue == ("coverletter_draft",)
    assert result.note == ""
    assert result.rule == "none"


def test_empty_queue_finishes_and_says_why():
    """남은 예정이 없으면 finish — 궤적에 이유가 남는다(전에는 'skipped' 로 남았다)."""

    result = observe(["career_chat"], {"career_chat": AgentResult(reply="네")},
                     [], ["career_chat"], {})
    assert result.action == "finish"
    assert result.rule == "queue_empty"
    assert result.reason


def test_trace_fields_are_always_populated():
    """궤적 필드는 항상 채운다 — 이유 없는 관찰 기록은 쓸모없다(기존 규약 유지)."""

    for batch, outcomes, queue, session in (
        (["career_chat"], {"career_chat": AgentResult()}, [], {}),
        (["fit_analysis"], {"fit_analysis": AgentResult(data=_ANALYSIS)},
         ["coverletter_draft"], {"resume": _RESUME, "analysis": _ANALYSIS}),
        (["fit_analysis"], {"fit_analysis": AgentResult(data={"status": "failed"})},
         ["coverletter_draft"], {"resume": _RESUME}),
    ):
        result = observe(batch, outcomes, queue, list(batch), session)
        assert result.action in ("continue", "finish")
        assert result.reason, "이유가 비면 사후에 재선택을 설명할 수 없다"
        assert result.rule, "어느 규칙이 정했는지 남아야 한다"
