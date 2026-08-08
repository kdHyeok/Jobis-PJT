from __future__ import annotations

import pytest
from pydantic import ValidationError

from jobis_ai.career_pipeline.contracts.fit import (
    AssessmentBasis,
    ClaimState,
    EvidenceState,
    RequirementAssessment,
    RequirementStatus,
    UserCompetencyEvidence,
    VerificationState,
)


def test_claimed_skill_is_not_implicitly_verified() -> None:
    evidence = UserCompetencyEvidence(
        competency_id="lang.java",
        display_name="Java",
        scope_definition="Java language syntax and standard library",
        claim_state=ClaimState.CLAIMED,
        evidence_state=EvidenceState.NO_EVIDENCE,
        verification_state=VerificationState.NOT_VERIFIED,
        claimed_level=2,
        verified_level=0,
        confidence=0.7,
    )

    assert evidence.verification_state is VerificationState.NOT_VERIFIED


def test_evidenced_skill_requires_evidence_reference() -> None:
    with pytest.raises(ValidationError, match="evidenceRefs"):
        UserCompetencyEvidence(
            competency_id="lang.java",
            display_name="Java",
            scope_definition="Java language syntax and standard library",
            claim_state=ClaimState.CLAIMED,
            evidence_state=EvidenceState.EVIDENCED,
            verification_state=VerificationState.NOT_VERIFIED,
            claimed_level=2,
            verified_level=0,
            confidence=0.7,
        )


def test_unknown_requirement_is_excluded_from_denominator() -> None:
    assessment = RequirementAssessment(
        requirement_id="req-game-domain",
        status=RequirementStatus.UNKNOWN,
        required=True,
        included_in_denominator=False,
        basis=AssessmentBasis.NO_INFORMATION,
        posting_evidence_ids=["seg-domain"],
        reason="사용자 자료 없음",
        confidence=0.4,
    )

    assert assessment.included_in_denominator is False


def test_unknown_requirement_cannot_count_as_failure() -> None:
    with pytest.raises(ValidationError, match="excluded"):
        RequirementAssessment(
            requirement_id="req-game-domain",
            status=RequirementStatus.UNKNOWN,
            required=True,
            included_in_denominator=True,
            basis=AssessmentBasis.NO_INFORMATION,
            posting_evidence_ids=["seg-domain"],
            reason="사용자 자료 없음",
            confidence=0.4,
        )


def test_not_met_requires_explicit_negative_basis() -> None:
    with pytest.raises(ValidationError, match="explicit absence"):
        RequirementAssessment(
            requirement_id="req-kafka",
            status=RequirementStatus.NOT_MET,
            required=True,
            included_in_denominator=True,
            basis=AssessmentBasis.NO_INFORMATION,
            posting_evidence_ids=["seg-kafka"],
            reason="자료 없음",
            confidence=0.4,
        )
