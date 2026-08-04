"""역량 검증 — **무엇을 물을지·언제 끝낼지는 규칙이 정한다** (`v2bridge/assessment.py`).

이 화면은 사용자의 역량을 "통과"로 확정한다. 그 판단이 LLM 재량이면 같은 사람이 같은 답을
써도 결과가 흔들린다. 그래서 종료·재출제 규칙은 결정론이고(§1 판단 계층), LLM 은 문제를
만들고 답을 읽기만 한다.

여기서 검사하는 것: 규칙이 통과·종료를 정확히 세는가, 그리고 LLM 이 규칙을 덮지 못하는가.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jobis_ai.v2bridge import assessment, service
from jobis_ai.v2bridge.models import (
    AssessmentAnswerEvaluation,
    AssessmentQuestion,
    CompetencyAssessmentRequest,
    CompetencyAssessmentResponse,
)

_COMPETENCY = {
    "canonicalKey": "skill.java", "title": "Java", "domain": "BACKEND",
    "scopeDefinition": "서비스 코드를 작성하고 동시성 이슈를 설명할 수 있다.",
    "requiredLevel": 3,
}


def _request(turns=None, retained=None, **over) -> CompetencyAssessmentRequest:
    return CompetencyAssessmentRequest(**{
        "sessionId": "11111111-1111-1111-1111-111111111111",
        "competency": _COMPETENCY,
        "turns": turns or [],
        "retainedScores": retained or {},
        **over,
    })


def _turn(ordinal: int, kind: str, score: int | None, answered: bool = True) -> dict:
    return {"ordinal": ordinal, "questionKind": kind, "prompt": f"{kind} 문제",
            "answerText": "제 답변입니다." if answered else None, "score": score}


def _evaluation(score: int, verdict: str = "PASS") -> AssessmentAnswerEvaluation:
    return AssessmentAnswerEvaluation(score=score, verdict=verdict, feedback="확인했습니다.")


# --- 규칙: 무엇을 물을까 -----------------------------------------------------------
def test_starts_with_the_first_uncovered_core_kind():
    assert assessment.next_question_kind(_request(), None) == "CONCEPT"


def test_moves_to_the_next_kind_once_one_passes():
    got = assessment.next_question_kind(
        _request([_turn(1, "CONCEPT", 80)]), _evaluation(80))
    assert got == "CODE"


def test_a_weak_score_repeats_the_same_kind():
    """60 미만은 통과가 아니다 — 다음 종류로 넘어가지 않는다."""

    got = assessment.next_question_kind(
        _request([_turn(1, "CONCEPT", 40)]), _evaluation(40))
    assert got == "CONCEPT"


def test_retained_scores_count_as_already_passed():
    """이전 세션에서 통과한 영역을 다시 묻지 않는다."""

    got = assessment.next_question_kind(
        _request(retained={"CONCEPT": 90, "CODE": 80}), None)
    assert got == "SCENARIO"


def test_highest_score_per_kind_wins():
    """한 번 통과한 영역을 나중 낮은 점수가 끌어내리지 않는다."""

    turns = [_turn(1, "CONCEPT", 90), _turn(2, "CONCEPT", 30)]
    assert assessment.next_question_kind(_request(turns), _evaluation(30)) == "CODE"


# --- 규칙: 언제 끝낼까 -------------------------------------------------------------
def test_finishes_when_all_core_kinds_pass_the_average():
    turns = [_turn(1, "CONCEPT", 80), _turn(2, "CODE", 75), _turn(3, "SCENARIO", 80)]
    assert assessment.next_question_kind(_request(turns), _evaluation(80)) is None


def test_asks_the_weakest_kind_again_when_the_average_falls_short():
    """셋 다 문턱은 넘었지만 평균이 모자라다 — 가장 약한 영역을 한 번 더."""

    turns = [_turn(1, "CONCEPT", 65), _turn(2, "CODE", 62), _turn(3, "SCENARIO", 70)]
    assert assessment.next_question_kind(_request(turns), _evaluation(70)) == "CODE"


def test_stops_after_five_answers_even_if_weak():
    """무한히 묻지 않는다 — 답변 5개면 끝낸다."""

    turns = [_turn(i, "CONCEPT", 10) for i in range(1, 6)]
    assert assessment.next_question_kind(_request(turns), _evaluation(10)) is None


def test_unanswered_turns_do_not_count_toward_the_cap():
    turns = [_turn(i, "CONCEPT", None, answered=False) for i in range(1, 7)]
    assert assessment.next_question_kind(_request(turns), None) == "CONCEPT"


def test_backend_can_pin_the_kind():
    """백엔드가 재시험 종류를 지정하면 규칙보다 우선한다."""

    turns = [_turn(1, "CONCEPT", 90), _turn(2, "CODE", 90), _turn(3, "SCENARIO", 90)]
    got = assessment.next_question_kind(
        _request(turns, requiredQuestionKind="FOLLOW_UP"), _evaluation(90))
    assert got == "FOLLOW_UP"


# --- 조립 ---------------------------------------------------------------------
def test_assemble_carries_the_evaluation_into_the_summary():
    question = AssessmentQuestion(kind="CODE", prompt="이 코드의 문제는?")
    got = assessment.assemble(_evaluation(80), question)
    assert got.session_summary == "확인했습니다."
    assert got.next_actions, "다음 문제가 있으면 무엇을 할지 알려준다"

    done = assessment.assemble(_evaluation(80), None)
    assert done.next_actions == [], "끝났으면 다음 행동을 지어내지 않는다"


def test_response_without_evaluation_or_question_is_rejected():
    """둘 다 없으면 이 응답으로 화면이 할 수 있는 일이 없다."""

    with pytest.raises(ValidationError):
        CompetencyAssessmentResponse(session_summary="…")


# --- LLM 이 규칙을 덮지 못한다 -------------------------------------------------------
def test_model_cannot_change_the_question_kind(monkeypatch):
    """규칙이 CONCEPT 를 요구했는데 모델이 CODE 를 내면 규칙을 따른다(§1 판단 계층 보호)."""

    def fake(schema, system, content, **kw):
        if schema is AssessmentQuestion:
            return AssessmentQuestion(kind="CODE", prompt="엉뚱한 종류"), []
        return None, []

    monkeypatch.setattr("jobis_ai.structured.run_structured", fake)
    got = service.assess_competency(_request())
    assert got.next_question is not None
    assert got.next_question.kind == "CONCEPT"


def test_grading_failure_is_not_invented(monkeypatch):
    """채점을 지어내면 사용자의 역량이 근거 없이 확정된다 — 실패로 올린다."""

    monkeypatch.setattr("jobis_ai.structured.run_structured",
                        lambda *a, **kw: (None, []))
    with pytest.raises(service.EngineFailed):
        service.assess_competency(_request([_turn(1, "CONCEPT", None)]))
