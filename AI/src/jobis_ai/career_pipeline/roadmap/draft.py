from __future__ import annotations

from pydantic import Field, model_validator

from jobis_ai.career_pipeline.contracts.common import CanonicalKey, ContractModel, EntityId, NonBlank, ensure_unique


class TargetProjectDraft(ContractModel):
    title: NonBlank
    objective: NonBlank
    deliverables: list[NonBlank] = Field(min_length=2, max_length=6)
    verification_criteria: list[NonBlank] = Field(min_length=2, max_length=6)
    required_capability_keys: list[CanonicalKey] = Field(default_factory=list)
    preferred_capability_keys: list[CanonicalKey] = Field(default_factory=list)
    required_provisional_candidate_ids: list[EntityId] = Field(default_factory=list)
    preferred_provisional_candidate_ids: list[EntityId] = Field(default_factory=list)
    domain_context: NonBlank

    @model_validator(mode="after")
    def validate_references(self) -> "TargetProjectDraft":
        ensure_unique(self.required_capability_keys, "draft required capability")
        ensure_unique(self.preferred_capability_keys, "draft preferred capability")
        ensure_unique(
            self.required_provisional_candidate_ids,
            "draft required provisional capability",
        )
        ensure_unique(
            self.preferred_provisional_candidate_ids,
            "draft preferred provisional capability",
        )
        return self


class RoadmapContentDraft(ContractModel):
    project: TargetProjectDraft
