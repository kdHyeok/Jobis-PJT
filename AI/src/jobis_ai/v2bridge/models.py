from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_serializer,
    model_validator,
)


def to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class OmitNullsModel(ContractModel):
    """그 턴에 생성되지 않은 optional 산출물은 JSON 키 자체를 생략한다."""

    @model_serializer(mode="wrap")
    def _omit_nulls(self, handler):
        return {key: value for key, value in handler(self).items() if value is not None}


class PostingImportRequest(ContractModel):
    """공고 URL 수집 요청. 대화창과 동일한 URL 입력 어댑터를 사용한다."""

    source_url: str = Field(min_length=8, max_length=2_000)


class PostingImportWarning(ContractModel):
    code: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=2_000)


class PostingImportResponse(ContractModel):
    final_url: str = Field(min_length=8, max_length=2_000)
    raw_text: str = Field(max_length=100_000)
    warnings: list[PostingImportWarning] = Field(default_factory=list, max_length=100)


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
    answer_value: str = Field(min_length=1, max_length=2_000)
    answer_label: str = Field(min_length=1, max_length=2_000)
    input_type: Literal["CHOICE", "TEXT"] = "CHOICE"
    answer_status: Literal["PROVIDED", "CONFIRMED_ABSENT", "SKIPPED"] = "PROVIDED"
    related_requirement_ids: list[str] = Field(default_factory=list, max_length=50)
    absence_scope: Literal["NONE", "GENERAL_EXPERIENCE", "REQUIREMENTS"] = "NONE"

    @model_validator(mode="after")
    def validate_absence(self) -> AnalysisAnswer:
        if self.answer_status == "CONFIRMED_ABSENT" and self.absence_scope == "NONE":
            raise ValueError("confirmed absence requires a non-NONE absenceScope")
        return self


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
    "QA",
    "EMBEDDED",
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
    primary_track: CareerTrack | None = None
    experience_requirement: ExperienceRequirement | None = None
    closes_at: datetime | None = None
    lifecycle_status: Literal["ACTIVE", "EXPIRED", "CLOSED", "UNKNOWN"] = "UNKNOWN"
    source_text: str | None = Field(default=None, max_length=100_000)
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
    input_type: Literal["CHOICE", "TEXT"] = "CHOICE"
    options: list[AnalysisQuestionOption] = Field(default_factory=list, max_length=4)
    related_requirement_ids: list[str] = Field(default_factory=list, max_length=50)
    absence_scope: Literal["NONE", "GENERAL_EXPERIENCE", "REQUIREMENTS"] = "NONE"

    @model_validator(mode="after")
    def validate_input_shape(self) -> AnalysisQuestion:
        if self.input_type == "CHOICE" and not (2 <= len(self.options) <= 4):
            raise ValueError("CHOICE questions require two to four options")
        if self.input_type == "TEXT" and self.options:
            raise ValueError("TEXT questions cannot contain options")
        return self

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


NodeAction = Literal["CREATE", "REUSE"]
NodeKind = Literal["FOUNDATION", "SKILL", "PROJECT", "CERTIFICATE", "OPPORTUNITY"]


class ProposedNode(ContractModel):
    ref: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    action: NodeAction
    existing_node_id: UUID | None = None
    canonical_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{2,159}$")
    title: str = Field(min_length=1, max_length=160)
    subtitle: str | None = Field(default=None, max_length=240)
    domain: str = Field(min_length=1, max_length=40)
    kind: NodeKind
    scope_definition: str | None = None
    level: int = Field(ge=1, le=5)
    rank: int = Field(ge=0, le=10_000)
    detail: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_action_fields(self) -> "ProposedNode":
        if self.action == "CREATE":
            if self.existing_node_id is not None:
                raise ValueError("CREATE nodes cannot include existingNodeId")
            if self.scope_definition is None or not self.scope_definition.strip():
                raise ValueError("CREATE nodes require scopeDefinition")
        elif self.existing_node_id is None:
            raise ValueError("REUSE nodes require existingNodeId")
        return self


class ProposedEdge(ContractModel):
    from_ref: str
    to_ref: str
    edge_kind: Literal["PREREQUISITE", "BRANCH", "MERGE", "OPPORTUNITY_PATH"] = (
        "PREREQUISITE"
    )


