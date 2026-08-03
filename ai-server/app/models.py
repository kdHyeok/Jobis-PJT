from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class Posting(ContractModel):
    id: UUID
    source_type: Literal["TEXT", "URL", "FILE"]
    source_url: str | None = None
    raw_text: str = Field(min_length=1, max_length=100_000)


class ExistingNode(ContractModel):
    id: UUID
    canonical_key: str
    title: str
    domain: str
    kind: str
    scope_definition: str | None = None
    level: int = Field(ge=1, le=5)
    progress_status: str


class ExistingCareerFragment(ContractModel):
    id: UUID
    kind: str
    title: str
    description: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)


class CareerGoalContext(ContractModel):
    current_posting_id: UUID | None = None
    current_company_name: str | None = Field(default=None, max_length=160)
    current_role_title: str | None = Field(default=None, max_length=200)
    final_goal_text: str | None = Field(default=None, max_length=2_000)


class CareerSnapshot(ContractModel):
    graph_id: UUID
    version: int = Field(ge=1)
    nodes: list[ExistingNode] = Field(max_length=2_000)
    fragments: list[ExistingCareerFragment] = Field(default_factory=list, max_length=1_000)
    goals: CareerGoalContext = Field(default_factory=CareerGoalContext)


class AnalysisAnswer(ContractModel):
    question_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,79}$")
    question_text: str = Field(min_length=1, max_length=1_000)
    answer_value: str = Field(min_length=1, max_length=120)
    answer_label: str = Field(min_length=1, max_length=240)


class AnalysisRequest(ContractModel):
    analysis_job_id: UUID
    posting: Posting
    career: CareerSnapshot
    question_count: int = Field(default=0, ge=0, le=3)
    answers: list[AnalysisAnswer] = Field(default_factory=list, max_length=3)
    shared_analysis: SharedPostingAnalysis | None = None


CareerTrack = Literal[
    "BACKEND",
    "FRONTEND",
    "FULLSTACK",
    "DATA",
    "AI",
    "DEVOPS",
    "CLOUD",
    "SECURITY",
    "GAME",
    "MOBILE",
]


class ExperienceRequirement(ContractModel):
    type: Literal["NONE", "REQUIRED", "PREFERRED"]
    minimum_months: int = Field(ge=0, le=600)
    maximum_months: int | None = Field(default=None, ge=0, le=600)
    source_text: str = Field(min_length=1, max_length=1_000)

    @model_validator(mode="after")
    def validate_range(self) -> ExperienceRequirement:
        if self.type == "NONE" and self.minimum_months != 0:
            raise ValueError("NONE experience requirements must start at zero")
        if (
            self.maximum_months is not None
            and self.maximum_months < self.minimum_months
        ):
            raise ValueError("maximum experience must not be below minimum")
        return self


class JobContext(ContractModel):
    company_name: str | None = None
    role_title: str | None = None
    employment_type: str | None = None
    experience_text: str | None = None
    primary_track: CareerTrack
    experience_requirement: ExperienceRequirement
    closes_at: datetime | None = None
    lifecycle_status: Literal["ACTIVE", "EXPIRED", "CLOSED", "UNKNOWN"] = "UNKNOWN"
    parsed_data: dict[str, Any] = Field(default_factory=dict)


class Evaluation(ContractModel):
    verdict: Literal["APPLY_NOW", "STRENGTHEN_THEN_APPLY", "ALTERNATIVE_FIRST"]
    summary: str
    reasons: list[str]


class AnalysisQuestionOption(ContractModel):
    value: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,119}$")
    label: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=500)


class AnalysisQuestion(ContractModel):
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,79}$")
    text: str = Field(min_length=1, max_length=1_000)
    reason: str = Field(min_length=1, max_length=1_000)
    options: list[AnalysisQuestionOption] = Field(min_length=2, max_length=4)

    @field_validator("options")
    @classmethod
    def unique_option_values(
        cls, value: list[AnalysisQuestionOption]
    ) -> list[AnalysisQuestionOption]:
        option_values = [option.value for option in value]
        if len(option_values) != len(set(option_values)):
            raise ValueError("question option values must be unique")
        return value


class ClarificationDecision(ContractModel):
    status: Literal["CONTINUE", "NEEDS_INPUT"]
    question: AnalysisQuestion | None = None

    @model_validator(mode="after")
    def validate_decision(self) -> ClarificationDecision:
        if self.status == "NEEDS_INPUT" and self.question is None:
            raise ValueError("NEEDS_INPUT decisions require a question")
        if self.status == "CONTINUE" and self.question is not None:
            raise ValueError("CONTINUE decisions cannot contain a question")
        return self


