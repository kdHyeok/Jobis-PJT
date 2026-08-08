from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from .common import ContractModel, EntityId, NonBlank, ensure_unique
from .posting import Ambiguity, StructuredPosting


class ResolutionStatus(StrEnum):
    AWAITING_ANSWER = "AWAITING_ANSWER"
    READY_FOR_ANALYSIS = "READY_FOR_ANALYSIS"
    UNRESOLVED = "UNRESOLVED"


class ExperienceTrack(StrEnum):
    NEW_GRADUATE = "NEW_GRADUATE"
    EXPERIENCED = "EXPERIENCED"


class ClarificationAnswer(ContractModel):
    ambiguity_id: EntityId
    selected_value: EntityId | None = None
    text_value: NonBlank | None = None
    answered_at: datetime

    @model_validator(mode="after")
    def validate_value(self) -> "ClarificationAnswer":
        if (self.selected_value is None) == (self.text_value is None):
            raise ValueError("exactly one of selectedValue or textValue is required")
        return self


class PostingResolutionRequest(ContractModel):
    structured_posting: StructuredPosting
    answers: list[ClarificationAnswer] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_answers(self) -> "PostingResolutionRequest":
        ensure_unique([answer.ambiguity_id for answer in self.answers], "ambiguity answer")
        return self


class PostingResolutionResult(ContractModel):
    contract_version: str = "jobis.ai.v3alpha1"
    structured_posting: StructuredPosting
    status: ResolutionStatus
    selected_position_id: EntityId | None = None
    selected_experience_track: ExperienceTrack | None = None
    active_ambiguity: Ambiguity | None = None
    resolved_ambiguity_ids: list[EntityId] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_state(self) -> "PostingResolutionResult":
        if self.status is ResolutionStatus.AWAITING_ANSWER and self.active_ambiguity is None:
            raise ValueError("AWAITING_ANSWER requires activeAmbiguity")
        if self.status is ResolutionStatus.READY_FOR_ANALYSIS:
            if self.active_ambiguity is not None or self.selected_position_id is None:
                raise ValueError("READY_FOR_ANALYSIS requires a selected position and no active ambiguity")
        ensure_unique(self.resolved_ambiguity_ids, "resolved ambiguity ID")
        return self