class ProposedRequirement(ContractModel):
    node_ref: str
    kind: Literal["REQUIRED", "PREFERRED"]
    source_text: str | None = None
    confidence: Decimal | None = Field(default=None, ge=0, le=1)


class ChangeProposal(ContractModel):
    base_graph_version: int = Field(ge=1)
    nodes: list[ProposedNode] = Field(max_length=100)
    edges: list[ProposedEdge] = Field(max_length=200)
    requirements: list[ProposedRequirement] = Field(max_length=200)

    @field_validator("nodes")
    @classmethod
    def unique_node_refs(cls, value: list[ProposedNode]) -> list[ProposedNode]:
        refs = [node.ref for node in value]
        if len(refs) != len(set(refs)):
            raise ValueError("node refs must be unique")
        reused_ids = [node.existing_node_id for node in value if node.existing_node_id]
        if len(reused_ids) != len(set(reused_ids)):
            raise ValueError("existing node ids must be unique")
        created_identities = [
            (node.canonical_key, node.level, " ".join((node.scope_definition or "").lower().split()))
            for node in value
            if node.action == "CREATE"
        ]
        if len(created_identities) != len(set(created_identities)):
            raise ValueError("created node identities must be unique")
        return value

    @model_validator(mode="after")
    def validate_references(self) -> "ChangeProposal":
        refs = {node.ref for node in self.nodes}
        if any(edge.from_ref not in refs or edge.to_ref not in refs for edge in self.edges):
            raise ValueError("edge references must point to proposed nodes")
        if any(requirement.node_ref not in refs for requirement in self.requirements):
            raise ValueError("requirement references must point to a proposed node")
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
    "QA",
    "EMBEDDED",
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
    # The real agent currently has no company-specific target-project field.
    # Keep that absence visible instead of manufacturing project content in the
    # transport adapter.
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
        if self.target_project is None:
            return self
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
    change_proposal: ChangeProposal | None = None
    competency_proposal: CompetencyProposal | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> AnalysisResponse:
        if self.status == "NEEDS_INPUT":
            if self.question is None:
                raise ValueError("NEEDS_INPUT responses require a question")
            if any(
                value is not None
                for value in (
                    self.job,
                    self.evaluation,
                    self.change_proposal,
                    self.competency_proposal,
                )
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


class StoredResume(ContractModel):
    id: UUID | None = None
    title: str | None = Field(default=None, max_length=200)
    source_type: str | None = Field(default="TEXT", max_length=20)
    raw_text: str = Field(min_length=1, max_length=100_000)
    created_at: datetime | None = None


class StoredPosting(ContractModel):
    id: UUID | None = None
    source_type: str | None = Field(default="TEXT", max_length=20)
    source_url: str | None = None
    raw_text: str = Field(min_length=1, max_length=100_000)
    parsed_data: dict[str, Any] | None = None
    created_at: datetime | None = None


class CareerSummary(ContractModel):
    completed_nodes: list[str] = Field(default_factory=list, max_length=200)
    active_goals: list[str] = Field(default_factory=list, max_length=100)
    recent_postings: list[str] = Field(default_factory=list, max_length=50)
    saved_evidence: list[str] = Field(default_factory=list, max_length=200)
    resumes: list[StoredResume] = Field(default_factory=list, max_length=5)
    preferences: dict[str, list[str]] | None = None
    facts: list[str] = Field(default_factory=list, max_length=200)
    postings: list[StoredPosting] = Field(default_factory=list, max_length=5)
    session_state: dict[str, Any] | None = None
    interview: dict[str, Any] | None = None


class ChatPostingAsset(ContractModel):
    id: UUID
    company_name: str | None = Field(default=None, max_length=160)
    role_title: str | None = Field(default=None, max_length=200)
    source_url: str | None = Field(default=None, max_length=2_000)
    experience_text: str | None = Field(default=None, max_length=500)
    lifecycle_status: str | None = Field(default=None, max_length=40)
    raw_text: str = Field(default="", max_length=20_000)
    analysis_summary: str | None = Field(default=None, max_length=4_000)


class ChatCareerFragment(ContractModel):
    kind: str = Field(max_length=40)
    title: str = Field(max_length=180)
    description: str = Field(default="", max_length=2_000)


class ChatCareerSourceAsset(ContractModel):
    id: UUID
    source_type: str = Field(max_length=30)
    title: str = Field(max_length=180)
    source_url: str | None = Field(default=None, max_length=2_000)
    summary: str | None = Field(default=None, max_length=4_000)
    raw_text: str = Field(default="", max_length=20_000)
    fragments: list[ChatCareerFragment] = Field(default_factory=list, max_length=100)


class ChatTaskContext(ContractModel):
    mode: Literal[
        "AUTO",
        "CAREER_CHAT",
        "POSTING_QA",
        "RESUME_DIAGNOSIS",
        "POSTING_COMPARE",
        "RESUME_COMPARE",
        "INTERVIEW_PREP",
        "COVER_LETTER",
        "APPLICATION_PLAN",
        "JOB_DISCOVERY",
    ] = "AUTO"
    postings: list[ChatPostingAsset] = Field(default_factory=list, max_length=5)
    career_sources: list[ChatCareerSourceAsset] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def validate_assets_for_mode(self) -> ChatTaskContext:
        posting_minimum = {
            "POSTING_QA": 1,
            "POSTING_COMPARE": 2,
            "INTERVIEW_PREP": 1,
            "COVER_LETTER": 1,
            "APPLICATION_PLAN": 1,
        }
        career_minimum = {
            "RESUME_DIAGNOSIS": 1,
            "RESUME_COMPARE": 2,
            "COVER_LETTER": 1,
        }
        if len(self.postings) < posting_minimum.get(self.mode, 0):
            raise ValueError(f"{self.mode} requires more selected postings")
        if len(self.career_sources) < career_minimum.get(self.mode, 0):
            raise ValueError(f"{self.mode} requires more selected career sources")
        return self


class ChatRequest(ContractModel):
    conversation_id: UUID
    display_name: str = Field(min_length=1, max_length=80)
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)
    career: CareerSummary = Field(default_factory=CareerSummary)
    task: ChatTaskContext = Field(default_factory=ChatTaskContext)
    # PostgreSQL is the canonical conversation workspace.  The AI session store is
    # only a turn-local cache hydrated from this snapshot.
    workspace_state: dict[str, Any] | None = None