CompetencyKind = Literal[
    "TECHNOLOGY",
    "KNOWLEDGE",
    "PRACTICE",
    "TASK",
    "DOMAIN_KNOWLEDGE",
    "EXPERIENCE",
    "CREDENTIAL",
]
RoadmapStage = Literal[
    "FOUNDATION",
    "WEB",
    "LANGUAGE",
    "FRAMEWORK",
    "DATA",
    "QUALITY",
    "OPERATIONS",
    "SCALE",
    "DOMAIN",
    "EXPERIENCE",
    "CREDENTIAL",
]
RoadmapDomain = Literal[
    "COMMON",
    "BACKEND",
    "FRONTEND",
    "DATA",
    "DEVOPS",
    "CLOUD",
    "SECURITY",
    "AI",
    "MOBILE",
    "GAME",
    "DOMAIN",
    "CAREER",
]


class AnalyzedCompetency(ContractModel):
    ref: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    canonical_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{2,159}$")
    title: str = Field(min_length=1, max_length=160)
    domain: RoadmapDomain
    kind: CompetencyKind
    stage: RoadmapStage
    scope_definition: str = Field(
        min_length=1,
        max_length=4_000,
        pattern=r".*\S.*",
    )
    required_level: int = Field(ge=1, le=5)
    roadmap_eligible: bool
    verification_method: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def validate_roadmap_eligibility(self) -> AnalyzedCompetency:
        if self.roadmap_eligible and (
            self.verification_method is None
            or not self.verification_method.strip()
        ):
            raise ValueError(
                "roadmap eligible competencies require a verification method"
            )
        return self


class AnalyzedRequirement(ContractModel):
    competency_ref: str
    relation: Literal["REQUIRED", "PREFERRED", "RESPONSIBILITY"]
    source_text: str = Field(min_length=1, max_length=4_000)
    confidence: Decimal = Field(ge=0, le=1)


class TargetProjectBrief(ContractModel):
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=4_000)
    domain_context: str = Field(min_length=1, max_length=4_000)
    required_competency_refs: list[str] = Field(min_length=1, max_length=30)
    optional_competency_refs: list[str] = Field(default_factory=list, max_length=20)
    deliverables: list[str] = Field(min_length=1, max_length=20)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=30)


class CompetencyProposal(ContractModel):
    competencies: list[AnalyzedCompetency] = Field(min_length=1, max_length=100)
    requirements: list[AnalyzedRequirement] = Field(min_length=1, max_length=200)
    target_project: TargetProjectBrief

    @field_validator("competencies")
    @classmethod
    def unique_competencies(
        cls, value: list[AnalyzedCompetency]
    ) -> list[AnalyzedCompetency]:
        refs = [competency.ref for competency in value]
        if len(refs) != len(set(refs)):
            raise ValueError("competency refs must be unique")
        keys = [competency.canonical_key for competency in value]
        if len(keys) != len(set(keys)):
            raise ValueError("canonical competency keys must be unique")
        return value

    @model_validator(mode="after")
    def validate_references(self) -> CompetencyProposal:
        competencies_by_ref = {
            competency.ref: competency for competency in self.competencies
        }
        refs = set(competencies_by_ref)
        requirement_identities: set[tuple[str, str]] = set()
        for requirement in self.requirements:
            if requirement.competency_ref not in refs:
                raise ValueError(
                    "requirement references must point to analyzed competencies"
                )
            identity = (requirement.competency_ref, requirement.relation)
            if identity in requirement_identities:
                raise ValueError("competency requirements must be deduplicated")
            requirement_identities.add(identity)
        project_refs = (
            self.target_project.required_competency_refs
            + self.target_project.optional_competency_refs
        )
        if any(ref not in refs for ref in project_refs):
            raise ValueError(
                "target project references must point to analyzed competencies"
            )
        if len(project_refs) != len(set(project_refs)):
            raise ValueError("target project competency refs must be unique")
        if any(
            not competencies_by_ref[ref].roadmap_eligible
            for ref in project_refs
        ):
            raise ValueError(
                "target project cannot require qualitative competencies"
            )
        return self


class SharedPostingAnalysis(ContractModel):
    """User-independent posting interpretation reused across accounts."""

    job: JobContext
    competency_proposal: CompetencyProposal


