from app.models import (
    AssessmentAnswerEvaluation,
    CompetencyAssessmentRequest,
    CompetencyAssessmentResponse,
)

CORE_KINDS = ("CONCEPT", "CODE", "SCENARIO")
MINIMUM_KIND_SCORE = 60
PASS_AVERAGE = 75
MAXIMUM_QUESTIONS = 5


def next_question_kind(
    request: CompetencyAssessmentRequest,
    evaluation: AssessmentAnswerEvaluation | None,
) -> str | None:
    if request.required_question_kind is not None:
        return request.required_question_kind

    scores = dict(request.retained_scores)
    for turn in request.turns:
        if turn.question_kind in CORE_KINDS and turn.score is not None:
            scores[turn.question_kind] = max(
                scores.get(turn.question_kind, 0),
                turn.score,
            )
    if evaluation is not None and request.turns:
        kind = request.turns[-1].question_kind
        if kind in CORE_KINDS:
            scores[kind] = max(scores.get(kind, 0), evaluation.score)

    answered = sum(1 for turn in request.turns if turn.answer_text)
    if answered >= MAXIMUM_QUESTIONS:
        return None
    for kind in CORE_KINDS:
        if scores.get(kind, 0) < MINIMUM_KIND_SCORE:
            return kind
    average = sum(scores.get(kind, 0) for kind in CORE_KINDS) / len(CORE_KINDS)
    if average >= PASS_AVERAGE:
        return None
    return min(CORE_KINDS, key=lambda kind: scores.get(kind, 0))


def assemble_assessment_response(
    evaluation: AssessmentAnswerEvaluation | None,
    next_question,
) -> CompetencyAssessmentResponse:
    if evaluation is None:
        return CompetencyAssessmentResponse(
            answer_evaluation=None,
            next_question=next_question,
            session_summary="핵심 통과 영역부터 차례로 확인합니다.",
            strengths=[],
            gaps=[],
            next_actions=[],
        )
    return CompetencyAssessmentResponse(
        answer_evaluation=evaluation,
        next_question=next_question,
        session_summary=evaluation.feedback,
        strengths=evaluation.covered_criteria,
        gaps=evaluation.gaps,
        next_actions=(
            ["피드백을 반영해 다음 변형 문제에 답해 보세요."]
            if next_question is not None
            else []
        ),
    )