class SuggestedAction(ContractModel):
    action: Literal[
        "ATTACH_POSTING",
        "OPEN_MAP",
        "OPEN_STORAGE",
        "OPEN_POSTING",
        "COMPARE_POSTINGS",
        "COMPARE_RESUMES",
        "START_INTERVIEW",
        "DRAFT_COVER_LETTER",
        "BUILD_APPLICATION_PLAN",
        "FIND_ALTERNATIVES",
        "NONE",
    ]
    label: str = Field(min_length=1, max_length=80)


class ChatReplySource(ContractModel):
    source_type: Literal["POSTING", "CAREER_SOURCE", "CAREER_FRAGMENT", "ROADMAP"]
    source_id: UUID | None = None
    title: str = Field(min_length=1, max_length=200)
    excerpt: str | None = Field(default=None, max_length=500)


class AgentProgress(ContractModel):
    step: str | None = Field(default=None, max_length=120)
    agent_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,49}$")
    label: str = Field(min_length=1, max_length=80)
    status: Literal["COMPLETED", "NEEDS_CONFIRMATION"]
    message: str = Field(min_length=1, max_length=300)


class ProposedAgentAction(ContractModel):
    action_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,79}$")
    action_type: Literal[
        "NAVIGATE",
        "ANALYZE_POSTING",
        "COMPARE",
        "SAVE_DRAFT",
        "START_INTERVIEW",
        "FIND_ALTERNATIVES",
    ]
    label: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    requires_consent: bool = True
    payload: dict[str, Any] = Field(default_factory=dict)


class PendingConfirmation(ContractModel):
    question: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=500)
    options: list[str] = Field(min_length=2, max_length=5)


ChatAgentId = Literal[
    "career_chat",
    "preference_intake",
    "posting_analysis",
    "resume_diagnosis",
    "fit_analysis",
    "job_recommend",
    "interview_prep",
    "coverletter_draft",
    "application_plan",
    "roadmap_manager",
]


class PlannedChatAgent(ContractModel):
    run_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,99}$")
    agent_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,49}$")
    label: str = Field(min_length=1, max_length=80)
    group_index: int = Field(ge=0, le=20)
    order_index: int = Field(ge=0, le=50)
    reason: str | None = Field(default=None, max_length=300)
    status: Literal[
        "PENDING",
        "RUNNING",
        "COMPLETED",
        "NEEDS_CONFIRMATION",
        "FAILED",
    ] = "PENDING"


