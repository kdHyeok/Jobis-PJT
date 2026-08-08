from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from jobis_ai.career_pipeline.contracts.common import CanonicalKey, ContractModel, EntityId, NonBlank, ensure_unique
from jobis_ai.career_pipeline.contracts.source import Confidence


class SemanticRelation(StrEnum):
    DIRECT = "DIRECT"
    PARTIAL = "PARTIAL"


class CompetencyMatchCandidate(ContractModel):
    competency_id: CanonicalKey
    relation: SemanticRelation
    confidence: Confidence


class FormalFactMatchCandidate(ContractModel):
    fact_id: EntityId
    relation: SemanticRelation
    confidence: Confidence


class RequirementMatchDraft(ContractModel):
    requirement_id: EntityId
    competency_candidates: list[CompetencyMatchCandidate] = Field(default_factory=list)
    formal_fact_candidates: list[FormalFactMatchCandidate] = Field(default_factory=list)
    confidence: Confidence
    reason: NonBlank

    @model_validator(mode="after")
    def validate_candidates(self) -> "RequirementMatchDraft":
        ensure_unique(
            [candidate.competency_id for candidate in self.competency_candidates],
            "competency match candidate",
        )
        ensure_unique(
            [candidate.fact_id for candidate in self.formal_fact_candidates],
            "formal fact match candidate",
        )
        return self


class FitMatchDraft(ContractModel):
    requirement_matches: list[RequirementMatchDraft]

    @model_validator(mode="after")
    def validate_requirements(self) -> "FitMatchDraft":
        ensure_unique(
            [item.requirement_id for item in self.requirement_matches],
            "requirement match draft",
        )
        return self
