from __future__ import annotations

from datetime import date

from pydantic import Field, model_validator

from jobis_ai.career_pipeline.contracts.common import ContractModel, EntityId, NonBlank, ensure_unique
from jobis_ai.career_pipeline.contracts.posting import (
    ExperienceRequirement,
    RequirementCategory,
    RequirementObligation,
)
from jobis_ai.career_pipeline.contracts.source import Confidence


class CompanyDraft(ContractModel):
    display_name: NonBlank
    evidence_ids: list[EntityId] = Field(min_length=1)
    confidence: Confidence


class RoleDraft(ContractModel):
    family: NonBlank
    specialization: NonBlank
    canonical_role_id_candidate: EntityId | None = None
    confidence: Confidence
    evidence_ids: list[EntityId] = Field(min_length=1)


class ResponsibilityDraft(ContractModel):
    # Exact source text is reconstructed from evidence_ids by the server. The
    # model may still return it for backwards compatibility, but it no longer
    # has to repeat long posting sentences in every output row.
    source_text: NonBlank | None = None
    atomic_text: NonBlank
    evidence_ids: list[EntityId] = Field(min_length=1)
    confidence: Confidence


class RequirementDraft(ContractModel):
    source_text: NonBlank | None = None
    atomic_text: NonBlank
    obligation: RequirementObligation
    category: RequirementCategory
    evidence_ids: list[EntityId] = Field(min_length=1)
    confidence: Confidence


class PositionDraft(ContractModel):
    # 모델이 만드는 임시 상관 키다. 최종 positionId는 서버가 pos-N으로
    # 생성하므로 표시용 한글/괄호가 포함되어도 시스템 EntityId로 신뢰하지 않는다.
    position_key: NonBlank
    source_title: NonBlank
    role: RoleDraft
    experience: ExperienceRequirement
    responsibilities: list[ResponsibilityDraft] = Field(default_factory=list)
    requirements: list[RequirementDraft] = Field(default_factory=list)


class PositionDiscoveryDraft(ContractModel):
    position_key: NonBlank
    source_title: NonBlank
    role: RoleDraft
    experience: ExperienceRequirement


class SharedConditionDraft(RequirementDraft):
    applies_to_position_keys: list[NonBlank] = Field(min_length=1)


class PostingInterpretationDraft(ContractModel):
    company: CompanyDraft | None = None
    posting_title: NonBlank | None = None
    posting_title_evidence_ids: list[EntityId] = Field(default_factory=list)
    positions: list[PositionDraft] = Field(min_length=1)
    shared_conditions: list[SharedConditionDraft] = Field(default_factory=list)
    application_deadline: date | None = None
    application_deadline_evidence_ids: list[EntityId] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_draft(self) -> "PostingInterpretationDraft":
        keys = [position.position_key for position in self.positions]
        ensure_unique(keys, "positionKey")
        known = set(keys)
        for condition in self.shared_conditions:
            missing = set(condition.applies_to_position_keys) - known
            if missing:
                raise ValueError(f"shared condition refers to unknown position keys: {sorted(missing)}")
        return self


class PostingDiscoveryDraft(ContractModel):
    company: CompanyDraft | None = None
    posting_title: NonBlank | None = None
    posting_title_evidence_ids: list[EntityId] = Field(default_factory=list)
    # A verified source can still be a recruitment index, job interview, or
    # company job catalogue rather than one actionable opening.  Empty is a
    # valid discovery outcome and is promoted to ROLE_RESOLUTION_REQUIRED by
    # the service; final StructuredPosting remains strict and non-empty.
    positions: list[PositionDiscoveryDraft] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_positions(self) -> "PostingDiscoveryDraft":
        ensure_unique(
            [position.position_key for position in self.positions],
            "positionKey",
        )
        return self


class SelectedPositionDetailDraft(ContractModel):
    responsibilities: list[ResponsibilityDraft] = Field(default_factory=list)
    requirements: list[RequirementDraft] = Field(default_factory=list)
    application_deadline: date | None = None
    application_deadline_evidence_ids: list[EntityId] = Field(default_factory=list)
