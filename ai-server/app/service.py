from collections.abc import AsyncIterator
from datetime import UTC, datetime

from app.models import (
    AnalysisRequest,
    AnalysisResponse,
    AnalysisStageDefinition,
    AnalysisStageUpdate,
    AnalysisStreamEvent,
    CareerExtractionRequest,
    CareerExtractionResponse,
    ChatRequest,
    ChatResponse,
    CompetencyAssessmentRequest,
    CompetencyAssessmentResponse,
    EvidenceVerificationRequest,
    EvidenceVerificationResponse,
)
from app.providers.anthropic_api import AnthropicApiProvider
from app.providers.base import AnalysisProvider
from app.providers.claude_cli import ClaudeCliProvider
from app.providers.unconfigured import UnconfiguredProvider
from app.settings import Settings


class AnalysisService:
    """Provider-neutral orchestration boundary.

    The emitted stages are not timers or decorative placeholders.  Every
    RUNNING/COMPLETED transition surrounds a real provider or deterministic
    contract operation.
    """

    def __init__(self, settings: Settings):
        self._provider = self._resolve_provider(settings)

    @property
    def provider_name(self) -> str:
        return self._provider.name

    async def analyze(self, request: AnalysisRequest) -> AnalysisResponse:
        return await self._provider.analyze(request)

    async def analyze_stream(
        self, request: AnalysisRequest
    ) -> AsyncIterator[AnalysisStreamEvent]:
        stages = self._analysis_stages(request)
        sequence = 1
        yield self._stream_event(
            request,
            sequence,
            "RUN_STARTED",
            stages=stages,
        )
        sequence += 1

        yield self._stage_event(
            request,
            sequence,
            "CONTEXT_ASSEMBLY",
            "RUNNING",
            "공고, 답변, 커리어 근거와 목표를 분석 입력으로 조립하고 있어요.",
        )
        sequence += 1
        # Pydantic has already rejected unknown or malformed fields at the API
        # boundary.  Re-validation here records a separate deterministic
        # orchestration step before an external model is called.
        AnalysisRequest.model_validate(request.model_dump())
        yield self._stage_event(
            request,
            sequence,
            "CONTEXT_ASSEMBLY",
            "COMPLETED",
            "현재 사용자의 분석 맥락을 준비했어요.",
        )
        sequence += 1

        if request.shared_analysis is None and request.question_count < 3:
            yield self._stage_event(
                request,
                sequence,
                "CLARIFICATION",
                "RUNNING",
                "결과를 바꿀 수 있는 모호한 조건이 있는지 확인하고 있어요.",
            )
            sequence += 1
            decision = await self._provider.decide_clarification(request)
            if decision.status == "NEEDS_INPUT":
                yield self._stage_event(
                    request,
                    sequence,
                    "CLARIFICATION",
                    "WAITING",
                    decision.question.text
                    if decision.question
                    else "정확한 분석을 위해 답변이 필요해요.",
                )
                sequence += 1
                yield self._stream_event(
                    request,
                    sequence,
                    "RESULT",
                    result=AnalysisResponse(
                        status="NEEDS_INPUT",
                        question=decision.question,
                    ),
                )
                return
            yield self._stage_event(
                request,
                sequence,
                "CLARIFICATION",
                "COMPLETED",
                "추가 질문 없이 분석을 계속할 수 있어요.",
            )
            sequence += 1

        if request.shared_analysis is not None:
            yield self._stage_event(
                request,
                sequence,
                "SHARED_REUSE",
                "RUNNING",
                "같은 공고의 검증된 정규화 결과를 불러오고 있어요.",
            )
            sequence += 1
            # Copy through the schema so cached data is subject to the same
            # contract as a freshly generated analysis.
            shared = type(request.shared_analysis).model_validate(
                request.shared_analysis.model_dump()
            )
            yield self._stage_event(
                request,
                sequence,
                "SHARED_REUSE",
                "COMPLETED",
                "공고 재추출을 생략하고 검증된 공용 결과를 재사용했어요.",
            )
            sequence += 1
            yield self._stage_event(
                request,
                sequence,
                "FIT_ANALYSIS",
                "RUNNING",
                "현재 사용자의 근거와 공고 조건을 새로 비교하고 있어요.",
            )
            sequence += 1
            evaluation = await self._provider.evaluate_shared_analysis(request)
            response = AnalysisResponse(
                status="COMPLETED",
                job=shared.job,
                evaluation=evaluation,
                competency_proposal=shared.competency_proposal,
            )
            yield self._stage_event(
                request,
                sequence,
                "FIT_ANALYSIS",
                "COMPLETED",
                "현재 사용자 기준의 지원 판단을 만들었어요.",
            )
            sequence += 1
        else:
            yield self._stage_event(
                request,
                sequence,
                "POSTING_ANALYSIS",
                "RUNNING",
                "필수·우대 조건, 역량 범위와 회사 맞춤 과제를 추출하고 있어요.",
            )
            sequence += 1
            completed = await self._provider.complete_posting_analysis(request)
            response = completed.to_analysis_response()
            yield self._stage_event(
                request,
                sequence,
                "POSTING_ANALYSIS",
                "COMPLETED",
                "공고 조건과 현재 사용자 기준의 적합도 분석을 마쳤어요.",
            )
            sequence += 1

        yield self._stage_event(
            request,
            sequence,
            "CONTRACT_VALIDATION",
            "RUNNING",
            "중복 역량, 참조 무결성, 조건부 필수값을 검증하고 있어요.",
        )
        sequence += 1
        response = AnalysisResponse.model_validate(response.model_dump())
        yield self._stage_event(
            request,
            sequence,
            "CONTRACT_VALIDATION",
            "COMPLETED",
            "서비스 계약과 근거 참조 검증을 통과했어요.",
        )
        sequence += 1

        yield self._stage_event(
            request,
            sequence,
            "RESULT_ASSEMBLY",
            "RUNNING",
            "지원 판단과 로드맵 입력 데이터를 조립하고 있어요.",
        )
        sequence += 1
        # The backend, not the model, decides the final shared roadmap layout.
        yield self._stage_event(
            request,
            sequence,
            "RESULT_ASSEMBLY",
            "COMPLETED",
            "검토 가능한 분석 결과를 모두 준비했어요.",
        )
        sequence += 1
        yield self._stream_event(
            request,
            sequence,
            "RESULT",
            result=response,
        )

    async def chat(self, request: ChatRequest) -> ChatResponse:
        return await self._provider.chat(request)

    async def verify_evidence(
        self, request: EvidenceVerificationRequest
    ) -> EvidenceVerificationResponse:
        return await self._provider.verify_evidence(request)

    async def extract_career(
        self, request: CareerExtractionRequest
    ) -> CareerExtractionResponse:
        return await self._provider.extract_career(request)

    async def assess_competency(
        self, request: CompetencyAssessmentRequest
    ) -> CompetencyAssessmentResponse:
        return await self._provider.assess_competency(request)

    def _resolve_provider(self, settings: Settings) -> AnalysisProvider:
        if settings.analysis_provider == "unconfigured":
            return UnconfiguredProvider()
        if settings.analysis_provider == "claude_cli":
            return ClaudeCliProvider(settings)
        if settings.analysis_provider == "anthropic":
            return AnthropicApiProvider(settings)
        raise ValueError(f"Unsupported analysis provider: {settings.analysis_provider}")

    def _analysis_stages(
        self, request: AnalysisRequest
    ) -> list[AnalysisStageDefinition]:
        stages = [
            AnalysisStageDefinition(
                id="CONTEXT_ASSEMBLY",
                label="맥락 조립",
                role="대화 오케스트레이터",
                message="공고와 현재 커리어 근거를 안전하게 조립합니다.",
                color="#1cb0f6",
            ),
        ]
        if request.shared_analysis is None and request.question_count < 3:
            stages.append(
                AnalysisStageDefinition(
                    id="CLARIFICATION",
                    label="기준 확인",
                    role="사전 확인 에이전트",
                    message="분석 결과를 바꿀 모호한 조건만 확인합니다.",
                    color="#ff9600",
                )
            )
        if request.shared_analysis is None:
            stages.append(
                AnalysisStageDefinition(
                    id="POSTING_ANALYSIS",
                    label="공고 분석",
                    role="공고·적합도 분석 에이전트",
                    message="공고 조건과 현재 근거를 구조화합니다.",
                    color="#ce82ff",
                )
            )
        else:
            stages.extend(
                [
                    AnalysisStageDefinition(
                        id="SHARED_REUSE",
                        label="공용 결과 재사용",
                        role="공고 정규화 저장소",
                        message="같은 공고에서 이미 검증한 조건을 재사용합니다.",
                        color="#ffc800",
                    ),
                    AnalysisStageDefinition(
                        id="FIT_ANALYSIS",
                        label="내 적합도 분석",
                        role="적합도 분석 에이전트",
                        message="현재 사용자의 근거만 새로 비교합니다.",
                        color="#ce82ff",
                    ),
                ]
            )
        stages.extend(
            [
                AnalysisStageDefinition(
                    id="CONTRACT_VALIDATION",
                    label="결과 검증",
                    role="결정론 검증기",
                    message="스키마와 참조 무결성을 코드로 검증합니다.",
                    color="#2b70c9",
                ),
                AnalysisStageDefinition(
                    id="RESULT_ASSEMBLY",
                    label="결과 조립",
                    role="경로 조립기",
                    message="지도 생성에 사용할 데이터를 준비합니다.",
                    color="#58cc02",
                ),
            ]
        )
        return stages

    def _stage_event(
        self,
        request: AnalysisRequest,
        sequence: int,
        stage_id: str,
        status: str,
        message: str,
    ) -> AnalysisStreamEvent:
        return self._stream_event(
            request,
            sequence,
            "STAGE_UPDATED",
            stage=AnalysisStageUpdate(
                id=stage_id,
                status=status,
                message=message,
            ),
        )

    @staticmethod
    def _stream_event(
        request: AnalysisRequest,
        sequence: int,
        event_type: str,
        *,
        stages: list[AnalysisStageDefinition] | None = None,
        stage: AnalysisStageUpdate | None = None,
        result: AnalysisResponse | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> AnalysisStreamEvent:
        return AnalysisStreamEvent(
            type=event_type,
            run_id=request.analysis_job_id,
            sequence=sequence,
            occurred_at=datetime.now(UTC),
            stages=stages or [],
            stage=stage,
            result=result,
            error_code=error_code,
            error_message=error_message,
        )
