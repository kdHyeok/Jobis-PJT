from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import CanonicalKey, ContractModel, EntityId, NonBlank, WarningItem, ensure_unique
from .posting import Ambiguity, ExperienceKind, StructuredPosting
from .resolution import ExperienceTrack
from .source import Confidence


class ClaimState(StrEnum):
    CLAIMED = "CLAIMED"
    NOT_CLAIMED = "NOT_CLAIMED"
    UNKNOWN = "UNKNOWN"


class EvidenceState(StrEnum):
    EVIDENCED = "EVIDENCED"
    NO_EVIDENCE = "NO_EVIDENCE"
    UNKNOWN = "UNKNOWN"


class VerificationState(StrEnum):
    VERIFIED = "VERIFIED"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    NOT_VERIFIED = "NOT_VERIFIED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class EvidenceSourceType(StrEnum):
    CAREER_FRAGMENT = "CAREER_FRAGMENT"
    RESUME = "RESUME"
    PROJECT = "PROJECT"
    CODE_REPOSITORY = "CODE_REPOSITORY"
    VERIFICATION_ANSWER = "VERIFICATION_ANSWER"
    CERTIFICATE = "CERTIFICATE"
    EMPLOYMENT = "EMPLOYMENT"
    EDUCATION = "EDUCATION"
    PORTFOLIO = "PORTFOLIO"
    OTHER = "OTHER"


class FormalFactKind(StrEnum):
    ROLE_EXPERIENCE = "ROLE_EXPERIENCE"
    CERTIFICATE = "CERTIFICATE"
    EDUCATION = "EDUCATION"
    WORK_AUTHORIZATION = "WORK_AUTHORIZATION"
    PORTFOLIO = "PORTFOLIO"
    OTHER = "OTHER"


