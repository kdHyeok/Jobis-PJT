"""서비스 v2 백엔드 ↔ AI HTTP 계약 스키마.

**계약 정본은 백엔드 코드다** — `analysis/AiContracts.java`(역직렬화 대상),
`roadmap/RoadmapService`(그 값이 지도에서 무엇이 되는가), `db/migration/V10·V12`
(DB CHECK 이 거부하는 값), `frontend/src/types.ts`(화면이 기대하는 형태).

`ai-server/app/models.py` 는 **정본이 아니다.** 백엔드 팀원이 자기 AI 답변을 시험하려고
세운 서버이고, 우리가 동기화할 의무가 없다(그쪽 실험이 우리를 깨면 안 된다). 다만 같은
계약을 향해 먼저 작성된 **참고 구현**이라 스키마·프롬프트를 가져올 값어치는 있다.
가져오되 빚은 지지 않는다 — 어긋나면 백엔드 코드를 따른다.

계약 요지(팀 README·architecture.md):

계약 요지(팀 README·architecture.md):
  · AI 서버는 무상태 — 매 요청에 전체 문맥(공고 원문·커리어 스냅샷·대화 이력)이 담겨 온다.
  · camelCase + extra="forbid" — 모르는 필드가 오면/나가면 거부된다.
    **요청 쪽 누락이 곧 장애다**: 백엔드가 보내는 필드가 여기 없으면 요청 전체가 422 로
    거부된다(모르는 필드를 무시하지 않는다). 응답 쪽 누락과 대칭이 아니다.
  · /v1/analyses 는 COMPLETED(전체 결과) 또는 NEEDS_INPUT(선택형 질문 정확히 1개) 둘 중 하나.
"""

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
    """`AiContracts.CareerGoalContext` — 사용자가 지금 겨냥한 공고와 최종 목표."""

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
    # 같은 공고를 이미 정규화해 둔 결과(계정 간 재사용). 백엔드가 보내므로 **받는 칸이
    # 없으면 요청 자체가 거부된다** — 쓰지 않더라도 선언은 있어야 한다.
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
    """공고의 경력 조건 — 지도의 **경력 관문 노드**가 여기서 나온다.

    `type=REQUIRED` 이고 `minimumMonths>0` 일 때만 관문이 생긴다(`RoadmapService`).
    연 단위는 개월로 환산해서 넣는다("2년 이상 4년 이하" → REQUIRED, 24, 48).
    """

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
    # --- 지도 재료 (계약상 필수) ---------------------------------------------------
    # **아직 Optional 이다.** 계약은 둘 다 필수지만, 지금 이 값을 채우는 생산자가 없다
    # (`mapping.build_job_context` 는 파싱 결과만 옮긴다). 필수로 선언하면 스키마만 넣은
    # 이 단계에서 분석 경로가 통째로 멈춘다. **2단계(생산자 연결)에서 Optional 을 뗀다** —
    # 그때까지는 검증기가 이 두 칸을 지키지 않는다는 뜻이므로, 미룬 사실을 여기 적어 둔다.
    primary_track: CareerTrack | None = None
    experience_requirement: ExperienceRequirement | None = None
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


