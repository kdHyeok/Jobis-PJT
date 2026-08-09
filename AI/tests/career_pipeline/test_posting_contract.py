from __future__ import annotations

import pytest
from pydantic import ValidationError

from jobis_ai.career_pipeline.contracts.posting import (
    Ambiguity,
    AmbiguityType,
    ClarificationQuestion,
    ExperienceKind,
    ExperienceRequirement,
    QuestionInputType,
    QuestionOption,
    RoleCandidate,
    RoleStatus,
    StructuredPosting,
)


def test_known_role_requires_canonical_id() -> None:
    with pytest.raises(ValidationError, match="canonicalRoleId"):
        RoleCandidate(
            family="SOFTWARE_ENGINEERING",
            specialization="WEB_BACKEND",
            status=RoleStatus.CANDIDATE,
            confidence=0.9,
            evidence_ids=["seg-role"],
        )


def test_new_role_candidate_must_not_have_existing_id() -> None:
    with pytest.raises(ValidationError, match="cannot already have"):
        RoleCandidate(
            family="EMERGING",
            specialization="CHARACTER_AI",
            canonical_role_id="role.web_backend",
            status=RoleStatus.NEW_CANDIDATE,
            confidence=0.7,
            evidence_ids=["seg-role"],
        )


@pytest.mark.parametrize(
    ("kind", "kwargs", "message"),
    [
        (ExperienceKind.EXPERIENCE_REQUIRED, {}, "positive minMonths"),
        (ExperienceKind.RANGE, {"min_months": 12}, "requires minMonths and maxMonths"),
        (ExperienceKind.NEW_GRADUATE, {"min_months": 12}, "cannot carry a numeric range"),
    ],
)
def test_experience_kind_controls_numeric_fields(kind: ExperienceKind, kwargs: dict, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        ExperienceRequirement(
            kind=kind,
            confidence=0.9,
            evidence_ids=["seg-exp"],
            **kwargs,
        )


def test_min_months_cannot_exceed_max_months() -> None:
    with pytest.raises(ValidationError, match="cannot be greater"):
        ExperienceRequirement(
            kind=ExperienceKind.RANGE,
            min_months=36,
            max_months=12,
            confidence=0.9,
            evidence_ids=["seg-exp"],
        )


def test_new_graduate_or_experienced_allows_unspecified_minimum() -> None:
    requirement = ExperienceRequirement(
        kind=ExperienceKind.NEW_GRADUATE_OR_EXPERIENCED,
        confidence=0.9,
        evidence_ids=["seg-exp"],
    )

    assert requirement.experienced_min_months is None


def test_new_graduate_or_experienced_preserves_explicit_minimum() -> None:
    requirement = ExperienceRequirement(
        kind=ExperienceKind.NEW_GRADUATE_OR_EXPERIENCED,
        experienced_min_months=36,
        confidence=0.9,
        evidence_ids=["seg-exp"],
    )

    assert requirement.experienced_min_months == 36


def test_choice_question_requires_two_options() -> None:
    with pytest.raises(ValidationError, match="at least two"):
        ClarificationQuestion(
            input_type=QuestionInputType.CHOICE,
            text="직무를 선택하세요",
            options=[QuestionOption(value="pos-backend", label="백엔드")],
        )


def test_position_selection_references_existing_positions(structured_posting: StructuredPosting) -> None:
    payload = structured_posting.model_dump()
    payload["ambiguities"] = [
        Ambiguity(
            ambiguity_id="amb-position",
            type=AmbiguityType.POSITION_SELECTION,
            blocking=True,
            reason="두 직무",
            candidate_ids=["pos-backend", "pos-missing"],
            evidence_ids=["seg-role"],
            question=ClarificationQuestion(
                input_type=QuestionInputType.CHOICE,
                text="직무를 선택하세요",
                options=[
                    QuestionOption(value="pos-backend", label="백엔드"),
                    QuestionOption(value="pos-missing", label="다른 직무"),
                ],
            ),
        ).model_dump()
    ]

    with pytest.raises(ValidationError, match="unknown positions"):
        StructuredPosting.model_validate(payload)