class FormalFactState(StrEnum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    UNKNOWN = "UNKNOWN"


class RequirementStatus(StrEnum):
    VERIFIED_MET = "VERIFIED_MET"
    EVIDENCED = "EVIDENCED"
    CLAIMED_ONLY = "CLAIMED_ONLY"
    PARTIAL = "PARTIAL"
    NOT_MET = "NOT_MET"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AssessmentBasis(StrEnum):
    VERIFIED_COMPETENCY = "VERIFIED_COMPETENCY"
    VERIFIED_FORMAL_FACT = "VERIFIED_FORMAL_FACT"
    VERIFIED_PARTIAL = "VERIFIED_PARTIAL"
    CAREER_EVIDENCE = "CAREER_EVIDENCE"
    USER_CLAIM = "USER_CLAIM"
    EXPLICIT_ABSENCE = "EXPLICIT_ABSENCE"
    VERIFIED_INSUFFICIENCY = "VERIFIED_INSUFFICIENCY"
    NO_INFORMATION = "NO_INFORMATION"
    POLICY_NOT_APPLICABLE = "POLICY_NOT_APPLICABLE"


class VerdictProposal(StrEnum):
    APPLY_NOW = "APPLY_NOW"
    STRENGTHEN_THEN_APPLY = "STRENGTHEN_THEN_APPLY"
    ALTERNATIVE_PATH = "ALTERNATIVE_PATH"
    UNKNOWN = "UNKNOWN"


class FitAnalysisStatus(StrEnum):
    AWAITING_USER_EVIDENCE = "AWAITING_USER_EVIDENCE"
    COMPLETED = "COMPLETED"


class UserEvidenceItem(ContractModel):
    evidence_id: EntityId
    source_type: EvidenceSourceType
    source_ref: EntityId | None = None
    title: NonBlank | None = None
    text: NonBlank
    verification_state: VerificationState = VerificationState.NOT_VERIFIED
    confidence: Confidence


class UserCompetencyEvidence(ContractModel):
    """A user-scoped competency state supplied by Spring.

    This object deliberately keeps a claim, supporting evidence, and a passed
    verification as three independent dimensions. The AI service never upgrades
    one dimension merely because another is present.
    """

    competency_id: CanonicalKey
    display_name: NonBlank
    scope_definition: NonBlank
    claim_state: ClaimState
    evidence_state: EvidenceState
    verification_state: VerificationState
    claimed_level: int | None = Field(default=None, ge=1, le=5)
    verified_level: int = Field(default=0, ge=0, le=5)
    evidence_refs: list[EntityId] = Field(default_factory=list)
    confidence: Confidence

    @model_validator(mode="after")
    def validate_states(self) -> "UserCompetencyEvidence":
        if self.claim_state is ClaimState.CLAIMED and self.claimed_level is None:
            raise ValueError("CLAIMED competencies require claimedLevel")
        if self.claim_state is not ClaimState.CLAIMED and self.claimed_level is not None:
            raise ValueError("only CLAIMED competencies may carry claimedLevel")
        if self.evidence_state is EvidenceState.EVIDENCED and not self.evidence_refs:
            raise ValueError("EVIDENCED competencies require evidenceRefs")
        if self.evidence_state is EvidenceState.NO_EVIDENCE and self.evidence_refs:
            raise ValueError("NO_EVIDENCE competencies cannot carry evidenceRefs")
        if self.verification_state in {
            VerificationState.VERIFIED,
            VerificationState.PARTIALLY_VERIFIED,
        }:
            if self.verified_level == 0:
                raise ValueError("verified competencies require a positive verifiedLevel")
            if self.evidence_state is not EvidenceState.EVIDENCED:
                raise ValueError("verified competencies must also be EVIDENCED")
        elif self.verified_level != 0:
            raise ValueError("unverified competencies require verifiedLevel=0")
        return self


class FormalFact(ContractModel):
    fact_id: EntityId
    kind: FormalFactKind
    label: NonBlank
    state: FormalFactState
    duration_months: int | None = Field(default=None, ge=0)
    evidence_refs: list[EntityId] = Field(default_factory=list)
    verification_state: VerificationState = VerificationState.NOT_VERIFIED
    confidence: Confidence

    @model_validator(mode="after")
    def validate_fact(self) -> "FormalFact":
        if self.duration_months is not None and self.kind is not FormalFactKind.ROLE_EXPERIENCE:
            raise ValueError("durationMonths is only valid for ROLE_EXPERIENCE")
        if self.state is not FormalFactState.PRESENT and self.duration_months is not None:
            raise ValueError("only PRESENT facts may carry durationMonths")
        if self.verification_state in {
            VerificationState.VERIFIED,
            VerificationState.PARTIALLY_VERIFIED,
        } and not self.evidence_refs:
            raise ValueError("verified formal facts require evidenceRefs")
        return self


class RequirementSelfReport(ContractModel):
    requirement_id: EntityId
    claim_state: ClaimState
    answered_at: datetime
    evidence_refs: list[EntityId] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_self_report(self) -> "RequirementSelfReport":
        if self.claim_state is ClaimState.NOT_CLAIMED and self.evidence_refs:
            raise ValueError("NOT_CLAIMED self reports cannot carry evidenceRefs")
        return self


class UserEvidenceBundle(ContractModel):
    evidence_set_id: EntityId
    revision: int = Field(ge=0)
    competencies: list[UserCompetencyEvidence] = Field(default_factory=list)
    evidence_items: list[UserEvidenceItem] = Field(default_factory=list)
    formal_facts: list[FormalFact] = Field(default_factory=list)
    requirement_self_reports: list[RequirementSelfReport] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self) -> "UserEvidenceBundle":
        ensure_unique([item.competency_id for item in self.competencies], "competencyId")
        ensure_unique([item.evidence_id for item in self.evidence_items], "user evidenceId")
        ensure_unique([item.fact_id for item in self.formal_facts], "formal factId")
        ensure_unique(
            [item.requirement_id for item in self.requirement_self_reports],
            "requirement self report",
        )
        known_evidence = {item.evidence_id for item in self.evidence_items}
        referenced = {
            evidence_id
            for competency in self.competencies
            for evidence_id in competency.evidence_refs
        } | {
            evidence_id
            for fact in self.formal_facts
            for evidence_id in fact.evidence_refs
        } | {
            evidence_id
            for report in self.requirement_self_reports
            for evidence_id in report.evidence_refs
        }
        missing = referenced - known_evidence
        if missing:
            raise ValueError(f"user evidence references are missing from evidenceItems: {sorted(missing)}")
        return self