class AnalysisResponse(ContractModel):
    status: Literal["COMPLETED", "NEEDS_INPUT"]
    question: AnalysisQuestion | None = None
    job: JobContext | None = None
    evaluation: Evaluation | None = None
    competency_proposal: CompetencyProposal | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> AnalysisResponse:
        if self.status == "NEEDS_INPUT":
            if self.question is None:
                raise ValueError("NEEDS_INPUT responses require a question")
            if any(
                value is not None
                for value in (self.job, self.evaluation, self.competency_proposal)
            ):
                raise ValueError("NEEDS_INPUT responses cannot contain a final result")
        else:
            if self.question is not None:
                raise ValueError("COMPLETED responses cannot contain a question")
            if any(
                value is None
                for value in (self.job, self.evaluation, self.competency_proposal)
            ):
                raise ValueError("COMPLETED responses require the complete result")
        return self


AnalysisStageStatus = Literal[
    "PENDING",
    "RUNNING",
    "WAITING",
    "COMPLETED",
    "FAILED",
]


class AnalysisStageDefinition(ContractModel):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{1,79}$")
    label: str = Field(min_length=1, max_length=80)
    role: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=500)
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")


class AnalysisStageUpdate(ContractModel):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{1,79}$")
    status: AnalysisStageStatus
    message: str | None = Field(default=None, max_length=1_000)


class AnalysisStreamEvent(ContractModel):
    type: Literal["RUN_STARTED", "STAGE_UPDATED", "RESULT", "ERROR"]
    run_id: UUID
    sequence: int = Field(ge=1)
    occurred_at: datetime
    stages: list[AnalysisStageDefinition] = Field(default_factory=list, max_length=12)
    stage: AnalysisStageUpdate | None = None
    result: AnalysisResponse | None = None
    error_code: str | None = Field(default=None, max_length=80)
    error_message: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def validate_payload(self) -> AnalysisStreamEvent:
        if self.type == "RUN_STARTED" and not self.stages:
            raise ValueError("RUN_STARTED events require stages")
        if self.type == "STAGE_UPDATED" and self.stage is None:
            raise ValueError("STAGE_UPDATED events require a stage")
        if self.type == "RESULT" and self.result is None:
            raise ValueError("RESULT events require a result")
        if self.type == "ERROR" and (
            not self.error_code
            or not self.error_message
        ):
            raise ValueError("ERROR events require errorCode and errorMessage")
        return self


class CompletedAnalysisResponse(ContractModel):
    status: Literal["COMPLETED"]
    job: JobContext
    evaluation: Evaluation
    competency_proposal: CompetencyProposal

    def to_analysis_response(self) -> AnalysisResponse:
        return AnalysisResponse(
            status="COMPLETED",
            job=self.job,
            evaluation=self.evaluation,
            competency_proposal=self.competency_proposal,
        )


class ChatMessage(ContractModel):
    role: Literal["USER", "ASSISTANT"]
    content: str = Field(min_length=1, max_length=20_000)


class CareerSummary(ContractModel):
    completed_nodes: list[str] = Field(default_factory=list, max_length=200)
    active_goals: list[str] = Field(default_factory=list, max_length=100)
    recent_postings: list[str] = Field(default_factory=list, max_length=50)
    saved_evidence: list[str] = Field(default_factory=list, max_length=200)


class ChatRequest(ContractModel):
    conversation_id: UUID
    display_name: str = Field(min_length=1, max_length=80)
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)
    career: CareerSummary = Field(default_factory=CareerSummary)


class SuggestedAction(ContractModel):
    action: Literal["ATTACH_POSTING", "OPEN_MAP", "OPEN_STORAGE", "NONE"]
    label: str = Field(min_length=1, max_length=80)


class ChatResponse(ContractModel):
    message: str = Field(min_length=1, max_length=4_000)
    intent: Literal[
        "GENERAL_CAREER",
        "PROFILE_DISCOVERY",
        "POSTING_ANALYSIS",
        "ROADMAP_QUESTION",
        "EVIDENCE_HELP",
        "OTHER",
    ]
    should_request_posting: bool = False
    suggested_actions: list[SuggestedAction] = Field(default_factory=list, max_length=3)


class EvidenceNode(ContractModel):
    id: UUID
    title: str
    domain: str
    kind: str
    scope_definition: str
    level: int = Field(ge=1, le=5)


class EvidencePayload(ContractModel):
    id: UUID
    evidence_type: str
    title: str
    source_url: str | None = None
    content: dict[str, Any] = Field(default_factory=dict)


class EvidenceVerificationRequest(ContractModel):
    evidence: EvidencePayload
    node: EvidenceNode


class EvidenceVerificationResponse(ContractModel):
    verdict: Literal["VERIFIED", "NEEDS_WORK", "REJECTED"]
    confidence: Decimal = Field(ge=0, le=1)
    summary: str = Field(min_length=1, max_length=2_000)
    strengths: list[str] = Field(default_factory=list, max_length=10)
    gaps: list[str] = Field(default_factory=list, max_length=10)
    next_actions: list[str] = Field(default_factory=list, max_length=10)


