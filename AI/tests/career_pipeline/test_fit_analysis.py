from __future__ import annotations

import copy
import json
from datetime import UTC, datetime

import pytest

from jobis_ai.career_pipeline.contracts.fit import (
    AssessmentBasis,
    ClaimState,
    EvidenceSourceType,
    EvidenceState,
    FitAnalysisRequest,
    FitAnalysisStatus,
    FormalFact,
    FormalFactKind,
    FormalFactState,
    RequirementSelfReport,
    RequirementStatus,
    UserCompetencyEvidence,
    UserEvidenceBundle,
    UserEvidenceItem,
    VerificationState,
    VerdictProposal,
)
from jobis_ai.career_pipeline.contracts.posting import StructuredPosting
from jobis_ai.career_pipeline.contracts.resolution import ExperienceTrack
from jobis_ai.career_pipeline.fit import FitAnalysisFailure, FitAnalysisService
from jobis_ai.career_pipeline.llm import StructuredGenerator


NOW = datetime(2026, 8, 4, 6, 0, tzinfo=UTC)


class StaticProvider:
    name = "scripted"
    model = "fit-fixture"

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    def complete_json(self, **_kwargs) -> str:
        self.calls += 1
        return json.dumps(self.payload, ensure_ascii=False)


def competency(
    *,
    claim: ClaimState = ClaimState.CLAIMED,
    evidence: EvidenceState = EvidenceState.NO_EVIDENCE,
    verification: VerificationState = VerificationState.NOT_VERIFIED,
    refs: list[str] | None = None,
    verified_level: int = 0,
) -> UserCompetencyEvidence:
    return UserCompetencyEvidence(
        competency_id="lang.java",
        display_name="Java",
        scope_definition="Java syntax, types, collections, and object-oriented programming",
        claim_state=claim,
        evidence_state=evidence,
        verification_state=verification,
        claimed_level=2 if claim is ClaimState.CLAIMED else None,
        verified_level=verified_level,
        evidence_refs=refs or [],
        confidence=0.9,
    )


def match_payload(
    *,
    requirement_id: str = "req-java",
    competency_id: str | None = None,
    fact_id: str | None = None,
    relation: str = "DIRECT",
) -> dict:
    return {
        "requirementMatches": [{
            "requirementId": requirement_id,
            "competencyCandidates": (
                [{"competencyId": competency_id, "relation": relation, "confidence": 0.95}]
                if competency_id else []
            ),
            "formalFactCandidates": (
                [{"factId": fact_id, "relation": relation, "confidence": 0.95}]
                if fact_id else []
            ),
            "confidence": 0.95,
            "reason": "The supplied capability scope directly covers the requirement.",
        }]
    }


def request_for(
    posting: StructuredPosting,
    payload: dict,
    *,
    competencies: list[UserCompetencyEvidence] | None = None,
    evidence_items: list[UserEvidenceItem] | None = None,
    formal_facts: list[FormalFact] | None = None,
    self_reports: list[RequirementSelfReport] | None = None,
    selected_track: ExperienceTrack | None = ExperienceTrack.NEW_GRADUATE,
    skip_questions: bool = True,
):
    provider = StaticProvider(payload)
    service = FitAnalysisService(StructuredGenerator(provider, max_attempts=1))
    request = FitAnalysisRequest(
        common_analysis_id="analysis-fit-1",
        structured_posting=posting,
        selected_position_id="pos-backend",
        selected_experience_track=selected_track,
        user_evidence=UserEvidenceBundle(
            evidence_set_id="evidence-set-1",
            revision=3,
            competencies=competencies or [],
            evidence_items=evidence_items or [],
            formal_facts=formal_facts or [],
            requirement_self_reports=self_reports or [],
        ),
        skip_remaining_evidence_questions=skip_questions,
    )
    return service, request, provider


