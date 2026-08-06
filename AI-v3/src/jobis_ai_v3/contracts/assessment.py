from __future__ import annotations

from pydantic import Field, model_validator

from .capability_graph import VerificationMethod
from .common import CONTRACT_VERSION, CanonicalKey, ContractModel, EntityId, NonBlank, ensure_unique


class AtomicCapabilityAssessmentContext(ContractModel):
    canonical_key: CanonicalKey
    technology_key: CanonicalKey
    display_name: NonBlank
    objective: NonBlank
    scope_definition: NonBlank
    excluded_scope: list[NonBlank] = Field(default_factory=list)
    verification_methods: list[VerificationMethod] = Field(min_length=1)
    graph_version: NonBlank
    graph_node_version: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_methods(self) -> "AtomicCapabilityAssessmentContext":
        ensure_unique([item.value for item in self.verification_methods], "verification method")
        return self


class AssessmentTargetContext(ContractModel):
    company_name: NonBlank | None = None
    role_title: NonBlank | None = None
    project_task_title: NonBlank | None = None
    project_task_objective: NonBlank | None = None
    current_goal: NonBlank | None = None
    final_goal: NonBlank | None = None


class CompletedAssessmentTurn(ContractModel):
    question_id: EntityId
    ordinal: int = Field(ge=1)
    method: VerificationMethod
    prompt: NonBlank
    answer: NonBlank
    score: int = Field(ge=0, le=100)
    passed: bool
    gaps: list[NonBlank] = Field(default_factory=list)


class CapabilityQuestionRequest(ContractModel):
    session_id: EntityId
    capability: AtomicCapabilityAssessmentContext
    target: AssessmentTargetContext = Field(default_factory=AssessmentTargetContext)
    completed_turns: list[CompletedAssessmentTurn] = Field(default_factory=list)
    ordinal: int = Field(ge=1, le=8)

    @model_validator(mode="after")
    def validate_history(self) -> "CapabilityQuestionRequest":
        ensure_unique([item.question_id for item in self.completed_turns], "assessment question")
        expected = list(range(1, len(self.completed_turns) + 1))
        if sorted(item.ordinal for item in self.completed_turns) != expected:
            raise ValueError("completed assessment turns must have contiguous ordinals")
        if self.ordinal != len(self.completed_turns) + 1:
            raise ValueError("question ordinal must follow completed assessment turns")
        return self


class AssessmentGenerationAudit(ContractModel):
    generator_version: NonBlank
    provider: NonBlank
    model: NonBlank
    attempts: int = Field(ge=1)
    duration_ms: int = Field(ge=0)


class CapabilityAssessmentQuestion(ContractModel):
    contract_version: str = CONTRACT_VERSION
    question_id: EntityId
    session_id: EntityId
    capability_key: CanonicalKey
    ordinal: int = Field(ge=1, le=8)
    method: VerificationMethod
    prompt: NonBlank
    starter_code: str | None = None
    answer_instructions: NonBlank
    core_criteria: list[NonBlank] = Field(min_length=2, max_length=5)
    future_extensions: list[NonBlank] = Field(default_factory=list, max_length=3)
    audit: AssessmentGenerationAudit

    @model_validator(mode="after")
    def validate_criteria(self) -> "CapabilityAssessmentQuestion":
        ensure_unique(self.core_criteria, "core criterion")
        ensure_unique(self.future_extensions, "future extension")
        return self


class CapabilityGradeRequest(ContractModel):
    capability: AtomicCapabilityAssessmentContext
    target: AssessmentTargetContext = Field(default_factory=AssessmentTargetContext)
    question: CapabilityAssessmentQuestion
    answer: NonBlank

    @model_validator(mode="after")
    def validate_question_scope(self) -> "CapabilityGradeRequest":
        if self.question.capability_key != self.capability.canonical_key:
            raise ValueError("question belongs to a different atomic capability")
        if self.question.method not in self.capability.verification_methods:
            raise ValueError("question method is not allowed by the atomic capability")
        return self


class CriterionGrade(ContractModel):
    criterion_index: int = Field(ge=0, le=4)
    score: int = Field(ge=0, le=100)
    feedback: NonBlank


class CapabilityAssessmentGrade(ContractModel):
    contract_version: str = CONTRACT_VERSION
    question_id: EntityId
    criterion_grades: list[CriterionGrade] = Field(min_length=2, max_length=5)
    score: int = Field(ge=0, le=100)
    passed: bool
    strengths: list[NonBlank] = Field(default_factory=list)
    gaps: list[NonBlank] = Field(default_factory=list)
    feedback: NonBlank
    scope_violation_detected: bool
    audit: AssessmentGenerationAudit
