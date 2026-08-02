"""백엔드 ↔ AI 서버 요청/응답 계약 (설계 15.2 / 15.3).

POST /api/v1/analyze
- 요청: AnalyzeRequest
- 응답: AnalyzeResponse
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    """공고 입력 소스 종류 (설계 8.3)."""

    url = "url"
    text = "text"
    file = "file"


class JobPostingInput(BaseModel):
    """목표 채용공고 입력."""

    sourceType: SourceType
    value: str


class AnalyzeOptions(BaseModel):
    """분석 옵션."""

    includeAlternatives: bool = False


class AnalyzeRequest(BaseModel):
    """백엔드 → AI 서버 요청 (설계 15.2)."""

    userId: int
    jobPostingInput: JobPostingInput
    selectedExperienceIds: list[int] = Field(default_factory=list)
    preparationPeriodWeeks: int
    availableHoursPerWeek: int
    options: AnalyzeOptions = Field(default_factory=AnalyzeOptions)
    # need_more_info 재개 시 기존 분석을 이어가기 위해 전달 (설계 15.3)
    analysisId: Optional[str] = None


AnalysisStatus = Literal["completed", "need_more_info", "failed"]


# ---------------------------------------------------------------------------
# 대화 진입 계약 (개선방안 Phase 2-4) — POST /api/v1/chat
# 기존 /analyze 계약은 그대로 유지하고, 대화 경로는 별도 계약으로 연다.
# ---------------------------------------------------------------------------
class ChatAttachment(BaseModel):
    """대화에 첨부되는 세션 자산 (이력서 또는 목표 공고).

    resume_extra 는 **기존 이력서에 덧붙이는** 추가 정보다(빈 섹션 보완 입력 등) —
    resume 처럼 통째로 교체하면 방금 준 몇 줄이 이력서 전체를 지워버린다.
    """

    kind: Literal["resume", "job_posting", "resume_extra"]
    sourceType: SourceType
    value: str


class ChatRequest(BaseModel):
    """사용자 대화 한 턴."""

    sessionId: str
    message: str = ""
    attachments: list[ChatAttachment] = Field(default_factory=list)


class ChatResponse(BaseModel):
    """오케스트레이터 응답. intent/dispatched 는 라우팅 가시화용 —
    사용자(프론트)가 오라우팅을 확인·정정할 수 있게 그대로 노출한다."""

    sessionId: str
    reply: str
    intent: str = ""
    confidence: Optional[float] = None
    dispatched: list[str] = Field(default_factory=list)
    # 에이전트 이름 → 구조화 산출물 (판정 결과는 가공 없이 그대로 전달)
    results: dict[str, dict] = Field(default_factory=dict)
    followUpQuestions: list[dict] = Field(default_factory=list)
    warnings: list[dict] = Field(default_factory=list)
    # reply 를 구성한 문장별 화자 — {agent, channel, text}. channel 은 tool_render(도구 산출을
    # 표현 계층이 렌더) / agent_llm(대화형 에이전트가 직접 생성) / 오케스트레이터 계열
    # (attachment_ack·lead·rule_note·consent_gate·notice). 오라우팅 디버깅용으로 그대로 노출한다.
    replySources: list[dict] = Field(default_factory=list)


class ResponseMeta(BaseModel):
    """응답 메타데이터."""

    retriedNodes: list[str] = Field(default_factory=list)
    generatedAt: str
    modelVersion: str = ""


class AnalyzeResponse(BaseModel):
    """AI 서버 → 백엔드 응답 (설계 15.3).

    status 가 need_more_info 이면 백엔드는 followUpQuestions 를 사용자에게 노출하고,
    답을 모아 analysisId 와 함께 같은 엔드포인트로 재요청한다.
    """

    analysisId: str
    status: AnalysisStatus
    # 분석 결과를 사람이 읽는 한 문단으로 요약한 것 (nl_render 산출, 설계 §3.9).
    # 기본값이 있는 추가 필드라 기존 소비자는 무시해도 된다.
    summary: str = ""
    # 종합 적합도 등급과 점수 (2026-07-21). fitGrade: "상"|"중"|"하"|"판정불가".
    # 상이면 진단만, 중·하면 로드맵·대안까지 제공한다. 계산 근거가 없으면 "판정불가"/None.
    # 기본값이 있는 추가 필드라 기존 소비자는 무시해도 된다.
    fitGrade: str = ""
    overallScore: Optional[float] = None
    requirements: list[dict] = Field(default_factory=list)
    strengths: list[dict] = Field(default_factory=list)
    gaps: list[dict] = Field(default_factory=list)
    roadmap: list[dict] = Field(default_factory=list)
    alternativeJobs: list[dict] = Field(default_factory=list)
    followUpQuestions: list[dict] = Field(default_factory=list)
    # docx 에서 못 뽑은 enum 필드(degree/status/employmentType/projectType) 보완 질문.
    # **비블로킹** — followUpQuestions 와 달리 status 를 need_more_info 로 바꾸지 않는다.
    # 기본값이 있는 추가 필드라 기존 소비자는 무시해도 된다.
    profileCompletionQuestions: list[dict] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)
    warnings: list[dict] = Field(default_factory=list)
    meta: ResponseMeta
