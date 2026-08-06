"""FastAPI router exposing career-pipeline operations from the single AI app.

This is a router, not a second application or process.  The legacy v3 URLs are
kept during the Spring migration so existing workers can move to the same base
URL before Java class names and transport DTOs are cleaned up.
"""

from __future__ import annotations

import logging
from queue import Queue
from threading import Thread

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from .assessment import AtomicCapabilityAssessmentService
from .capability_graph import HttpCapabilityGraphPort, UnavailableCapabilityGraphPort
from .cancellation import bind_analysis_job, cancel_analysis
from .config import Settings
from .contracts.assessment import (
    CapabilityAssessmentGrade,
    CapabilityAssessmentQuestion,
    CapabilityGradeRequest,
    CapabilityQuestionRequest,
)
from .contracts.errors import ErrorCode, ErrorDetail, ErrorEnvelope
from .contracts.pipeline import (
    AnalysisPipelineRequest,
    AnalysisPipelineResult,
    PipelineStreamEvent,
    PipelineStreamType,
)
from .contracts.progress import CapabilitiesResponse, CapabilityFlag, ProgressEvent
from .contracts.source import (
    SourceAcquisitionRequest,
    SourceDocument,
    SourceVerificationRequest,
    SourceVerificationResult,
)
from .fit import FitAnalysisService
from .interpretation import PostingInterpretationService
from .llm_adapter import StructuredGenerator
from .normalization import CapabilityNormalizationService
from .project_planning import ProjectPlanningService
from .resolution import PostingResolutionService
from .roadmap import RoadmapDraftService
from .service import AnalysisPipelineService
from .source import SourceAcquisitionService


LOGGER = logging.getLogger(__name__)
router = APIRouter()


class CareerPipelineRuntime:
    def __init__(self) -> None:
        settings = Settings.from_env()
        generator = StructuredGenerator()
        self.settings = settings
        self.source = SourceAcquisitionService(settings=settings)
        self.posting = PostingInterpretationService(generator)
        self.resolution = PostingResolutionService()
        self.fit = FitAnalysisService(generator)
        self.normalization = CapabilityNormalizationService(generator)
        self.project_planning = ProjectPlanningService(generator)
        self.roadmap = RoadmapDraftService(generator)
        self.assessment = AtomicCapabilityAssessmentService(generator)
        graph = (
            HttpCapabilityGraphPort(
                base_url=settings.capability_graph_url,
                shared_secret=settings.capability_graph_shared_secret,
                timeout_seconds=settings.capability_graph_timeout_seconds,
            )
            if settings.capability_graph_url
            else UnavailableCapabilityGraphPort()
        )
        self.pipeline = AnalysisPipelineService(
            posting_service=self.posting,
            resolution_service=self.resolution,
            fit_service=self.fit,
            normalization_service=self.normalization,
            project_planning_service=self.project_planning,
            graph_port=graph,
            roadmap_service=self.roadmap,
        )


runtime = CareerPipelineRuntime()


@router.get("/v1/capabilities", response_model=CapabilitiesResponse, response_model_by_alias=True)
def capabilities() -> CapabilitiesResponse:
    graph_ready = bool(runtime.settings.capability_graph_url)
    return CapabilitiesResponse(
        service_version="single-ai-career-pipeline-1.0.0",
        capabilities=[
            CapabilityFlag(name="CONTRACTS", available=True),
            CapabilityFlag(name="SOURCE_ACQUISITION", available=True),
            CapabilityFlag(name="POSTING_INTERPRETATION", available=True),
            CapabilityFlag(name="AMBIGUITY_RESOLUTION", available=True),
            CapabilityFlag(name="FIT_ANALYSIS", available=True),
            CapabilityFlag(name="CAPABILITY_NORMALIZATION", available=True),
            CapabilityFlag(
                name="CAPABILITY_GRAPH",
                available=graph_ready,
                reason=None if graph_ready else "CAPABILITY_GRAPH_URL is not configured",
            ),
            CapabilityFlag(
                name="ROADMAP_PROPOSAL",
                available=graph_ready,
                reason=None if graph_ready else "CAPABILITY_GRAPH_URL is not configured",
            ),
            CapabilityFlag(
                name="ANALYSIS_PIPELINE",
                available=graph_ready,
                reason=None if graph_ready else "CAPABILITY_GRAPH_URL is not configured",
            ),
            CapabilityFlag(name="ATOMIC_CAPABILITY_ASSESSMENT", available=True),
        ],
    )


@router.post("/v1/sources/acquire", response_model=SourceDocument, response_model_by_alias=True)
def acquire_source(request: SourceAcquisitionRequest) -> SourceDocument:
    return _call(lambda: runtime.source.acquire(request))


@router.post(
    "/v1/sources/{source_document_id}/verify",
    response_model=SourceVerificationResult,
    response_model_by_alias=True,
)
def verify_source(
    source_document_id: str,
    request: SourceVerificationRequest,
) -> SourceVerificationResult:
    if source_document_id != request.source_document.source_document_id:
        raise HTTPException(status_code=409, detail={
            "code": ErrorCode.CONTRACT_VALIDATION_FAILED,
            "message": "sourceDocumentId in path and body must match",
        })
    return _call(lambda: runtime.source.verify(request))


