"""역량 검증 — 무엇을 물을지는 **규칙**이 정하고, 문제와 채점만 LLM 이 한다.

§1 3계층이 그대로 적용된다:

  · **판단(결정론)** — 다음에 어느 종류를 물을지, 언제 끝낼지. 점수·개수로 정해지는 것이라
    LLM 이 추측할 이유가 없다. `next_question_kind` 가 그 자리다.
  · **읽기·말하기(LLM)** — 문제 출제와 답변 채점. 사람이 쓴 답을 읽고 판단해야 하므로
    `semantic_judge` 와 같은 성격의 예외다.

통과 규칙(백엔드 계약과 같은 값):
  · 핵심 세 종류(CONCEPT·CODE·SCENARIO)를 모두 60점 이상 → 그 다음 평균 75 이상이면 종료
  · 답변 5개를 채우면 종료 — 무한히 묻지 않는다
  · `requiredQuestionKind` 가 오면 그대로 따른다(백엔드가 재시험 종류를 지정하는 경로)

`ai-server/app/assessment_flow.py` 를 참고해 옮겼다(D132 — 가져오되 빚은 지지 않는다).
"""

from __future__ import annotations

from jobis_ai.v2bridge.models import (
    AssessmentAnswerEvaluation,
    AssessmentQuestion,
    CompetencyAssessmentRequest,
    CompetencyAssessmentResponse,
)

# 통과 판정에 쓰는 핵심 종류. FOLLOW_UP 은 보조라 여기 없다 —
# 꼬리 질문으로 통과를 대신할 수 없다.
CORE_KINDS: tuple[str, ...] = ("CONCEPT", "CODE", "SCENARIO")
MINIMUM_KIND_SCORE = 60
PASS_AVERAGE = 75
MAXIMUM_QUESTIONS = 5


def next_question_kind(
    request: CompetencyAssessmentRequest,
    evaluation: AssessmentAnswerEvaluation | None,
) -> str | None:
    """다음에 물을 종류. None 이면 **검증을 끝낸다.** 순수 함수 — LLM 없음."""

    if request.required_question_kind is not None:
        return request.required_question_kind

    # 종류별 최고점 — 한 번 통과한 영역을 다시 낮은 점수로 끌어내리지 않는다.
    scores = dict(request.retained_scores)
    for turn in request.turns:
        if turn.question_kind in CORE_KINDS and turn.score is not None:
            scores[turn.question_kind] = max(
                scores.get(turn.question_kind, 0), turn.score)
    if evaluation is not None and request.turns:
        kind = request.turns[-1].question_kind
        if kind in CORE_KINDS:
            scores[kind] = max(scores.get(kind, 0), evaluation.score)

    if sum(1 for turn in request.turns if turn.answer_text) >= MAXIMUM_QUESTIONS:
        return None
    for kind in CORE_KINDS:
        if scores.get(kind, 0) < MINIMUM_KIND_SCORE:
            return kind
    if sum(scores.get(kind, 0) for kind in CORE_KINDS) / len(CORE_KINDS) >= PASS_AVERAGE:
        return None
    # 셋 다 문턱은 넘었지만 평균이 모자라다 — 가장 약한 영역을 한 번 더.
    return min(CORE_KINDS, key=lambda kind: scores.get(kind, 0))


def assemble(
    evaluation: AssessmentAnswerEvaluation | None,
    next_question: AssessmentQuestion | None,
) -> CompetencyAssessmentResponse:
    """채점 + 다음 문제 → 응답. **새 판단을 만들지 않는다** — 있는 값을 옮겨 담는다."""

    if evaluation is None:
        return CompetencyAssessmentResponse(
            next_question=next_question,
            session_summary="핵심 통과 영역부터 차례로 확인합니다.",
        )
    return CompetencyAssessmentResponse(
        answer_evaluation=evaluation,
        next_question=next_question,
        session_summary=evaluation.feedback,
        strengths=list(evaluation.covered_criteria),
        gaps=list(evaluation.gaps),
        next_actions=(["피드백을 반영해 다음 변형 문제에 답해 보세요."]
                      if next_question is not None else []),
    )
