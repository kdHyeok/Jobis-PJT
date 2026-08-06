from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from .common import ContractModel, EntityId, NonBlank, WarningItem, ensure_unique
from .source import Confidence, SourceDocument, VerifiedPostingSnapshot


class RoleStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    CONFIRMED = "CONFIRMED"
    NEW_CANDIDATE = "NEW_CANDIDATE"
    UNKNOWN = "UNKNOWN"


class PostingStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"


class ExperienceKind(StrEnum):
    NEW_GRADUATE = "NEW_GRADUATE"
    EXPERIENCE_REQUIRED = "EXPERIENCE_REQUIRED"
    RANGE = "RANGE"
    NO_RESTRICTION = "NO_RESTRICTION"
    NEW_GRADUATE_OR_EXPERIENCED = "NEW_GRADUATE_OR_EXPERIENCED"
    UNKNOWN = "UNKNOWN"


class RequirementObligation(StrEnum):
    REQUIRED = "REQUIRED"
    PREFERRED = "PREFERRED"
    INFORMATIONAL = "INFORMATIONAL"


class RequirementCategory(StrEnum):
    TECHNOLOGY = "TECHNOLOGY"
    TECHNICAL_CAPABILITY = "TECHNICAL_CAPABILITY"
    RESPONSIBILITY = "RESPONSIBILITY"
    DOMAIN_KNOWLEDGE = "DOMAIN_KNOWLEDGE"
    CREDENTIAL = "CREDENTIAL"
    EXPERIENCE = "EXPERIENCE"
    PORTFOLIO = "PORTFOLIO"
    BEHAVIORAL = "BEHAVIORAL"
    EMPLOYMENT_CONDITION = "EMPLOYMENT_CONDITION"
    OTHER = "OTHER"


class NormalizationStatus(StrEnum):
    PENDING = "PENDING"
    KNOWN = "KNOWN"
    NEW_CANDIDATE = "NEW_CANDIDATE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AmbiguityType(StrEnum):
    SOURCE_VERIFICATION = "SOURCE_VERIFICATION"
    POSITION_SELECTION = "POSITION_SELECTION"
    EXPERIENCE_TRACK_SELECTION = "EXPERIENCE_TRACK_SELECTION"
    EXPERIENCE_CONFLICT = "EXPERIENCE_CONFLICT"
    REQUIREMENT_SCOPE = "REQUIREMENT_SCOPE"
    USER_EVIDENCE = "USER_EVIDENCE"
    OTHER = "OTHER"


class QuestionInputType(StrEnum):
    CHOICE = "CHOICE"
    TEXT = "TEXT"


class CompanyCandidate(ContractModel):
    display_name: NonBlank
    canonical_company_id: EntityId | None = None
    evidence_ids: list[EntityId] = Field(min_length=1)
    confidence: Confidence


class RoleCandidate(ContractModel):
    family: NonBlank
    specialization: NonBlank
    canonical_role_id: EntityId | None = None
    status: RoleStatus
    confidence: Confidence
    evidence_ids: list[EntityId] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_identity(self) -> "RoleCandidate":
        if self.status in {RoleStatus.CANDIDATE, RoleStatus.CONFIRMED} and self.canonical_role_id is None:
            raise ValueError("known role candidates require canonicalRoleId")
        if self.status is RoleStatus.NEW_CANDIDATE and self.canonical_role_id is not None:
            raise ValueError("new role candidates cannot already have canonicalRoleId")
        return self


class ExperienceRequirement(ContractModel):
    kind: ExperienceKind
    min_months: int | None = Field(default=None, ge=0)
    max_months: int | None = Field(default=None, ge=0)
    experienced_min_months: int | None = Field(default=None, ge=1)
    confidence: Confidence
    evidence_ids: list[EntityId] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_kind(self) -> "ExperienceRequirement":
        if self.min_months is not None and self.max_months is not None and self.min_months > self.max_months:
            raise ValueError("minMonths cannot be greater than maxMonths")
        if self.kind is ExperienceKind.EXPERIENCE_REQUIRED:
            if self.min_months is None or self.min_months <= 0:
                raise ValueError("EXPERIENCE_REQUIRED requires a positive minMonths")
        elif self.kind is ExperienceKind.RANGE:
            if self.min_months is None or self.max_months is None:
                raise ValueError("RANGE requires minMonths and maxMonths")
        elif self.kind is ExperienceKind.NEW_GRADUATE_OR_EXPERIENCED:
            if self.experienced_min_months is None:
                raise ValueError("NEW_GRADUATE_OR_EXPERIENCED requires experiencedMinMonths")
        elif self.kind in {
            ExperienceKind.NEW_GRADUATE,
            ExperienceKind.NO_RESTRICTION,
            ExperienceKind.UNKNOWN,
        }:
            if self.min_months is not None or self.max_months is not None:
                raise ValueError(f"{self.kind.value} cannot carry a numeric range")
        return self


class Responsibility(ContractModel):
    responsibility_id: EntityId
    source_text: NonBlank
    atomic_text: NonBlank
    evidence_ids: list[EntityId] = Field(min_length=1)
    confidence: Confidence


class AtomicRequirement(ContractModel):
    requirement_id: EntityId
    source_text: NonBlank
    atomic_text: NonBlank
    obligation: RequirementObligation
    category: RequirementCategory
    applies_to_position_ids: list[EntityId] = Field(min_length=1)
    evidence_ids: list[EntityId] = Field(min_length=1)
    confidence: Confidence
    normalization_status: NormalizationStatus = NormalizationStatus.PENDING
    warnings: list[WarningItem] = Field(default_factory=list)