def required_experience_posting(posting: StructuredPosting, months: int = 24) -> StructuredPosting:
    payload = copy.deepcopy(posting.model_dump(mode="json"))
    payload["positions"][0]["requirements"] = []
    payload["positions"][0]["experience"] = {
        "kind": "EXPERIENCE_REQUIRED",
        "min_months": months,
        "max_months": None,
        "experienced_min_months": None,
        "confidence": 0.99,
        "evidence_ids": ["seg-exp"],
    }
    return StructuredPosting.model_validate(payload)


def test_no_evidence_is_unknown_not_not_met(structured_posting) -> None:
    service, request, _provider = request_for(
        structured_posting,
        match_payload(),
    )

    result = service.analyze(request)
    assessment = result.assessment.requirement_assessments[0]

    assert result.status is FitAnalysisStatus.COMPLETED
    assert assessment.status is RequirementStatus.UNKNOWN
    assert assessment.basis is AssessmentBasis.NO_INFORMATION
    assert assessment.included_in_denominator is False
    assert result.assessment.metrics.required_known == 0
    assert result.assessment.metrics.capability_readiness_percent is None
    assert result.assessment.verdict_proposal is VerdictProposal.UNKNOWN


def test_claim_is_not_upgraded_to_evidenced_or_verified(structured_posting) -> None:
    service, request, _provider = request_for(
        structured_posting,
        match_payload(competency_id="lang.java"),
        competencies=[competency()],
    )

    result = service.analyze(request).assessment
    assessment = result.requirement_assessments[0]

    assert assessment.status is RequirementStatus.CLAIMED_ONLY
    assert assessment.user_evidence_refs == []
    assert result.metrics.capability_readiness_percent == 30.0


def test_evidence_and_verification_remain_distinct(structured_posting) -> None:
    evidence_item = UserEvidenceItem(
        evidence_id="ev-project-java",
        source_type=EvidenceSourceType.PROJECT,
        title="Order service",
        text="Implemented Java domain logic and collection processing.",
        verification_state=VerificationState.NOT_VERIFIED,
        confidence=0.9,
    )
    evidenced = competency(
        evidence=EvidenceState.EVIDENCED,
        refs=[evidence_item.evidence_id],
    )
    service, request, _provider = request_for(
        structured_posting,
        match_payload(competency_id="lang.java"),
        competencies=[evidenced],
        evidence_items=[evidence_item],
    )

    first_result = service.analyze(request).assessment
    first = first_result.requirement_assessments[0]
    assert first.status is RequirementStatus.EVIDENCED
    assert first_result.metrics.capability_readiness_percent == 70.0

    verified = evidenced.model_copy(update={
        "verification_state": VerificationState.VERIFIED,
        "verified_level": 2,
    })
    service, request, _provider = request_for(
        structured_posting,
        match_payload(competency_id="lang.java"),
        competencies=[verified],
        evidence_items=[evidence_item],
    )
    second_result = service.analyze(request).assessment
    second = second_result.requirement_assessments[0]
    assert second.status is RequirementStatus.VERIFIED_MET
    assert second_result.metrics.capability_readiness_percent == 100.0


def test_explicit_absence_is_required_before_not_met(structured_posting) -> None:
    report = RequirementSelfReport(
        requirement_id="req-java",
        claim_state=ClaimState.NOT_CLAIMED,
        answered_at=NOW,
    )
    service, request, _provider = request_for(
        structured_posting,
        match_payload(),
        self_reports=[report],
    )

    assessment = service.analyze(request).assessment.requirement_assessments[0]

    assert assessment.status is RequirementStatus.NOT_MET
    assert assessment.basis is AssessmentBasis.EXPLICIT_ABSENCE


def test_model_cannot_invent_user_evidence_ids(structured_posting) -> None:
    service, request, _provider = request_for(
        structured_posting,
        match_payload(competency_id="lang.fabricated"),
    )

    with pytest.raises(FitAnalysisFailure, match="unknown user evidence"):
        service.analyze(request)


