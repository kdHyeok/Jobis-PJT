"""서비스 v2 백엔드 ↔ AI HTTP 계약 스키마.

**계약 정본은 백엔드 코드다** — `analysis/AiContracts.java`(역직렬화 대상),
`roadmap/RoadmapService`(그 값이 지도에서 무엇이 되는가), `db/migration/V10·V12`
(DB CHECK 이 거부하는 값), `frontend/src/types.ts`(화면이 기대하는 형태).

삭제된 실험용 계약 어댑터나 과거 문서는 정본이 아니다. 어긋나면 백엔드 코드와 DB/프론트
소비 계약을 따른다.

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
    """비어 있는 칸(None)을 직렬화에서 **아예 뺀다** — `"profile": null` 로 내지 않는다.

    백엔드 Jackson 은 `JsonNode` 칸의 JSON null 을 Java null 이 아니라 `NullNode` 로 읽어
    `!= null` 가드를 통과시킨다. 실측(08-03, ⓐ 첫 실경로): `collected.outputs.profile: null`
    이 그 가드를 지나 `ai_user_profiles` 에 null 을 넣다 `ai_user_profile_shape_check` 에
    걸렸고, **같은 트랜잭션의 블롭(session_state) 적재까지 통째로 굴러떨어졌다.**
    "그 턴에 만들어진 것만 온다"는 계약이므로 없는 칸은 키 자체가 없는 것이 맞다.
    """

    @model_serializer(mode="wrap")
    def _omit_nulls(self, handler):
        return {k: v for k, v in handler(self).items() if v is not None}


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
    # URL 공고에서 **우리가 수집한 원문**. 백엔드는 주소만 받은 공고의 raw_text 를 이걸로
    # 되메운다 — 안 그러면 채용공고 페이지의 "원문" 칸이 영영 주소로 남는다.
    # `parsedData.rawChunks` 로는 안 된다: 파서가 상태 비대화 방지로 비운다(read_nodes).
    # 원문을 그대로 받은 공고에서는 None — 백엔드가 이미 갖고 있다.
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


class StoredResume(ContractModel):
    """백엔드 `career_sources` 한 행 — 사용자가 등록한 이력서 원문.

    **무상태 전환의 첫 조각**(0803-무상태-전환-계획 §2-1): 지금까지 이력서 원문과 그 라이브러리는
    AI 세션(SQLite)에만 살아 있었다. 백엔드가 이미 `career_sources` 에 갖고 있는 것을 턴마다
    실어 보내면, 세션 파일이 없어도 같은 대화를 이어갈 수 있다.
    """

    id: UUID | None = None
    # **null 을 받는다.** 백엔드 `career_sources.title` 은 nullable 이고, 우리가 non-null 로
    # 선언하면 요청 전체가 422 로 거부된다(extra=forbid 와 같은 계열의 사고 — 실측 08-03:
    # 대화가 통째로 실패했다). 받는 쪽은 넉넉하게, 쓰는 쪽에서 기본값을 준다.
    title: str | None = Field(default=None, max_length=200)
    source_type: str | None = Field(default="TEXT", max_length=20)
    raw_text: str = Field(min_length=1, max_length=100_000)
    created_at: datetime | None = None


class StoredPosting(ContractModel):
    """백엔드 `job_postings` 한 행 — 이 대화에서 다룬 공고.

    `parsed_data` 는 파서 산출(normalizedJobPosting)이다. 있으면 AI 가 다시 파싱하지 않는다
    (무상태 전환 §2-3) — 없으면 원문만 받아 첫 소비자가 파싱한다.
    """

    id: UUID | None = None
    source_type: str | None = Field(default="TEXT", max_length=20)
    source_url: str | None = None
    raw_text: str = Field(min_length=1, max_length=100_000)
    # **null 을 받는다** — `job_postings.parsed_data` 는 파싱 전이면 비어 있다(nullable).
    parsed_data: dict[str, Any] | None = None
    created_at: datetime | None = None


class CareerSummary(ContractModel):
    completed_nodes: list[str] = Field(default_factory=list, max_length=200)
    active_goals: list[str] = Field(default_factory=list, max_length=100)
    recent_postings: list[str] = Field(default_factory=list, max_length=50)
    saved_evidence: list[str] = Field(default_factory=list, max_length=200)
    # 등록된 이력서 원문들 — 최신이 앞. 첫 항목이 활성 이력서가 된다.
    # 없으면(백엔드가 아직 안 보내면) 종전대로 위 확정 항목을 줄글로 이어 원천으로 쓴다.
    resumes: list[StoredResume] = Field(default_factory=list, max_length=5)
    # 대화로 수집해 **적재해 둔** 선호·지속 사실을 되돌려 받는다(`user_goal_profiles`).
    # 올려 보내기만 하고 받지 않으면(V22 직후 상태) 다음 턴이 세션 파일에 의존한다.
    preferences: dict[str, list[str]] | None = None
    facts: list[str] = Field(default_factory=list, max_length=200)
    # 이 대화에서 다룬 공고들 — 최신이 앞. 첫 항목이 활성 공고가 된다(§2-3).
    postings: list[StoredPosting] = Field(default_factory=list, max_length=5)
    # **자산 블롭 — 진실의 출처**(ⓐ, D152). 직전 턴 응답의 `collected.outputs.session_state`
    # 를 백엔드가 `agent_session_state.state` 에 저장했다가 그대로 되돌려준다. AI 는 이것을
    # 번역 없이 세션으로 복원한다 — 저장소가 없어도 대화 맥락 전체가 선다.
    session_state: dict[str, Any] | None = None
    # 여러 턴에 걸친 면접 진행 상태(`interview_sessions.state`) — 대화 이력 재파싱보다 정직하다.
    interview: dict[str, Any] | None = None


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

    # 화자 키(에이전트 이름 또는 "orchestrator"). 웹이 이 키로 색·로고를 고른다 —
    # label 은 다듬을 수 있는 문구라 화면 식별자로 쓸 수 없다.
    agent: str = Field(default="", max_length=40)
    step: str = Field(max_length=80)
    label: str = Field(max_length=80)
    detail: str = Field(default="", max_length=300)
    elapsed_ms: int | None = None
    # 에이전트가 완성한 **사용자향 발화 본문**(D153) — 담당이 말을 마치는 즉시(agent_end)
    # 화면이 말풍선으로 그릴 수 있게 스트림에 싣는다. 과정 라벨(detail)과 달리 이건 내용이라
    # 자르지 않고 답변 상한(4000)을 그대로 쓴다. 발화가 없는 단계는 빈 문자열.
    message: str = Field(default="", max_length=4000)


class CollectedPosting(ContractModel):
    """대화에서 확보한 공고 — 백엔드 `job_postings` 한 행의 재료 (D141).

    `raw_text` 는 **주소가 아니라 원문**이다. URL 로 받았으면 `posting_fetch` 가 수집한 본문이
    들어간다 — 백엔드가 이걸 그대로 저장해야 사이드바 채용공고 페이지에 내용이 보인다.

    **파싱 결과는 싣지 않는다.** `company_name`·`parsed_data` 같은 칸을 여기 두면 그 열의
    writer 가 둘이 된다 — `AnalysisWorker.complete` 가 이미 분석 결과로 그 열들을 채우는
    유일한 자리다. 우리가 낼 것은 그 앞에 없던 것, 즉 **원문**뿐이다.
    """

    source_type: Literal["URL", "TEXT"]
    source_url: str | None = None
    raw_text: str = Field(min_length=1, max_length=100_000)


class CollectedResume(ContractModel):
    """대화에서 확보한 이력서 원문 — 백엔드 `career_sources` 한 행의 재료 (D141).

    **백엔드가 요청에 실어 보낸 확정 커리어 요약은 여기 담지 않는다** — 자기가 준 것을
    되받아 다시 적재하면 같은 이력이 매 턴 늘어난다.
    """

    source_type: Literal["TEXT"] = "TEXT"
    title: str = Field(min_length=1, max_length=200)
    raw_text: str = Field(min_length=1, max_length=100_000)


class CollectedOutputs(OmitNullsModel):
    """이 턴에 에이전트가 **만든** 것들 — 백엔드가 자기 테이블에 적재한다(V23).

    확보한 자산(`CollectedAssets`)과 갈라 두는 이유: 저쪽은 사용자가 준 것(공고·이력서)이고
    이쪽은 대화가 만든 산출물이다. 목적지도 다르다(§1 대응표).

    전부 optional 이다 — 그 턴에 만들어진 것만 실린다. 매 턴 전량을 보내면 백엔드가 같은
    산출물을 계속 다시 쓴다.
    """

    # analysis_jobs.engine_result — 엔진 형식 판정(fitGrade·gaps·roadmap). v2 형식(result_data)의 짝
    analysis: dict[str, Any] | None = None
    # 준비 로드맵 — 판정과 같은 행(engine_result)에 들어간다
    roadmap: list[dict[str, Any]] | None = Field(default=None, max_length=50)
    judgment_summary: dict[str, Any] | None = None
    # ai_user_profiles.profile — 이력서에서 뽑은 정규화 프로필(파생 캐시)
    profile: dict[str, Any] | None = None
    # posting_recommendations.recommendations
    recommendations: list[dict[str, Any]] | None = Field(default=None, max_length=20)
    # coverletter_drafts.draft — 항상 draft_pending_review (§2-8: 최종 확정은 사람)
    coverletter: dict[str, Any] | None = None
    # interview_sessions.state — {asked, answers, usedTopics}
    interview: dict[str, Any] | None = None
    # application_plans.plan — {decision, routes}
    application_plan: dict[str, Any] | None = None
    # user_goal_profiles 의 준비 예산
    preparation_period_weeks: int | None = Field(default=None, ge=1, le=260)
    available_hours_per_week: int | None = Field(default=None, ge=1, le=168)
    # agent_session_state.state — **세션 자산 전체**(진실의 출처 블롭, ⓐ D152). 무엇이든
    # 바뀐 턴에 통째로 실린다. 백엔드는 그대로 upsert 하고 다음 요청 sessionState 로 돌려준다.
    session_state: dict[str, Any] | None = None
    # **지도 재료** — 대화가 쌓은 자산으로 만든 것. 백엔드가 user_competencies ·
    # posting_competency_requirements · posting_target_projects 로 적재하고, 그 뒤
    # 지도가 자동으로 그려진다(D146). 판정이 이번 턴에 새로 난 경우에만 실린다.
    competency_proposal: CompetencyProposal | None = None
    # 지도 재료의 짝 — **공고 맥락**(경력 관문·트랙·마감). 백엔드가 competency_proposal 을
    # 공용 분석 캐시로 저장할 때 job 칸을 이걸로 채운다. 없으면 백엔드는 아직 파싱 전인
    # job_postings 열로 job 을 지어내는데, experienceRequirement·primaryTrack 이 비어
    # 재사용 경로가 죽는다(실측 08-04: NPE 로 분석 job FAILED → 지도 미생성).
    job_context: JobContext | None = None


class CollectedAssets(OmitNullsModel):
    """이 턴에 **새로** 확보한 자산. 없으면 응답에서 생략된다.

    왜 필요한가(D141): 사용자가 채팅에 URL 을 붙이면 AI 는 수집·파싱·판정까지 하는데
    백엔드는 그 공고를 모른다 — `ConversationService` 는 공고 첨부 UI 경로에서만 공고를
    만들고 `ChatRequest` 는 `role`·`content` 만 싣는다. 그래서 대화로 준 공고는 채용공고
    페이지에도, 커리어지도에도 나타나지 않았다(실측 08-03: 세션의 공고가 `job_postings` 에
    없었다). **AI 세션은 캐시이고 진실의 출처는 백엔드 테이블이다.**

    매 턴 싣지 않는다 — 자산이 이번 턴에 승격·수집된 사실이 있을 때만이다. 같은 원문을
    턴마다 돌려보내면 백엔드가 같은 공고를 계속 다시 만든다.
    """

    posting: CollectedPosting | None = None
    resume: CollectedResume | None = None
    # 이 턴에 에이전트가 만든 산출물 — 목적지가 자산과 다르다(V23 테이블들).
    outputs: CollectedOutputs | None = None
    # 대화로 수집한 공고 선호 {roles, domains, companies, regions, techStack} — 이번 턴에
    # 바뀌었을 때만. 백엔드 `user_goal_profiles.chat_preferences` 자리(전량 upsert).
    preferences: dict[str, list[str]] | None = None
    # 사용자가 직접 말한 지속 사실 — 이번 턴에 늘었을 때만. `user_goal_profiles.chat_facts`.
    # **누적 전량**을 싣는다: 백엔드가 갖고 있는 것을 우리가 모르므로 차분을 낼 수 없고,
    # 전량 upsert 는 멱등이다(같은 것을 두 번 보내도 행이 늘지 않는다).
    facts: list[str] | None = Field(default=None, max_length=200)


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
    # 이 답변이 **결정론 폴백**이면 그 이유. 비어 있으면 정상 답변이다.
    #
    # 폴백이 그럴듯해서 실패가 안 보인 사고가 반복됐다(2026-07-29 자기 루프 전멸,
    # 2026-08-03 posting_analysis 형식 위반). 경고는 응답 객체에만 실려 아무도 안 읽었고,
    # 사용자는 요약본을 분석 결과로 읽었다. 사용자에게 보이는 자리에 사실을 실어 보낸다.
    degraded_reason: str = Field(default="", max_length=300)
    suggested_actions: list[SuggestedAction] = Field(default_factory=list, max_length=3)
    reply_sources: list[ReplySource] = Field(default_factory=list, max_length=20)
    progress: list[ProgressStep] = Field(default_factory=list, max_length=60)
    # 이 턴에 확보한 자산 → 백엔드가 자기 테이블에 적재한다 (D141). 백엔드가 이 칸을 읽지
    # 않으면 아무 일도 일어나지 않는다(추가만 하는 변경).
    collected: CollectedAssets | None = None


# ---------------------------------------------------------------------------
# 역량 검증 (`POST /v1/competency-assessments`)
# ---------------------------------------------------------------------------
AssessmentKind = Literal["CONCEPT", "CODE", "SCENARIO", "FOLLOW_UP"]


class AssessmentCompetency(ContractModel):
    canonical_key: str
    title: str = Field(min_length=1, max_length=160)
    domain: str
    scope_definition: str = Field(min_length=1, max_length=4_000)
    required_level: int = Field(ge=1, le=5)
    level_definition: dict[str, Any] = Field(default_factory=dict)
    assessment_blueprint: dict[str, Any] = Field(default_factory=dict)


class AssessmentTargetContext(ContractModel):
    """문제를 개인화할 맥락. **회사 내부 사실을 지어내는 근거가 아니다.**"""

    company_name: str | None = None
    role_title: str | None = None
    primary_track: str | None = None
    domain_context: str | None = None
    requirement_source: str | None = None
    current_goal: str | None = None
    final_goal: str | None = None


class AssessmentTurn(ContractModel):
    ordinal: int = Field(ge=1)
    question_kind: AssessmentKind
    prompt: str
    code_snippet: str | None = None
    answer_text: str | None = None
    score: int | None = Field(default=None, ge=0, le=100)
    feedback: str | None = None


class CompetencyAssessmentRequest(ContractModel):
    session_id: UUID
    competency: AssessmentCompetency
    target: AssessmentTargetContext = Field(default_factory=AssessmentTargetContext)
    turns: list[AssessmentTurn] = Field(default_factory=list, max_length=20)
    retained_scores: dict[str, int] = Field(default_factory=dict)
    required_question_kind: AssessmentKind | None = None


class AssessmentQuestion(ContractModel):
    kind: AssessmentKind
    prompt: str = Field(min_length=1, max_length=4_000)
    code_snippet: str | None = Field(default=None, max_length=4_000)
    # 이 문제로 확인할 **현재 노드의 통과 기준**. 인접 기술·장기 목표는 여기 넣지 않는다.
    core_criteria: list[str] = Field(default_factory=list, max_length=10)
    future_extensions: list[str] = Field(default_factory=list, max_length=10)


class AssessmentAnswerEvaluation(ContractModel):
    score: int = Field(ge=0, le=100)
    verdict: Literal["PASS", "PARTIAL", "FAIL"]
    feedback: str = Field(min_length=1, max_length=2_000)
    covered_criteria: list[str] = Field(default_factory=list, max_length=10)
    gaps: list[str] = Field(default_factory=list, max_length=10)
    future_extensions: list[str] = Field(default_factory=list, max_length=10)


class CompetencyAssessmentResponse(ContractModel):
    answer_evaluation: AssessmentAnswerEvaluation | None = None
    next_question: AssessmentQuestion | None = None
    session_summary: str = Field(min_length=1, max_length=2_000)
    strengths: list[str] = Field(default_factory=list, max_length=10)
    gaps: list[str] = Field(default_factory=list, max_length=10)
    next_actions: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def validate_outcome(self) -> CompetencyAssessmentResponse:
        """채점도 다음 문제도 없으면 이 응답으로 화면이 할 수 있는 일이 없다."""

        if self.answer_evaluation is None and self.next_question is None:
            raise ValueError(
                "assessment responses require an evaluation or the next question")
        return self


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