class ChatPlanEdge(ContractModel):
    from_run_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,99}$")
    to_run_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,99}$")


class ChatAgentPlan(ContractModel):
    intent: Literal[
        "GENERAL_CAREER",
        "PROFILE_DISCOVERY",
        "POSTING_ANALYSIS",
        "ROADMAP_QUESTION",
        "EVIDENCE_HELP",
        "RESUME_DIAGNOSIS",
        "ASSET_COMPARISON",
        "INTERVIEW_PREP",
        "COVER_LETTER",
        "APPLICATION_PLAN",
        "JOB_DISCOVERY",
        "OTHER",
    ]
    confidence: float | None = Field(default=None, ge=0, le=1)
    agents: list[PlannedChatAgent] = Field(default_factory=list, max_length=12)
    edges: list[ChatPlanEdge] = Field(default_factory=list, max_length=40)
    selected_posting_ids: list[UUID] = Field(default_factory=list, max_length=5)
    selected_career_source_ids: list[UUID] = Field(default_factory=list, max_length=5)
    pending_confirmation: PendingConfirmation | None = None
    updated_during_run: bool = False


class ChatArtifact(ContractModel):
    artifact_type: Literal[
        "DIAGNOSIS",
        "COMPARISON",
        "INTERVIEW_SET",
        "COVER_LETTER_DRAFT",
        "APPLICATION_PLAN",
        "JOB_DISCOVERY_PLAN",
    ]
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=2_000)
    sections: list[dict[str, Any]] = Field(default_factory=list, max_length=20)


class ChatAgentWorkProduct(ContractModel):
    agent_id: ChatAgentId
    product_type: Literal[
        "DIAGNOSIS",
        "COMPARISON",
        "INTERVIEW_SET",
        "COVER_LETTER_DRAFT",
        "APPLICATION_PLAN",
        "JOB_RECOMMENDATIONS",
        "PREFERENCES",
        "ROADMAP_VIEW",
        "POSTING_ANALYSIS",
    ]
    title: str = Field(min_length=1, max_length=200)
    reply: str | None = Field(default=None, max_length=4_000)
    summary: str = Field(min_length=1, max_length=2_000)
    findings: list[str] = Field(default_factory=list, max_length=12)
    recommendations: list[str] = Field(default_factory=list, max_length=10)
    follow_up_questions: list[str] = Field(default_factory=list, max_length=3)
    reply_sources: list[ChatReplySource] = Field(default_factory=list, max_length=12)
    suggested_actions: list[SuggestedAction] = Field(default_factory=list, max_length=3)
    proposed_actions: list[ProposedAgentAction] = Field(default_factory=list, max_length=5)
    pending_confirmation: PendingConfirmation | None = None
    artifact: ChatArtifact | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class ChatAgentWarning(ContractModel):
    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=1_000)
    agent_id: str | None = Field(default=None, max_length=50)
    recoverable: bool = True


class ChatReplyAttribution(ContractModel):
    agent_id: str = Field(min_length=1, max_length=80)
    channel: str = Field(min_length=1, max_length=40)
    text: str = Field(default="", max_length=4_000)


class CollectedPosting(ContractModel):
    source_type: Literal["URL", "TEXT"]
    source_url: str | None = None
    raw_text: str = Field(min_length=1, max_length=100_000)


class CollectedResume(ContractModel):
    source_type: Literal["TEXT"] = "TEXT"
    title: str = Field(min_length=1, max_length=200)
    raw_text: str = Field(min_length=1, max_length=100_000)


class CollectedOutputs(OmitNullsModel):
    analysis: dict[str, Any] | None = None
    roadmap: list[dict[str, Any]] | None = Field(default=None, max_length=50)
    judgment_summary: dict[str, Any] | None = None
    profile: dict[str, Any] | None = None
    recommendations: list[dict[str, Any]] | None = Field(default=None, max_length=20)
    coverletter: dict[str, Any] | None = None
    interview: dict[str, Any] | None = None
    application_plan: dict[str, Any] | None = None
    preparation_period_weeks: int | None = Field(default=None, ge=1, le=260)
    available_hours_per_week: int | None = Field(default=None, ge=1, le=168)
    session_state: dict[str, Any] | None = None
    competency_proposal: CompetencyProposal | None = None
    job_context: JobContext | None = None