@router.post(
    "/v1/assessments/questions",
    response_model=CapabilityAssessmentQuestion,
    response_model_by_alias=True,
)
def assessment_question(request: CapabilityQuestionRequest) -> CapabilityAssessmentQuestion:
    return _call(lambda: runtime.assessment.question(request))


@router.post(
    "/v1/assessments/grade",
    response_model=CapabilityAssessmentGrade,
    response_model_by_alias=True,
)
def assessment_grade(request: CapabilityGradeRequest) -> CapabilityAssessmentGrade:
    return _call(lambda: runtime.assessment.grade(request))


@router.post(
    "/v1/analysis-pipeline/run",
    response_model=AnalysisPipelineResult,
    response_model_by_alias=True,
)
def run_pipeline(request: AnalysisPipelineRequest) -> AnalysisPipelineResult:
    return _call(lambda: runtime.pipeline.run(request))


@router.post("/v1/analysis-pipeline/stream")
def stream_pipeline(
    pipeline_request: AnalysisPipelineRequest,
    http_request: Request,
) -> StreamingResponse:
    queue: Queue[PipelineStreamEvent | object] = Queue()
    sentinel = object()
    last_sequence = 0

    def on_progress(progress: ProgressEvent) -> None:
        nonlocal last_sequence
        last_sequence = progress.sequence
        queue.put(PipelineStreamEvent(
            type=PipelineStreamType.PROGRESS,
            sequence=progress.sequence,
            progress=progress,
        ))

    def work() -> None:
        nonlocal last_sequence
        try:
            with bind_analysis_job(str(pipeline_request.job_id)):
                result = runtime.pipeline.run(pipeline_request, event_sink=on_progress)
            last_sequence += 1
            queue.put(PipelineStreamEvent(
                type=PipelineStreamType.RESULT,
                sequence=last_sequence,
                result=result,
            ))
        except Exception as exc:  # stream headers have already been sent
            LOGGER.exception("career pipeline failed (job_id=%s)", pipeline_request.job_id)
            last_sequence += 1
            queue.put(PipelineStreamEvent(
                type=PipelineStreamType.ERROR,
                sequence=last_sequence,
                error=_error_detail(exc, http_request),
            ))
        finally:
            queue.put(sentinel)

    def body():
        Thread(
            target=work,
            name=f"career-pipeline-{pipeline_request.job_id}",
            daemon=True,
        ).start()
        while True:
            item = queue.get()
            if item is sentinel:
                return
            assert isinstance(item, PipelineStreamEvent)
            yield item.model_dump_json(by_alias=True) + "\n"

    return StreamingResponse(
        body(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.post("/v1/analysis-pipeline/{job_id}/cancel")
def cancel_pipeline(job_id: str) -> dict[str, object]:
    return {
        "jobId": job_id,
        "cancelRequested": True,
        "activeProcessInterrupted": cancel_analysis(job_id),
    }


def _call(operation):
    try:
        return operation()
    except HTTPException:
        raise
    except Exception as exc:  # typed pipeline errors expose code/retryable
        detail = _error_detail(exc, None)
        status_code = 503 if detail.retryable else 422
        raise HTTPException(
            status_code=status_code,
            detail=ErrorEnvelope(error=detail).model_dump(mode="json", by_alias=True),
        ) from exc


def _error_detail(exc: Exception, request: Request | None) -> ErrorDetail:
    try:
        code = ErrorCode(getattr(exc, "code", ErrorCode.INTERNAL_ERROR))
    except ValueError:
        code = ErrorCode.INTERNAL_ERROR
    retryable = bool(getattr(exc, "retryable", False))
    message = _public_error_message(code, str(exc))
    return ErrorDetail(
        code=code,
        message=message,
        retryable=retryable,
        request_id=request.headers.get("X-Request-ID") if request else None,
        trace_id=request.headers.get("X-Trace-ID") if request else None,
    )


def _public_error_message(code: ErrorCode, raw_message: str) -> str:
    """Keep provider/model implementation details out of user-visible errors."""
    if code is ErrorCode.AI_PROVIDER_NOT_CONFIGURED:
        return "분석 엔진 설정을 확인해 주세요."
    if code is ErrorCode.AI_TIMEOUT:
        return "분석 에이전트의 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요."
    if code is ErrorCode.AI_PROVIDER_UNAVAILABLE:
        return "분석 엔진이 일시적으로 응답하지 않습니다. 잠시 후 다시 시도해 주세요."
    if code is ErrorCode.CAPABILITY_NOT_AVAILABLE:
        return "역량 지식 그래프에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요."
    if code is ErrorCode.INTERNAL_ERROR:
        return "커리어 분석을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요."
    return raw_message or "커리어 분석을 완료하지 못했습니다."
