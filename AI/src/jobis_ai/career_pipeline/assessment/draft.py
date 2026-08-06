from __future__ import annotations

from pydantic import Field, model_validator

from jobis_ai.career_pipeline.contracts.assessment import CriterionGrade
from jobis_ai.career_pipeline.contracts.common import ContractModel, NonBlank


class CapabilityQuestionDraft(ContractModel):
    prompt: NonBlank
    starter_code: str | None = None
    answer_instructions: NonBlank
    core_criteria: list[NonBlank] = Field(min_length=2, max_length=5)
    future_extensions: list[NonBlank] = Field(default_factory=list, max_length=3)


class CapabilityGradeDraft(ContractModel):
    criterion_grades: list[CriterionGrade] = Field(min_length=2, max_length=5)
    strengths: list[NonBlank] = Field(default_factory=list)
    gaps: list[NonBlank] = Field(default_factory=list)
    feedback: NonBlank
    scope_violation_detected: bool = False

    @model_validator(mode="after")
    def validate_indexes(self) -> "CapabilityGradeDraft":
        indexes = [item.criterion_index for item in self.criterion_grades]
        if len(indexes) != len(set(indexes)):
            raise ValueError("criterion grade indexes must be unique")
        return self