AssessmentQuestionKind = Literal["CONCEPT", "CODE", "SCENARIO", "FOLLOW_UP"]


class AssessmentCompetency(ContractModel):
    canonical_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{2,159}$")
    title: str = Field(min_length=1, max_length=160)
    domain: str = Field(min_length=1, max_length=40)
    scope_definition: str = Field(min_length=1, max_length=4_000)
    required_level: int = Field(ge=1, le=5)
    level_definition: dict[str, Any] = Field(default_factory=dict)
    assessment_blueprint: dict[str, Any] = Field(default_factory=dict)


class AssessmentTargetContext(ContractModel):
    company_name: str | None = Field(default=None, max_length=160)
    role_title: str | None = Field(default=None, max_length=200)
    primary_track: str | None = Field(default=None, max_length=40)
    domain_context: str | None = Field(default=None, max_length=4_000)
    requirement_source: str | None = Field(default=None, max_length=4_000)
    current_goal: str | None = Field(default=None, max_length=500)
    final_goal: str | None = Field(default=None, max_length=2_000)


class AssessmentTurn(ContractModel):
    ordinal: int = Field(ge=1, le=5)
    question_kind: AssessmentQuestionKind
    prompt: str = Field(min_length=1, max_length=6_000)
    code_snippet: str | None = Field(default=None, max_length=8_000)
    answer_text: str | None = Field(default=None, max_length=12_000)
    score: int | None = Field(default=None, ge=0, le=100)
    feedback: str | None = Field(default=None, max_length=4_000)


class CompetencyAssessmentRequest(ContractModel):
    session_id: UUID
    competency: AssessmentCompetency
    target: AssessmentTargetContext = Field(default_factory=AssessmentTargetContext)
    turns: list[AssessmentTurn] = Field(default_factory=list, max_length=5)
    retained_scores: dict[
        Literal["CONCEPT", "CODE", "SCENARIO"],
        int,
    ] = Field(default_factory=dict, max_length=3)
    required_question_kind: AssessmentQuestionKind | None = None

    @field_validator("retained_scores")
    @classmethod
    def validate_retained_scores(
        cls,
        value: dict[str, int],
    ) -> dict[str, int]:
        if any(score < 60 or score > 100 for score in value.values()):
            raise ValueError("retained assessment scores must be between 60 and 100")
        return value


class AssessmentAnswerEvaluation(ContractModel):
    score: int = Field(ge=0, le=100)
    verdict: Literal["PASS", "PARTIAL", "FAIL"]
    feedback: str = Field(min_length=1, max_length=4_000)
    covered_criteria: list[str] = Field(default_factory=list, max_length=12)
    gaps: list[str] = Field(default_factory=list, max_length=12)
    future_extensions: list[str] = Field(default_factory=list, max_length=12)


class AssessmentQuestion(ContractModel):
    kind: AssessmentQuestionKind
    prompt: str = Field(min_length=1, max_length=6_000)
    code_snippet: str | None = Field(default=None, max_length=8_000)
    core_criteria: list[str] = Field(default_factory=list, max_length=12)
    future_extensions: list[str] = Field(default_factory=list, max_length=12)


class CompetencyAssessmentResponse(ContractModel):
    answer_evaluation: AssessmentAnswerEvaluation | None = None
    next_question: AssessmentQuestion | None = None
    session_summary: str = Field(min_length=1, max_length=2_000)
    strengths: list[str] = Field(default_factory=list, max_length=10)
    gaps: list[str] = Field(default_factory=list, max_length=10)
    next_actions: list[str] = Field(default_factory=list, max_length=10)


CareerFragmentKind = Literal[
    "SKILL",
    "PROJECT",
    "EXPERIENCE",
    "EDUCATION",
    "CREDENTIAL",
    "ACHIEVEMENT",
    "LINK",
]


class CareerExtractionRequest(ContractModel):
    source_id: UUID
    source_type: Literal["TEXT", "FILE", "URL"]
    title: str = Field(min_length=1, max_length=180)
    source_url: str | None = Field(default=None, max_length=2_000)
    raw_text: str = Field(min_length=20, max_length=100_000)


class CareerFragmentSuggestion(ContractModel):
    kind: CareerFragmentKind
    title: str = Field(min_length=1, max_length=180)
    description: str = Field(default="", max_length=4_000)
    canonical_key: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9][a-z0-9._:-]{2,159}$",
    )
    detail: dict[str, Any] = Field(default_factory=dict)


class CareerExtractionResponse(ContractModel):
    summary: str = Field(min_length=1, max_length=2_000)
    fragments: list[CareerFragmentSuggestion] = Field(min_length=1, max_length=100)
