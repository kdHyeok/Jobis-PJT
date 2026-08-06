from __future__ import annotations

import hashlib

from jobis_ai_v3.contracts.errors import ErrorCode
from jobis_ai_v3.contracts.posting import (
    Ambiguity,
    AmbiguityType,
    ClarificationQuestion,
    ExperienceKind,
    QuestionInputType,
    QuestionOption,
)
from jobis_ai_v3.contracts.resolution import (
    ExperienceTrack,
    PostingResolutionRequest,
    PostingResolutionResult,
    ResolutionStatus,
)


class AmbiguityResolutionFailure(RuntimeError):
    def __init__(self, *, code: ErrorCode, message: str, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(message)


class PostingResolutionService:
    def resolve(self, request: PostingResolutionRequest) -> PostingResolutionResult:
        posting = request.structured_posting
        answers = {answer.ambiguity_id: answer for answer in request.answers}
        known_answer_ids: set[str] = set()
        resolved_ids: list[str] = []
        ambiguities: list[Ambiguity] = []

        selected_position_id: str | None = None
        if len(posting.positions) == 1:
            selected_position_id = posting.positions[0].position_id
        else:
            ambiguity = _position_selection(posting)
            ambiguities.append(ambiguity)
            known_answer_ids.add(ambiguity.ambiguity_id)
            answer = answers.get(ambiguity.ambiguity_id)
            if answer is None:
                _reject_stale_answers(answers, known_answer_ids)
                return _waiting(posting, ambiguities, ambiguity, resolved_ids)
            selected_position_id = _selected_choice(answer.selected_value, ambiguity)
            resolved_ids.append(ambiguity.ambiguity_id)

        selected = next(
            position for position in posting.positions if position.position_id == selected_position_id
        )
        selected_track: ExperienceTrack | None = None
        if selected.experience.kind is ExperienceKind.NEW_GRADUATE:
            selected_track = ExperienceTrack.NEW_GRADUATE
        elif selected.experience.kind in {ExperienceKind.EXPERIENCE_REQUIRED, ExperienceKind.RANGE}:
            selected_track = ExperienceTrack.EXPERIENCED
        elif selected.experience.kind is ExperienceKind.NEW_GRADUATE_OR_EXPERIENCED:
            ambiguity = _experience_track_selection(posting.verified_snapshot_id, selected)
            ambiguities.append(ambiguity)
            known_answer_ids.add(ambiguity.ambiguity_id)
            answer = answers.get(ambiguity.ambiguity_id)
            if answer is None:
                _reject_stale_answers(answers, known_answer_ids)
                return _waiting(
                    posting,
                    ambiguities,
                    ambiguity,
                    resolved_ids,
                    selected_position_id=selected_position_id,
                )
            selected_value = _selected_choice(answer.selected_value, ambiguity)
            selected_track = (
                ExperienceTrack.NEW_GRADUATE
                if selected_value == "track-new-graduate"
                else ExperienceTrack.EXPERIENCED
            )
            resolved_ids.append(ambiguity.ambiguity_id)

        _reject_stale_answers(answers, known_answer_ids)
        resolved_posting = posting.model_copy(update={"ambiguities": ambiguities})
        return PostingResolutionResult(
            structured_posting=resolved_posting,
            status=ResolutionStatus.READY_FOR_ANALYSIS,
            selected_position_id=selected_position_id,
            selected_experience_track=selected_track,
            active_ambiguity=None,
            resolved_ambiguity_ids=resolved_ids,
        )


def _position_selection(posting) -> Ambiguity:
    candidate_ids = [position.position_id for position in posting.positions]
    evidence_ids = list(dict.fromkeys(
        evidence_id
        for position in posting.positions
        for evidence_id in position.role.evidence_ids
    ))
    ambiguity_id = _stable_id(
        "position",
        posting.verified_snapshot_id,
        *candidate_ids,
    )
    return Ambiguity(
        ambiguity_id=ambiguity_id,
        type=AmbiguityType.POSITION_SELECTION,
        blocking=True,
        reason="서로 다른 모집 포지션이 둘 이상이라 선택에 따라 경력과 요건이 달라집니다.",
        candidate_ids=candidate_ids,
        evidence_ids=evidence_ids,
        question=ClarificationQuestion(
            input_type=QuestionInputType.CHOICE,
            text="어느 직무 기준으로 준비도를 분석할까요?",
            options=[
                QuestionOption(value=position.position_id, label=position.source_title)
                for position in posting.positions
            ],
        ),
    )


def _experience_track_selection(snapshot_id: str, position) -> Ambiguity:
    ambiguity_id = _stable_id("experience-track", snapshot_id, position.position_id)
    months = position.experience.experienced_min_months
    experienced_label = f"경력 {months // 12}년 이상 기준" if months and months % 12 == 0 else (
        f"경력 {months}개월 이상 기준" if months else "경력 기준"
    )
    return Ambiguity(
        ambiguity_id=ambiguity_id,
        type=AmbiguityType.EXPERIENCE_TRACK_SELECTION,
        blocking=True,
        reason="같은 포지션이 신입과 경력 지원자를 함께 모집해 분석 기준을 선택해야 합니다.",
        candidate_ids=["track-new-graduate", "track-experienced"],
        evidence_ids=position.experience.evidence_ids,
        question=ClarificationQuestion(
            input_type=QuestionInputType.CHOICE,
            text=f"{position.source_title} 공고를 어느 경력 트랙 기준으로 분석할까요?",
            options=[
                QuestionOption(value="track-new-graduate", label="신입 기준"),
                QuestionOption(value="track-experienced", label=experienced_label),
            ],
        ),
    )


def _selected_choice(selected_value: str | None, ambiguity: Ambiguity) -> str:
    allowed = {option.value for option in ambiguity.question.options} if ambiguity.question else set()
    if selected_value is None or selected_value not in allowed:
        raise AmbiguityResolutionFailure(
            code=ErrorCode.AMBIGUITY_UNRESOLVED,
            message=f"answer for {ambiguity.ambiguity_id} must select one of {sorted(allowed)}",
        )
    return selected_value


def _reject_stale_answers(answers: dict, known_ids: set[str]) -> None:
    stale = sorted(set(answers) - known_ids)
    if stale:
        raise AmbiguityResolutionFailure(
            code=ErrorCode.ANALYSIS_STALE_RESULT,
            message=f"answers refer to stale or unrelated ambiguities: {stale}",
        )


def _waiting(
    posting,
    ambiguities,
    active,
    resolved_ids,
    *,
    selected_position_id: str | None = None,
) -> PostingResolutionResult:
    return PostingResolutionResult(
        structured_posting=posting.model_copy(update={"ambiguities": ambiguities}),
        status=ResolutionStatus.AWAITING_ANSWER,
        selected_position_id=selected_position_id,
        selected_experience_track=None,
        active_ambiguity=active,
        resolved_ambiguity_ids=resolved_ids,
    )


def _stable_id(kind: str, *parts: str) -> str:
    digest = hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]
    return f"amb-{kind}-{digest}"