class Position(ContractModel):
    position_id: EntityId
    source_title: NonBlank
    role: RoleCandidate
    experience: ExperienceRequirement
    responsibilities: list[Responsibility] = Field(default_factory=list)
    requirements: list[AtomicRequirement] = Field(default_factory=list)
    warnings: list[WarningItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_position_members(self) -> "Position":
        ensure_unique([item.responsibility_id for item in self.responsibilities], "responsibilityId")
        ensure_unique([item.requirement_id for item in self.requirements], "requirementId")
        for requirement in self.requirements:
            if self.position_id not in requirement.applies_to_position_ids:
                raise ValueError(
                    f"requirement {requirement.requirement_id} must apply to containing position {self.position_id}"
                )
        return self


class QuestionOption(ContractModel):
    value: EntityId
    label: NonBlank


class ClarificationQuestion(ContractModel):
    input_type: QuestionInputType
    text: NonBlank
    options: list[QuestionOption] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_options(self) -> "ClarificationQuestion":
        if self.input_type is QuestionInputType.CHOICE and len(self.options) < 2:
            raise ValueError("CHOICE questions require at least two options")
        if self.input_type is QuestionInputType.TEXT and self.options:
            raise ValueError("TEXT questions cannot include options")
        ensure_unique([option.value for option in self.options], "question option value")
        return self


class Ambiguity(ContractModel):
    ambiguity_id: EntityId
    type: AmbiguityType
    blocking: bool
    reason: NonBlank
    candidate_ids: list[EntityId] = Field(default_factory=list)
    evidence_ids: list[EntityId] = Field(min_length=1)
    question: ClarificationQuestion | None = None

    @model_validator(mode="after")
    def validate_question(self) -> "Ambiguity":
        if self.blocking and self.question is None:
            raise ValueError("blocking ambiguities require a question")
        return self


class StructuredPosting(ContractModel):
    contract_version: str = "jobis.ai.v3alpha1"
    analysis_version: NonBlank
    verified_snapshot_id: EntityId
    company: CompanyCandidate | None = None
    posting_title: NonBlank | None = None
    posting_title_evidence_ids: list[EntityId] = Field(default_factory=list)
    positions: list[Position] = Field(min_length=1)
    shared_conditions: list[AtomicRequirement] = Field(default_factory=list)
    application_deadline: date | None = None
    application_deadline_evidence_ids: list[EntityId] = Field(default_factory=list)
    posting_status: PostingStatus = PostingStatus.UNKNOWN
    ambiguities: list[Ambiguity] = Field(default_factory=list)
    warnings: list[WarningItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self) -> "StructuredPosting":
        position_ids = [position.position_id for position in self.positions]
        ensure_unique(position_ids, "positionId")
        position_id_set = set(position_ids)

        if self.application_deadline is None and self.application_deadline_evidence_ids:
            raise ValueError("deadline evidence cannot be supplied without applicationDeadline")
        if self.posting_title is None and self.posting_title_evidence_ids:
            raise ValueError("posting title evidence cannot be supplied without postingTitle")
        if self.posting_title is not None and not self.posting_title_evidence_ids:
            raise ValueError("postingTitle requires at least one evidence ID")

        requirements = [
            *(requirement for position in self.positions for requirement in position.requirements),
            *self.shared_conditions,
        ]
        ensure_unique([requirement.requirement_id for requirement in requirements], "requirementId")
        for requirement in requirements:
            missing = set(requirement.applies_to_position_ids) - position_id_set
            if missing:
                raise ValueError(
                    f"requirement {requirement.requirement_id} refers to unknown positions {sorted(missing)}"
                )

        ensure_unique([ambiguity.ambiguity_id for ambiguity in self.ambiguities], "ambiguityId")
        for ambiguity in self.ambiguities:
            if ambiguity.type is AmbiguityType.POSITION_SELECTION:
                missing = set(ambiguity.candidate_ids) - position_id_set
                if missing:
                    raise ValueError(
                        f"ambiguity {ambiguity.ambiguity_id} refers to unknown positions {sorted(missing)}"
                    )
                if len(ambiguity.candidate_ids) < 2:
                    raise ValueError("POSITION_SELECTION requires at least two position candidates")
        return self


class ApprovedRoleCatalogEntry(ContractModel):
    canonical_role_id: EntityId
    family: NonBlank
    specialization: NonBlank


class PostingInterpretationRequest(ContractModel):
    source_document: SourceDocument
    verified_snapshot: VerifiedPostingSnapshot
    as_of_date: date
    approved_role_catalog: list[ApprovedRoleCatalogEntry] = Field(default_factory=list)


def all_posting_evidence_ids(posting: StructuredPosting) -> set[str]:
    result = set(posting.company.evidence_ids) if posting.company is not None else set()
    result.update(posting.posting_title_evidence_ids)
    result.update(posting.application_deadline_evidence_ids)
    for position in posting.positions:
        result.update(position.role.evidence_ids)
        result.update(position.experience.evidence_ids)
        for responsibility in position.responsibilities:
            result.update(responsibility.evidence_ids)
        for requirement in position.requirements:
            result.update(requirement.evidence_ids)
    for requirement in posting.shared_conditions:
        result.update(requirement.evidence_ids)
    for ambiguity in posting.ambiguities:
        result.update(ambiguity.evidence_ids)
    return result