# ---------------------------------------------------------------------------
# 역량 제안 — **지도의 재료 전부**
# ---------------------------------------------------------------------------
# 위의 ChangeProposal(nodes/edges/rank)은 백엔드에서 legacy 로 격리됐다. 새 분석은 노드나
# 간선을 만들지 않는다 — `RoadmapService.buildSnapshot` 이 DB 행에서 결정론으로 그린다.
# AI 가 내는 것은 **그 행의 재료**뿐이다.
CompetencyKind = Literal[
    "TECHNOLOGY",
    "KNOWLEDGE",
    "PRACTICE",
    "TASK",
    "DOMAIN_KNOWLEDGE",
    "EXPERIENCE",
    "CREDENTIAL",
]
# 노드의 **가로 순서**. 같은 `track|stage` 는 한 MILESTONE 으로 묶인다(RoadmapService).
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
# DB CHECK 제약이 있다(V10). 여기 없는 값은 백엔드가 아니라 **DB 가** 거부한다.
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
    """지도의 역량 노드 하나.

    `canonicalKey` 는 `user_competencies` 의 유일키다 — **같은 기술이 공고마다 다른 키를
    받으면 사용자 역량이 쪼개지고 지도에 중복 노드가 생긴다.** 그리고 그 고장은 조용하다
    (예외도 경고도 없이 지도만 이상해진다). 키를 짓는 쪽이 `skill_taxonomy` 를 앵커로
    쓰는 것은 3단계의 몫이고, 여기서는 형태만 강제한다.
    """

    ref: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    canonical_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{2,159}$")
    title: str = Field(min_length=1, max_length=160)
    domain: RoadmapDomain
    kind: CompetencyKind
    stage: RoadmapStage
    scope_definition: str = Field(min_length=1, max_length=4_000, pattern=r".*\S.*")
    required_level: int = Field(ge=1, le=5)
    roadmap_eligible: bool
    verification_method: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def validate_roadmap_eligibility(self) -> AnalyzedCompetency:
        """로드맵에 올릴 역량은 **무엇으로 검증하는지**를 반드시 댄다.

        검증 방법 없는 역량은 사용자가 영원히 완료 처리할 수 없는 노드가 된다.
        정성 조건(책임감·소통력)은 `roadmapEligible=false` 로 두고 지도에서 뺀다.
        """

        if self.roadmap_eligible and not (self.verification_method or "").strip():
            raise ValueError("roadmap eligible competencies require a verification method")
        return self


class AnalyzedRequirement(ContractModel):
    """공고가 그 역량을 어떤 강도로 요구하는가.

    `REQUIRED` = 지도의 본선 경로, `PREFERRED` = 우대사항 선택 퀘스트(optional 노드).
    `RESPONSIBILITY` 는 `RoadmapService` 가 읽지 않아 **지도에 나오지 않는다** — 낼 수는
    있지만 그것만으로는 노드가 생기지 않는다는 뜻이다.
    """

    competency_ref: str
    relation: Literal["REQUIRED", "PREFERRED", "RESPONSIBILITY"]
    source_text: str = Field(min_length=1, max_length=4_000)
    confidence: Decimal = Field(ge=0, le=1)


class TargetProjectBrief(ContractModel):
    """PROJECT 노드 1개 — 필수 역량 경로 끝에 붙고 그 뒤에 OPPORTUNITY(공고)가 온다.

    **옵션이 아니다.** 이게 없으면 지도에서 회사 가지가 완성되지 않는다.
    """

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
        """참조 무결성 — 끊긴 참조는 백엔드에서 502 가 된다."""

        competencies_by_ref = {c.ref: c for c in self.competencies}
        refs = set(competencies_by_ref)

        seen: set[tuple[str, str]] = set()
        for requirement in self.requirements:
            if requirement.competency_ref not in refs:
                raise ValueError("requirement references must point to analyzed competencies")
            identity = (requirement.competency_ref, requirement.relation)
            if identity in seen:
                raise ValueError("competency requirements must be deduplicated")
            seen.add(identity)

        project_refs = (
            self.target_project.required_competency_refs
            + self.target_project.optional_competency_refs
        )
        if any(ref not in refs for ref in project_refs):
            raise ValueError("target project references must point to analyzed competencies")
        if len(project_refs) != len(set(project_refs)):
            raise ValueError("target project competency refs must be unique")
        # 정성 역량으로는 프로젝트를 증명할 수 없다 — 로드맵에서 빠진 것을 과제가 참조하면
        # 완료 판정이 영원히 성립하지 않는다.
        if any(not competencies_by_ref[ref].roadmap_eligible for ref in project_refs):
            raise ValueError("target project cannot require qualitative competencies")
        return self


# ---------------------------------------------------------------------------
# 분석 진행 스트리밍 (`POST /v1/analyses/stream`, NDJSON)
# ---------------------------------------------------------------------------
# 제약은 백엔드가 **검증하고 실패시키는** 값이다: `AnalysisWorker.recordProgress` 가
# `runId != analysisJobId` 이거나 `sequence` 범위를 벗어나면 IllegalStateException 을 던져
# 그 job 을 FAILED 로 끝낸다. 그래서 우리 쪽에서 먼저 건다 — 스트림이 분석을 죽이면 안 된다.
class AnalysisStageDefinition(ContractModel):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{1,79}$")
    label: str = Field(min_length=1, max_length=80)      # 눈썹 문구
    role: str = Field(min_length=1, max_length=120)      # 제목 — 에이전트 이름이 들어갈 자리
    message: str = Field(min_length=1, max_length=500)
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")


