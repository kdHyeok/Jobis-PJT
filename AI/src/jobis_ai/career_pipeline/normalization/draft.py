from __future__ import annotations

from pydantic import Field, model_validator

from jobis_ai.career_pipeline.contracts.common import CanonicalKey, ContractModel, EntityId, NonBlank, ensure_unique
from jobis_ai.career_pipeline.contracts.normalization import CapabilityKind
from jobis_ai.career_pipeline.contracts.source import Confidence


class SemanticCapabilityCandidateDraft(ContractModel):
    canonical_key: CanonicalKey
    partial_scope: bool = False
    confidence: Confidence
    reason: NonBlank


class NewCapabilityCandidateDraft(ContractModel):
    display_name: NonBlank
    proposed_kind: CapabilityKind
    scope_definition: NonBlank
    aliases: list[NonBlank] = Field(default_factory=list)
    confidence: Confidence


class RequirementNormalizationDraft(ContractModel):
    requirement_id: EntityId
    split_required: bool = False
    candidates: list[SemanticCapabilityCandidateDraft] = Field(default_factory=list)
    new_candidate: NewCapabilityCandidateDraft | None = None
    reason: NonBlank

    @model_validator(mode="after")
    def validate_choice(self) -> "RequirementNormalizationDraft":
        ensure_unique([item.canonical_key for item in self.candidates], "semantic candidate")
        if self.split_required and (self.candidates or self.new_candidate is not None):
            raise ValueError("splitRequired cannot include candidates or newCandidate")
        if self.candidates and self.new_candidate is not None:
            raise ValueError("choose catalog candidates or a new candidate, not both")
        return self


class CapabilityNormalizationDraft(ContractModel):
    items: list[RequirementNormalizationDraft]

    @model_validator(mode="after")
    def validate_items(self) -> "CapabilityNormalizationDraft":
        ensure_unique([item.requirement_id for item in self.items], "normalization draft requirementId")
        return self
