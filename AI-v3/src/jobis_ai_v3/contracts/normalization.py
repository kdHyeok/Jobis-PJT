from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from .common import CanonicalKey, ContractModel, EntityId, NonBlank, WarningItem, ensure_unique
from .posting import RequirementCategory, StructuredPosting
from .source import Confidence


class CapabilityKind(StrEnum):
    PROGRAMMING_LANGUAGE = "PROGRAMMING_LANGUAGE"
    FRAMEWORK = "FRAMEWORK"
    LIBRARY = "LIBRARY"
    DATABASE = "DATABASE"
    MESSAGING = "MESSAGING"
    CLOUD = "CLOUD"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    TOOL = "TOOL"
    PROTOCOL = "PROTOCOL"
    COMPUTER_SCIENCE = "COMPUTER_SCIENCE"
    SOFTWARE_PRACTICE = "SOFTWARE_PRACTICE"
    TECHNICAL_CAPABILITY = "TECHNICAL_CAPABILITY"
    DOMAIN_KNOWLEDGE = "DOMAIN_KNOWLEDGE"
    OTHER = "OTHER"


class CatalogEntryStatus(StrEnum):
    APPROVED = "APPROVED"
    DEPRECATED = "DEPRECATED"


class RoadmapDisposition(StrEnum):
    LEARNING_CAPABILITY = "LEARNING_CAPABILITY"
    PROJECT_CONTEXT = "PROJECT_CONTEXT"
    CAREER_GATE = "CAREER_GATE"
    FIT_ONLY = "FIT_ONLY"
    EMPLOYMENT_INFORMATION = "EMPLOYMENT_INFORMATION"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class MatchType(StrEnum):
    EXACT_CANONICAL_KEY = "EXACT_CANONICAL_KEY"
    EXACT_ALIAS = "EXACT_ALIAS"
    AI_DIRECT_SCOPE = "AI_DIRECT_SCOPE"
    AI_PARTIAL_SCOPE = "AI_PARTIAL_SCOPE"


class NormalizationDecision(StrEnum):
    AUTO_SELECTED = "AUTO_SELECTED"
    CANDIDATES_PROPOSED = "CANDIDATES_PROPOSED"
    NEW_CANDIDATE_PROPOSED = "NEW_CANDIDATE_PROPOSED"
    SPLIT_REQUIRED = "SPLIT_REQUIRED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNRESOLVED = "UNRESOLVED"


