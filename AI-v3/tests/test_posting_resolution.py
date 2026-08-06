from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from jobis_ai_v3.contracts.posting import StructuredPosting
from jobis_ai_v3.contracts.resolution import (
    ClarificationAnswer,
    ExperienceTrack,
    PostingResolutionRequest,
    ResolutionStatus,
)
from jobis_ai_v3.resolution import AmbiguityResolutionFailure, PostingResolutionService


NOW = datetime(2026, 8, 4, 5, 0, tzinfo=UTC)


def multi_track_posting(structured_posting: StructuredPosting) -> StructuredPosting:
    payload = structured_posting.model_dump(mode="json")
    backend = payload["positions"][0]
    backend["requirements"] = []
    backend["experience"] = {
        "kind": "NEW_GRADUATE_OR_EXPERIENCED",
        "min_months": None,
        "max_months": None,
        "experienced_min_months": 36,
        "confidence": 0.98,
        "evidence_ids": ["seg-exp"],
    }
    frontend = copy.deepcopy(backend)
    frontend["position_id"] = "pos-frontend"
    frontend["source_title"] = "웹 프론트엔드 개발자"
    frontend["role"] = {
        "family": "SOFTWARE_ENGINEERING",
        "specialization": "WEB_FRONTEND",
        "canonical_role_id": "role.web_frontend",
        "status": "CANDIDATE",
        "confidence": 0.97,
        "evidence_ids": ["seg-title"],
    }
    frontend["experience"] = {
        "kind": "NEW_GRADUATE",
        "min_months": None,
        "max_months": None,
        "experienced_min_months": None,
        "confidence": 0.98,
        "evidence_ids": ["seg-exp"],
    }
    payload["positions"].append(frontend)
    return StructuredPosting.model_validate(payload)


def answer(ambiguity_id: str, value: str) -> ClarificationAnswer:
    return ClarificationAnswer(
        ambiguity_id=ambiguity_id,
        selected_value=value,
        answered_at=NOW,
    )


def test_single_position_is_ready_without_unnecessary_question(structured_posting) -> None:
    result = PostingResolutionService().resolve(PostingResolutionRequest(
        structured_posting=structured_posting,
    ))

    assert result.status is ResolutionStatus.READY_FOR_ANALYSIS
    assert result.selected_position_id == "pos-backend"
    assert result.selected_experience_track is ExperienceTrack.NEW_GRADUATE
    assert result.active_ambiguity is None


def test_multi_position_then_experience_track_are_asked_one_at_a_time(structured_posting) -> None:
    service = PostingResolutionService()
    posting = multi_track_posting(structured_posting)

    first = service.resolve(PostingResolutionRequest(structured_posting=posting))
    assert first.status is ResolutionStatus.AWAITING_ANSWER
    assert first.active_ambiguity.type.value == "POSITION_SELECTION"
    assert [option.value for option in first.active_ambiguity.question.options] == [
        "pos-backend", "pos-frontend"
    ]

    position_answer = answer(first.active_ambiguity.ambiguity_id, "pos-backend")
    second = service.resolve(PostingResolutionRequest(
        structured_posting=posting,
        answers=[position_answer],
    ))
    assert second.status is ResolutionStatus.AWAITING_ANSWER
    assert second.selected_position_id == "pos-backend"
    assert second.active_ambiguity.type.value == "EXPERIENCE_TRACK_SELECTION"

    track_answer = answer(second.active_ambiguity.ambiguity_id, "track-new-graduate")
    final = service.resolve(PostingResolutionRequest(
        structured_posting=posting,
        answers=[position_answer, track_answer],
    ))
    assert final.status is ResolutionStatus.READY_FOR_ANALYSIS
    assert final.selected_position_id == "pos-backend"
    assert final.selected_experience_track is ExperienceTrack.NEW_GRADUATE
    assert final.resolved_ambiguity_ids == [
        first.active_ambiguity.ambiguity_id,
        second.active_ambiguity.ambiguity_id,
    ]


def test_same_input_produces_same_question_id(structured_posting) -> None:
    service = PostingResolutionService()
    posting = multi_track_posting(structured_posting)

    first = service.resolve(PostingResolutionRequest(structured_posting=posting))
    repeated = service.resolve(PostingResolutionRequest(structured_posting=posting))

    assert first.active_ambiguity.ambiguity_id == repeated.active_ambiguity.ambiguity_id


def test_invalid_choice_is_not_silently_coerced(structured_posting) -> None:
    service = PostingResolutionService()
    posting = multi_track_posting(structured_posting)
    first = service.resolve(PostingResolutionRequest(structured_posting=posting))

    with pytest.raises(AmbiguityResolutionFailure, match="must select one"):
        service.resolve(PostingResolutionRequest(
            structured_posting=posting,
            answers=[answer(first.active_ambiguity.ambiguity_id, "pos-does-not-exist")],
        ))


def test_stale_answer_is_rejected(structured_posting) -> None:
    with pytest.raises(AmbiguityResolutionFailure, match="stale or unrelated"):
        PostingResolutionService().resolve(PostingResolutionRequest(
            structured_posting=structured_posting,
            answers=[answer("amb-old-question", "old-value")],
        ))


def test_duplicate_answer_for_same_ambiguity_is_rejected(structured_posting) -> None:
    item = answer("amb-position-123", "pos-backend")

    with pytest.raises(ValidationError, match="duplicate ambiguity answer"):
        PostingResolutionRequest(
            structured_posting=structured_posting,
            answers=[item, item],
        )