class FitAnalysisRequest(ContractModel):
    common_analysis_id: EntityId
    structured_posting: StructuredPosting
    selected_position_id: EntityId
    selected_experience_track: ExperienceTrack | None = None
    user_evidence: UserEvidenceBundle
    skip_remaining_evidence_questions: bool = False

    @model_validator(mode="after")
    def validate_selection(self) -> "FitAnalysisRequest":
        selected = [
            position
            for position in self.structured_posting.positions
            if position.position_id == self.selected_position_id
        ]
        if not selected:
            raise ValueError("selectedPositionId does not exist in structuredPosting")
        experience_kind = selected[0].experience.kind
        if experience_kind is ExperienceKind.NEW_GRADUATE:
            if self.selected_experience_track not in {None, ExperienceTrack.NEW_GRADUATE}:
                raise ValueError("a NEW_GRADUATE position cannot use the experienced track")
        elif experience_kind in {ExperienceKind.EXPERIENCE_REQUIRED, ExperienceKind.RANGE}:
            if self.selected_experience_track not in {None, ExperienceTrack.EXPERIENCED}:
                raise ValueError("an experienced position cannot use the new-graduate track")
        elif experience_kind is ExperienceKind.NEW_GRADUATE_OR_EXPERIENCED:
            if self.selected_experience_track is None:
                raise ValueError("NEW_GRADUATE_OR_EXPERIENCED requires selectedExperienceTrack")
        return self


class RequirementAssessment(ContractModel):
    requirement_id: EntityId
    status: RequirementStatus
    required: bool
    included_in_denominator: bool
    basis: AssessmentBasis
    matched_competencies: list[CanonicalKey] = Field(default_factory=list)
    matched_formal_facts: list[EntityId] = Field(default_factory=list)
    user_evidence_refs: list[EntityId] = Field(default_factory=list)
    posting_evidence_ids: list[EntityId] = Field(min_length=1)
    reason: NonBlank
    confidence: Confidence

    @model_validator(mode="after")
    def validate_status(self) -> "RequirementAssessment":
        if self.status is RequirementStatus.UNKNOWN:
            if self.included_in_denominator:
                raise ValueError("UNKNOWN requirements must be excluded from the denominator")
            if self.basis is not AssessmentBasis.NO_INFORMATION:
                raise ValueError("UNKNOWN requirements require NO_INFORMATION basis")
        if self.status is RequirementStatus.NOT_APPLICABLE:
            if self.included_in_denominator:
                raise ValueError("NOT_APPLICABLE requirements must be excluded from the denominator")
            if self.basis is not AssessmentBasis.POLICY_NOT_APPLICABLE:
                raise ValueError("NOT_APPLICABLE requires POLICY_NOT_APPLICABLE basis")
        if self.status is RequirementStatus.NOT_MET and self.basis not in {
            AssessmentBasis.EXPLICIT_ABSENCE,
            AssessmentBasis.VERIFIED_INSUFFICIENCY,
        }:
            raise ValueError("NOT_MET requires explicit absence or verified insufficiency")
        if self.status is RequirementStatus.VERIFIED_MET and self.basis not in {
            AssessmentBasis.VERIFIED_COMPETENCY,
            AssessmentBasis.VERIFIED_FORMAL_FACT,
        }:
            raise ValueError("VERIFIED_MET requires a verified basis")
        return self


