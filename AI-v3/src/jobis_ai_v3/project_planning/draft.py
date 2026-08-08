from __future__ import annotations

from pydantic import Field

from jobis_ai_v3.contracts.common import CanonicalKey, ContractModel, EntityId, NonBlank


class ProjectTaskDraft(ContractModel):
    title: NonBlank
    objective: NonBlank
    acceptance_criteria: list[NonBlank] = Field(min_length=2, max_length=6)
    capability_keys: list[CanonicalKey] = Field(default_factory=list, max_length=12)
    requirement_ids: list[EntityId] = Field(min_length=1, max_length=12)


class CompanyProjectBlueprintDraft(ContractModel):
    title: NonBlank
    objective: NonBlank
    domain_context: NonBlank
    tasks: list[ProjectTaskDraft] = Field(default_factory=list, max_length=12)
    unresolved_requirement_ids: list[EntityId] = Field(default_factory=list)