class ReviewStatus(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    OPERATOR_REVIEW_REQUIRED = "OPERATOR_REVIEW_REQUIRED"
    SOURCE_RESTRUCTURE_REQUIRED = "SOURCE_RESTRUCTURE_REQUIRED"


class ReviewAction(StrEnum):
    LINK_EXISTING = "LINK_EXISTING"
    APPROVE_NEW = "APPROVE_NEW"
    SPLIT_SOURCE = "SPLIT_SOURCE"
    HOLD = "HOLD"
    REJECT = "REJECT"
    REVERT = "REVERT"


class CapabilityCatalogEntry(ContractModel):
    canonical_key: CanonicalKey
    display_name: NonBlank
    kind: CapabilityKind
    scope_definition: NonBlank
    aliases: list[NonBlank] = Field(default_factory=list)
    status: CatalogEntryStatus = CatalogEntryStatus.APPROVED
    version: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_aliases(self) -> "CapabilityCatalogEntry":
        normalized = [alias.strip().casefold() for alias in self.aliases]
        if len(normalized) != len(set(normalized)):
            raise ValueError(f"duplicate aliases in {self.canonical_key}")
        return self


class CapabilityCatalogSnapshot(ContractModel):
    catalog_version: NonBlank
    entries: list[CapabilityCatalogEntry]

    @model_validator(mode="after")
    def validate_entries(self) -> "CapabilityCatalogSnapshot":
        ensure_unique([entry.canonical_key for entry in self.entries], "catalog canonicalKey")
        return self


class CapabilityCandidate(ContractModel):
    canonical_key: CanonicalKey
    match_type: MatchType
    confidence: Confidence
    reason: NonBlank


class NewCapabilityCandidate(ContractModel):
    candidate_id: EntityId
    display_name: NonBlank
    proposed_kind: CapabilityKind
    scope_definition: NonBlank
    aliases: list[NonBlank] = Field(default_factory=list)
    evidence_ids: list[EntityId] = Field(min_length=1)
    confidence: Confidence


class RequirementNormalization(ContractModel):
    requirement_id: EntityId
    source_category: RequirementCategory
    disposition: RoadmapDisposition
    decision: NormalizationDecision
    selected_canonical_key: CanonicalKey | None = None
    candidates: list[CapabilityCandidate] = Field(default_factory=list)
    new_candidate: NewCapabilityCandidate | None = None
    review_status: ReviewStatus
    evidence_ids: list[EntityId] = Field(min_length=1)
    reason: NonBlank
    warnings: list[WarningItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_decision(self) -> "RequirementNormalization":
        ensure_unique([item.canonical_key for item in self.candidates], "normalization candidate")
        if self.decision is NormalizationDecision.AUTO_SELECTED:
            if self.selected_canonical_key is None or self.review_status is not ReviewStatus.NOT_REQUIRED:
                raise ValueError("AUTO_SELECTED requires selectedCanonicalKey and no review")
            if self.new_candidate is not None:
                raise ValueError("AUTO_SELECTED cannot include newCandidate")
        elif self.selected_canonical_key is not None:
            raise ValueError("only AUTO_SELECTED may set selectedCanonicalKey")
        if self.decision is NormalizationDecision.NEW_CANDIDATE_PROPOSED:
            if self.new_candidate is None:
                raise ValueError("NEW_CANDIDATE_PROPOSED requires newCandidate")
            if self.review_status is not ReviewStatus.OPERATOR_REVIEW_REQUIRED:
                raise ValueError("new candidates require operator review")
        elif self.new_candidate is not None:
            raise ValueError("newCandidate requires NEW_CANDIDATE_PROPOSED")
        if self.decision is NormalizationDecision.CANDIDATES_PROPOSED:
            if not self.candidates or self.review_status is not ReviewStatus.OPERATOR_REVIEW_REQUIRED:
                raise ValueError("candidate proposals require candidates and operator review")
        if self.decision is NormalizationDecision.SPLIT_REQUIRED:
            if self.review_status is not ReviewStatus.SOURCE_RESTRUCTURE_REQUIRED:
                raise ValueError("SPLIT_REQUIRED requires source restructure review")
        if self.decision is NormalizationDecision.NOT_APPLICABLE:
            if self.review_status is not ReviewStatus.NOT_REQUIRED:
                raise ValueError("NOT_APPLICABLE cannot require review")
            if self.candidates:
                raise ValueError("NOT_APPLICABLE cannot include capability candidates")
        return self


class CapabilityNormalizationRequest(ContractModel):
    common_analysis_id: EntityId
    structured_posting: StructuredPosting
    selected_position_id: EntityId
    catalog: CapabilityCatalogSnapshot

    @model_validator(mode="after")
    def validate_position(self) -> "CapabilityNormalizationRequest":
        if self.selected_position_id not in {
            position.position_id for position in self.structured_posting.positions
        }:
            raise ValueError("selectedPositionId does not exist in structuredPosting")
        return self


class NormalizationAudit(ContractModel):
    normalizer_version: NonBlank
    catalog_version: NonBlank
    provider: NonBlank | None = None
    model: NonBlank | None = None
    generation_attempts: int | None = Field(default=None, ge=1)
    generation_duration_ms: int | None = Field(default=None, ge=0)
    exact_match_requirement_ids: list[EntityId] = Field(default_factory=list)
    ai_match_requirement_ids: list[EntityId] = Field(default_factory=list)


class CapabilityNormalizationResult(ContractModel):
    contract_version: str = "jobis.ai.v3alpha1"
    normalization_id: EntityId
    common_analysis_id: EntityId
    selected_position_id: EntityId
    catalog_version: NonBlank
    items: list[RequirementNormalization]
    audit: NormalizationAudit
    warnings: list[WarningItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_items(self) -> "CapabilityNormalizationResult":
        ensure_unique([item.requirement_id for item in self.items], "normalized requirementId")
        return self


class NormalizationReviewDecision(ContractModel):
    review_id: EntityId
    normalization_id: EntityId
    requirement_id: EntityId
    action: ReviewAction
    selected_canonical_key: CanonicalKey | None = None
    new_candidate_id: EntityId | None = None
    operator_ref: EntityId
    decided_at: datetime
    reason: NonBlank
    supersedes_review_id: EntityId | None = None

    @model_validator(mode="after")
    def validate_action(self) -> "NormalizationReviewDecision":
        if self.action is ReviewAction.LINK_EXISTING:
            if self.selected_canonical_key is None or self.new_candidate_id is not None:
                raise ValueError("LINK_EXISTING requires only selectedCanonicalKey")
        elif self.action is ReviewAction.APPROVE_NEW:
            if self.new_candidate_id is None or self.selected_canonical_key is not None:
                raise ValueError("APPROVE_NEW requires only newCandidateId")
        elif self.selected_canonical_key is not None or self.new_candidate_id is not None:
            raise ValueError(f"{self.action.value} cannot select a capability")
        if self.action is ReviewAction.REVERT and self.supersedes_review_id is None:
            raise ValueError("REVERT requires supersedesReviewId")
        return self