class FitMetrics(ContractModel):
    required_total: int = Field(ge=0)
    required_known: int = Field(ge=0)
    required_verified_met: int = Field(ge=0)
    preferred_total: int = Field(ge=0)
    claimed_readiness_percent: Annotated[float, Field(ge=0, le=100)] | None = None
    evidenced_readiness_percent: Annotated[float, Field(ge=0, le=100)] | None = None
    verified_readiness_percent: Annotated[float, Field(ge=0, le=100)] | None = None
    capability_readiness_percent: Annotated[float, Field(ge=0, le=100)] | None = None
    readiness_unavailable_reason: Literal[
        "NO_REQUIRED_REQUIREMENTS",
        "REQUIRED_EVIDENCE_UNKNOWN",
    ] | None = None

    @model_validator(mode="after")
    def validate_counts(self) -> "FitMetrics":
        if self.required_known > self.required_total:
            raise ValueError("requiredKnown cannot exceed requiredTotal")
        if self.required_verified_met > self.required_known:
            raise ValueError("requiredVerifiedMet cannot exceed requiredKnown")
        expected_reason = (
            "NO_REQUIRED_REQUIREMENTS"
            if self.required_total == 0
            else "REQUIRED_EVIDENCE_UNKNOWN"
            if self.required_known == 0
            else None
        )
        if self.readiness_unavailable_reason != expected_reason:
            raise ValueError(
                "readinessUnavailableReason must explain an unavailable denominator"
            )
        readiness_values = (
            self.claimed_readiness_percent,
            self.evidenced_readiness_percent,
            self.verified_readiness_percent,
            self.capability_readiness_percent,
        )
        if expected_reason is not None and any(value is not None for value in readiness_values):
            raise ValueError("readiness values must be unavailable without a denominator")
        if expected_reason is None and any(
            value is None for value in readiness_values[:3]
        ):
            raise ValueError("the three readiness axes require an available denominator")
        return self


class FitAudit(ContractModel):
    matcher_version: NonBlank
    policy_version: NonBlank
    provider: NonBlank
    model: NonBlank
    generation_attempts: int = Field(ge=1)
    generation_duration_ms: int = Field(ge=0)
    evaluated_requirement_ids: list[EntityId]
    used_user_evidence_refs: list[EntityId] = Field(default_factory=list)
    ignored_user_evidence_refs: list[EntityId] = Field(default_factory=list)


class FitAssessment(ContractModel):
    contract_version: str = "jobis.ai.v3alpha1"
    fit_assessment_id: EntityId
    common_analysis_id: EntityId
    selected_position_id: EntityId
    selected_experience_track: ExperienceTrack | None = None
    user_evidence_set_id: EntityId
    user_evidence_revision: int = Field(ge=0)
    policy_version: NonBlank
    formal_eligibility: RequirementStatus
    requirement_assessments: list[RequirementAssessment]
    metrics: FitMetrics
    strengths: list[NonBlank] = Field(default_factory=list)
    gaps: list[NonBlank] = Field(default_factory=list)
    uncertainties: list[NonBlank] = Field(default_factory=list)
    verdict_proposal: VerdictProposal
    audit: FitAudit
    warnings: list[WarningItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_requirements(self) -> "FitAssessment":
        ensure_unique(
            [assessment.requirement_id for assessment in self.requirement_assessments],
            "requirement assessment id",
        )
        return self


class FitAnalysisResult(ContractModel):
    contract_version: str = "jobis.ai.v3alpha1"
    status: FitAnalysisStatus
    assessment: FitAssessment | None = None
    active_ambiguity: Ambiguity | None = None

    @model_validator(mode="after")
    def validate_state(self) -> "FitAnalysisResult":
        if self.status is FitAnalysisStatus.AWAITING_USER_EVIDENCE:
            if self.active_ambiguity is None or self.assessment is not None:
                raise ValueError("AWAITING_USER_EVIDENCE requires only activeAmbiguity")
        if self.status is FitAnalysisStatus.COMPLETED:
            if self.assessment is None or self.active_ambiguity is not None:
                raise ValueError("COMPLETED requires only assessment")
        return self