class AnalysisStageUpdate(ContractModel):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{1,79}$")
    status: Literal["PENDING", "RUNNING", "WAITING", "COMPLETED", "FAILED"]
    message: str = Field(default="", max_length=1_000)   # 툴 호출·관찰이 들어갈 자리


class AnalysisStreamEvent(ContractModel):
    """한 줄 = 한 이벤트. 첫 줄은 RUN_STARTED, 마지막 줄은 RESULT 또는 ERROR."""

    type: Literal["RUN_STARTED", "STAGE_UPDATED", "RESULT", "ERROR"]
    run_id: UUID
    sequence: int = Field(ge=1, le=10_000)
    occurred_at: datetime
    stages: list[AnalysisStageDefinition] = Field(default_factory=list, max_length=12)
    stage: AnalysisStageUpdate | None = None
    result: AnalysisResponse | None = None
    error_code: str | None = Field(default=None, max_length=80)
    error_message: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def validate_payload(self) -> AnalysisStreamEvent:
        """타입별로 실려야 할 것만 싣는다 — 빈 RUN_STARTED 는 프론트의 계획을 지운다."""

        if self.type == "RUN_STARTED" and not self.stages:
            raise ValueError("RUN_STARTED requires at least one stage")
        if self.type == "STAGE_UPDATED" and self.stage is None:
            raise ValueError("STAGE_UPDATED requires a stage")
        if self.type == "RESULT" and self.result is None:
            raise ValueError("RESULT requires the analysis response")
        if self.type == "ERROR" and not (self.error_code or "").strip():
            raise ValueError("ERROR requires an error code")
        return self


class SharedPostingAnalysis(ContractModel):
    """같은 공고의 검증된 정규화 결과 — 계정 간 재사용(요청으로 들어온다)."""

    job: JobContext
    competency_proposal: CompetencyProposal


class AnalysisResponse(ContractModel):
    status: Literal["COMPLETED", "NEEDS_INPUT"]
    question: AnalysisQuestion | None = None
    job: JobContext | None = None
    evaluation: Evaluation | None = None
    change_proposal: ChangeProposal | None = None
    # 새 계약의 산출물. **COMPLETED 면 필수다** — 백엔드 워커가 이게 없으면 job 을 FAILED
    # 로 끝내므로, 없는 채로 COMPLETED 를 내보내는 것은 성공을 가장한 실패다. 만들지 못하면
    # 서비스가 먼저 EngineFailed 로 알린다(무엇이 없었는지가 메시지에 남는다).
    competency_proposal: CompetencyProposal | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> AnalysisResponse:
        if self.status == "NEEDS_INPUT":
            if self.question is None:
                raise ValueError("NEEDS_INPUT responses require a question")
            if any(
                value is not None
                for value in (self.job, self.evaluation, self.change_proposal,
                              self.competency_proposal)
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


class ReplySource(ContractModel):
    """message 를 구성한 문장별 화자 — 오라우팅 디버깅용(엔진 ChatResponse.replySources 통과).

    channel: tool_render(도구 산출을 표현 계층이 렌더) / agent_llm(대화형 에이전트 직접 생성) /
    attachment_ack·lead·rule_note·consent_gate·notice(오케스트레이터 결정론 문장).
    """

    agent: str = Field(max_length=80)
    channel: str = Field(max_length=40)
    text: str = Field(default="", max_length=4_000)


class ProgressStep(ContractModel):
    """턴 내부 진행 단계 하나 — 어떤 에이전트/판정 노드가 언제 무엇을 했나(관찰용 타임라인)."""

    step: str = Field(max_length=80)
    label: str = Field(max_length=80)
    detail: str = Field(default="", max_length=300)
    elapsed_ms: int | None = None


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
    reply_sources: list[ReplySource] = Field(default_factory=list, max_length=20)
    progress: list[ProgressStep] = Field(default_factory=list, max_length=60)


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
