"""서비스 v2 백엔드 ↔ AI HTTP 계약 스키마.

**계약 정본은 팀 저장소의 `ai-server/app/models.py`** (feat/be/jobiss-service-v2)다.
이 파일은 그 정본의 사본이다 — 백엔드가 보내는/받는 JSON 을 같은 검증기로 지키기 위해
그대로 가져왔고, 여기서 필드를 더하거나 빼지 않는다. 정본이 바뀌면 이 파일을 다시 맞춘다.

계약 요지(팀 README·architecture.md):
  · AI 서버는 무상태 — 매 요청에 전체 문맥(공고 원문·커리어 스냅샷·대화 이력)이 담겨 온다.
  · camelCase + extra="forbid" — 모르는 필드가 오면/나가면 거부된다.
  · /v1/analyses 는 COMPLETED(전체 결과) 또는 NEEDS_INPUT(선택형 질문 정확히 1개) 둘 중 하나.
"""

from __future__ import annotations

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


class CareerSnapshot(ContractModel):
    graph_id: UUID
    version: int = Field(ge=1)
    nodes: list[ExistingNode] = Field(max_length=2_000)
    fragments: list[ExistingCareerFragment] = Field(default_factory=list, max_length=1_000)


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


class JobContext(ContractModel):
    company_name: str | None = None
    role_title: str | None = None
    employment_type: str | None = None
    experience_text: str | None = None
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


NodeAction = Literal["CREATE", "REUSE"]
NodeKind = Literal[
    "FOUNDATION",
    "SKILL",
    "PROJECT",
    "CREDENTIAL",
    "EXPERIENCE",
    "OPPORTUNITY",
    "OPPORTUNITY_CLUSTER",
]


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

    @field_validator("scope_definition")
    @classmethod
    def created_node_needs_scope(cls, value: str | None, info):
        action = info.data.get("action")
        if action == "CREATE" and (value is None or not value.strip()):
            raise ValueError("CREATE nodes require scopeDefinition")
        return value

    @field_validator("existing_node_id")
    @classmethod
    def reused_node_needs_id(cls, value: UUID | None, info):
        action = info.data.get("action")
        if action == "REUSE" and value is None:
            raise ValueError("REUSE nodes require existingNodeId")
        if action == "CREATE" and value is not None:
            raise ValueError("CREATE nodes cannot include existingNodeId")
        return value

    @model_validator(mode="after")
    def validate_action_fields(self) -> ProposedNode:
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
    edge_kind: Literal[
        "PREREQUISITE",
        "BRANCH",
        "MERGE",
        "OPPORTUNITY_PATH",
    ] = "PREREQUISITE"


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
        reused_ids = [
            node.existing_node_id for node in value if node.existing_node_id is not None
        ]
        if len(reused_ids) != len(set(reused_ids)):
            raise ValueError("existing node ids must be unique")
        created_identities = [
            (
                node.canonical_key,
                node.level,
                " ".join((node.scope_definition or "").lower().split()),
            )
            for node in value
            if node.action == "CREATE"
        ]
        if len(created_identities) != len(set(created_identities)):
            raise ValueError("created node identities must be unique")
        return value

    @model_validator(mode="after")
    def validate_references(self) -> ChangeProposal:
        refs = {node.ref for node in self.nodes}
        for edge in self.edges:
            if edge.from_ref not in refs or edge.to_ref not in refs:
                raise ValueError("edge references must point to proposed nodes")
        for requirement in self.requirements:
            if requirement.node_ref not in refs:
                raise ValueError("requirement references must point to a proposed node")
        return self


class AnalysisResponse(ContractModel):
    status: Literal["COMPLETED", "NEEDS_INPUT"]
    question: AnalysisQuestion | None = None
    job: JobContext | None = None
    evaluation: Evaluation | None = None
    change_proposal: ChangeProposal | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> AnalysisResponse:
        if self.status == "NEEDS_INPUT":
            if self.question is None:
                raise ValueError("NEEDS_INPUT responses require a question")
            if any(
                value is not None
                for value in (self.job, self.evaluation, self.change_proposal)
            ):
                raise ValueError("NEEDS_INPUT responses cannot contain a final result")
        else:
            if self.question is not None:
                raise ValueError("COMPLETED responses cannot contain a question")
            if any(
                value is None
                for value in (self.job, self.evaluation, self.change_proposal)
            ):
                raise ValueError("COMPLETED responses require the complete result")
        return self


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