class CollectedAssets(OmitNullsModel):
    posting: CollectedPosting | None = None
    resume: CollectedResume | None = None
    outputs: CollectedOutputs | None = None
    preferences: dict[str, list[str]] | None = None
    facts: list[str] | None = Field(default=None, max_length=200)


class ChatResponse(ContractModel):
    message: str = Field(min_length=1, max_length=4_000)
    intent: Literal[
        "GENERAL_CAREER",
        "PROFILE_DISCOVERY",
        "POSTING_ANALYSIS",
        "ROADMAP_QUESTION",
        "EVIDENCE_HELP",
        "RESUME_DIAGNOSIS",
        "ASSET_COMPARISON",
        "INTERVIEW_PREP",
        "COVER_LETTER",
        "APPLICATION_PLAN",
        "JOB_DISCOVERY",
        "OTHER",
    ]
    should_request_posting: bool = False
    degraded_reason: str = Field(default="", max_length=300)
    suggested_actions: list[SuggestedAction] = Field(default_factory=list, max_length=3)
    reply_sources: list[ChatReplySource] = Field(default_factory=list, max_length=12)
    progress: list[AgentProgress] = Field(default_factory=list, max_length=12)
    proposed_actions: list[ProposedAgentAction] = Field(default_factory=list, max_length=5)
    pending_confirmation: PendingConfirmation | None = None
    artifact: ChatArtifact | None = None
    plan: ChatAgentPlan | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    detailed_status: str | None = Field(default=None, max_length=80)
    work_products: list[ChatAgentWorkProduct] = Field(default_factory=list, max_length=12)
    warnings: list[ChatAgentWarning] = Field(default_factory=list, max_length=30)
    reply_attributions: list[ChatReplyAttribution] = Field(default_factory=list, max_length=30)
    workspace_state: dict[str, Any] = Field(default_factory=dict)
    collected: CollectedAssets | None = None


class ChatStreamEvent(ContractModel):
    type: Literal["PLAN", "PROGRESS", "RESULT", "ERROR"]
    sequence: int = Field(ge=1)
    occurred_at: datetime
    agent_id: str | None = Field(default=None, max_length=50)
    label: str | None = Field(default=None, max_length=80)
    status: Literal["RUNNING", "COMPLETED", "NEEDS_CONFIRMATION", "FAILED"] | None = None
    message: str | None = Field(default=None, max_length=300)
    result: ChatResponse | None = None
    plan: ChatAgentPlan | None = None
    error_code: str | None = Field(default=None, max_length=80)
    error_message: str | None = Field(default=None, max_length=1_000)


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
    ordinal: int = Field(ge=1)
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
    turns: list[AssessmentTurn] = Field(default_factory=list, max_length=20)
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
    # 출제 schema에서는 서비스가 요구 유형을 결정해 덮어쓴다. 기본값은 LLM이 kind를
    # 생략해도 구조화 본문을 검증할 수 있게 하는 내부 호환값이다.
    kind: AssessmentQuestionKind = "CONCEPT"
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

    @model_validator(mode="after")
    def validate_outcome(self) -> "CompetencyAssessmentResponse":
        if self.answer_evaluation is None and self.next_question is None:
            raise ValueError("assessment responses require an evaluation or the next question")
        return self


class CompetencyLearningRequest(ContractModel):
    competency: AssessmentCompetency
    target: AssessmentTargetContext = Field(default_factory=AssessmentTargetContext)


class LearningModule(ContractModel):
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=1_000)
    concepts: list[str] = Field(min_length=1, max_length=10)
    example: str | None = Field(default=None, max_length=4_000)
    practice: str = Field(min_length=1, max_length=2_000)
    completion_criteria: list[str] = Field(min_length=1, max_length=8)


class CompetencyLearningResponse(ContractModel):
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=2_000)
    scope_reminder: str = Field(min_length=1, max_length=4_000)
    target_context: str | None = Field(default=None, max_length=2_000)
    modules: list[LearningModule] = Field(min_length=1, max_length=8)
    recommended_resources: list[str] = Field(default_factory=list, max_length=10)
    assessment_readiness: list[str] = Field(default_factory=list, max_length=10)


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