def test_formal_evidence_question_is_stable_and_asked_one_at_a_time(structured_posting) -> None:
    posting = required_experience_posting(structured_posting)
    payload = match_payload(requirement_id="req-experience-pos-backend")
    service, request, _provider = request_for(
        posting,
        payload,
        selected_track=ExperienceTrack.EXPERIENCED,
        skip_questions=False,
    )

    first = service.analyze(request)
    second = service.analyze(request)

    assert first.status is FitAnalysisStatus.AWAITING_USER_EVIDENCE
    assert first.assessment is None
    assert first.active_ambiguity.type.value == "USER_EVIDENCE"
    assert first.active_ambiguity.ambiguity_id == second.active_ambiguity.ambiguity_id
    assert len(first.active_ambiguity.question.options) == 3


def test_answered_formal_evidence_question_resumes_without_asking_again(
    structured_posting,
) -> None:
    posting = required_experience_posting(structured_posting)
    report = RequirementSelfReport(
        requirement_id="req-experience-pos-backend",
        claim_state=ClaimState.NOT_CLAIMED,
        answered_at=NOW,
    )
    service, request, _provider = request_for(
        posting,
        match_payload(requirement_id="req-experience-pos-backend"),
        self_reports=[report],
        selected_track=ExperienceTrack.EXPERIENCED,
        skip_questions=False,
    )

    result = service.analyze(request)

    assert result.status is FitAnalysisStatus.COMPLETED
    assert result.assessment.requirement_assessments[0].status is RequirementStatus.NOT_MET


def test_verified_insufficient_experience_is_formal_failure(structured_posting) -> None:
    posting = required_experience_posting(structured_posting, 24)
    evidence_item = UserEvidenceItem(
        evidence_id="ev-employment",
        source_type=EvidenceSourceType.EMPLOYMENT,
        text="Backend engineer from 2026-01 through 2026-12.",
        verification_state=VerificationState.VERIFIED,
        confidence=1.0,
    )
    fact = FormalFact(
        fact_id="fact-backend-experience",
        kind=FormalFactKind.ROLE_EXPERIENCE,
        label="Backend engineering experience",
        state=FormalFactState.PRESENT,
        duration_months=12,
        evidence_refs=[evidence_item.evidence_id],
        verification_state=VerificationState.VERIFIED,
        confidence=1.0,
    )
    service, request, _provider = request_for(
        posting,
        match_payload(
            requirement_id="req-experience-pos-backend",
            fact_id=fact.fact_id,
        ),
        evidence_items=[evidence_item],
        formal_facts=[fact],
        selected_track=ExperienceTrack.EXPERIENCED,
    )

    fit = service.analyze(request).assessment
    assessment = fit.requirement_assessments[0]

    assert assessment.status is RequirementStatus.NOT_MET
    assert assessment.basis is AssessmentBasis.VERIFIED_INSUFFICIENCY
    assert fit.formal_eligibility is RequirementStatus.NOT_MET
    assert fit.verdict_proposal is VerdictProposal.ALTERNATIVE_PATH


def test_partial_semantic_relation_does_not_become_verified_met(structured_posting) -> None:
    evidence_item = UserEvidenceItem(
        evidence_id="ev-java",
        source_type=EvidenceSourceType.VERIFICATION_ANSWER,
        text="Passed Java language verification.",
        verification_state=VerificationState.VERIFIED,
        confidence=1.0,
    )
    record = competency(
        evidence=EvidenceState.EVIDENCED,
        verification=VerificationState.VERIFIED,
        refs=[evidence_item.evidence_id],
        verified_level=2,
    )
    service, request, _provider = request_for(
        structured_posting,
        match_payload(competency_id="lang.java", relation="PARTIAL"),
        competencies=[record],
        evidence_items=[evidence_item],
    )

    assessment = service.analyze(request).assessment.requirement_assessments[0]

    assert assessment.status is RequirementStatus.PARTIAL
    assert assessment.basis is AssessmentBasis.VERIFIED_PARTIAL
