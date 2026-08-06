from __future__ import annotations

import hmac
import logging
from collections.abc import Mapping
from queue import Queue
from threading import Thread
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from .config import Settings
from .contracts.common import CONTRACT_VERSION
from .contracts.assessment import (
    CapabilityAssessmentGrade,
    CapabilityAssessmentQuestion,
    CapabilityGradeRequest,
    CapabilityQuestionRequest,
)
from .contracts.errors import ErrorCode, ErrorDetail, ErrorEnvelope
from .contracts.fit import (
    FitAnalysisRequest,
    FitAnalysisResult,
    FitAssessment,
    RequirementAssessment,
    UserCompetencyEvidence,
)
from .contracts.posting import PostingInterpretationRequest, StructuredPosting
from .contracts.progress import CapabilitiesResponse, CapabilityFlag, ProgressEvent
from .contracts.project_planning import CompanyProjectBlueprint
from .contracts.roadmap import RoadmapDraftRequest, RoadmapProposal
from .contracts.source import (
    SourceAcquisitionRequest,
    SourceDocument,
    SourceVerificationRequest,
    SourceVerificationResult,
    VerifiedPostingSnapshot,
)
from .source import SourceAcquisitionFailure, SourceAcquisitionService
from .interpretation import PostingInterpretationFailure, PostingInterpretationService
from .llm import StructuredGenerator, build_json_provider
from .contracts.resolution import PostingResolutionRequest, PostingResolutionResult
from .resolution import AmbiguityResolutionFailure, PostingResolutionService
from .fit import FitAnalysisFailure, FitAnalysisService
from .contracts.normalization import CapabilityNormalizationRequest, CapabilityNormalizationResult
from .normalization import CapabilityNormalizationFailure, CapabilityNormalizationService
from .project_planning import ProjectPlanningService
from .roadmap import RoadmapDraftFailure, RoadmapDraftService
from .capability_graph import HttpCapabilityGraphPort, UnavailableCapabilityGraphPort
from .contracts.pipeline import (
    AnalysisPipelineRequest,
    AnalysisPipelineResult,
    PipelineStreamEvent,
    PipelineStreamType,
)
from .pipeline import AnalysisPipelineFailure, AnalysisPipelineService
from .assessment import AtomicCapabilityAssessmentService, AssessmentFailure
from .cancellation import bind_analysis_job, cancel_analysis


SERVICE_VERSION = "0.8.0"
LOGGER = logging.getLogger(__name__)


SCHEMA_MODELS: Mapping[str, type[BaseModel]] = {
    "source-document": SourceDocument,
    "source-acquisition-request": SourceAcquisitionRequest,
    "source-verification-request": SourceVerificationRequest,
    "source-verification-result": SourceVerificationResult,
    "verified-posting-snapshot": VerifiedPostingSnapshot,
    "structured-posting": StructuredPosting,
    "posting-interpretation-request": PostingInterpretationRequest,
    "user-competency-evidence": UserCompetencyEvidence,
    "requirement-assessment": RequirementAssessment,
    "fit-assessment": FitAssessment,
    "roadmap-proposal": RoadmapProposal,
    "company-project-blueprint": CompanyProjectBlueprint,
    "atomic-capability-assessment-question": CapabilityAssessmentQuestion,
    "atomic-capability-assessment-grade": CapabilityAssessmentGrade,
    "progress-event": ProgressEvent,
    "error-envelope": ErrorEnvelope,
}


class ApiContractException(Exception):
    def __init__(self, *, status_code: int, error: ErrorDetail) -> None:
        self.status_code = status_code
        self.error = error
        super().__init__(error.message)


def create_app(
    settings: Settings | None = None,
    source_service: SourceAcquisitionService | None = None,
    posting_service: PostingInterpretationService | None = None,
    resolution_service: PostingResolutionService | None = None,
    fit_service: FitAnalysisService | None = None,
    normalization_service: CapabilityNormalizationService | None = None,
    project_planning_service: ProjectPlanningService | None = None,
    roadmap_service: RoadmapDraftService | None = None,
    pipeline_service: AnalysisPipelineService | None = None,
    assessment_service: AtomicCapabilityAssessmentService | None = None,
) -> FastAPI:
    resolved = settings or Settings.from_env()
    application = FastAPI(
        title="JOBIS AI v3",
        version=SERVICE_VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json" if resolved.environment == "local" else None,
    )
    application.state.settings = resolved
    application.state.source_service = source_service or SourceAcquisitionService(settings=resolved)
    application.state.posting_service = posting_service or PostingInterpretationService(
        StructuredGenerator(
            build_json_provider(resolved),
            max_attempts=resolved.llm_max_attempts,
            initial_effort=resolved.llm_effort,
            retry_effort=resolved.llm_retry_effort,
        )
    )
    application.state.resolution_service = resolution_service or PostingResolutionService()
    application.state.fit_service = fit_service or FitAnalysisService(
        StructuredGenerator(
            build_json_provider(resolved),
            max_attempts=resolved.llm_max_attempts,
            initial_effort=resolved.llm_effort,
            retry_effort=resolved.llm_retry_effort,
        )
    )
    application.state.normalization_service = normalization_service or CapabilityNormalizationService(
        StructuredGenerator(
            build_json_provider(resolved),
            max_attempts=resolved.llm_max_attempts,
            initial_effort=resolved.llm_effort,
            retry_effort=resolved.llm_retry_effort,
        )
    )
    application.state.project_planning_service = (
        project_planning_service
        or ProjectPlanningService(
            StructuredGenerator(
                build_json_provider(resolved),
                max_attempts=resolved.llm_max_attempts,
                initial_effort=resolved.llm_effort,
                retry_effort=resolved.llm_retry_effort,
            )
        )
    )
    application.state.roadmap_service = roadmap_service or RoadmapDraftService(
        StructuredGenerator(
            build_json_provider(resolved),
            max_attempts=resolved.llm_max_attempts,
            initial_effort=resolved.llm_effort,
            retry_effort=resolved.llm_retry_effort,
        )
    )
    graph_port = (
        HttpCapabilityGraphPort(
            base_url=resolved.capability_graph_url,
            shared_secret=resolved.capability_graph_shared_secret,
            timeout_seconds=resolved.capability_graph_timeout_seconds,
        )
        if resolved.capability_graph_url
        else UnavailableCapabilityGraphPort()
    )
    application.state.pipeline_service = pipeline_service or AnalysisPipelineService(
        posting_service=application.state.posting_service,
        resolution_service=application.state.resolution_service,
        fit_service=application.state.fit_service,
        normalization_service=application.state.normalization_service,
        project_planning_service=application.state.project_planning_service,
        graph_port=graph_port,
        roadmap_service=application.state.roadmap_service,
    )
    application.state.assessment_service = assessment_service or AtomicCapabilityAssessmentService(
        StructuredGenerator(
            build_json_provider(resolved),
            max_attempts=resolved.llm_max_attempts,
            initial_effort=resolved.llm_effort,
            retry_effort=resolved.llm_retry_effort,
        )
    )

    @application.middleware("http")
    async def request_identity(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or f"request-{uuid4()}"
        trace_id = request.headers.get("X-Trace-ID") or f"trace-{uuid4()}"
        request.state.request_id = request_id
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Trace-ID"] = trace_id
        return response

    @application.exception_handler(ApiContractException)
    async def handle_contract_error(
        request: Request,
        exc: ApiContractException,
    ) -> JSONResponse:
        error = exc.error.model_copy(update={
            "request_id": exc.error.request_id or request.state.request_id,
            "trace_id": exc.error.trace_id or request.state.trace_id,
        })
        envelope = ErrorEnvelope(error=error)
        return JSONResponse(
            status_code=exc.status_code,
            content=envelope.model_dump(mode="json", by_alias=True),
        )

    @application.exception_handler(SourceAcquisitionFailure)
    async def handle_source_error(
        request: Request,
        exc: SourceAcquisitionFailure,
    ) -> JSONResponse:
        envelope = ErrorEnvelope(error=ErrorDetail(
            code=exc.code,
            message=str(exc),
            retryable=exc.retryable,
            request_id=request.state.request_id,
            trace_id=request.state.trace_id,
        ))
        status_code = 503 if exc.retryable else 422
        return JSONResponse(
            status_code=status_code,
            content=envelope.model_dump(mode="json", by_alias=True),
        )

    @application.exception_handler(PostingInterpretationFailure)
    async def handle_posting_error(
        request: Request,
        exc: PostingInterpretationFailure,
    ) -> JSONResponse:
        envelope = ErrorEnvelope(error=ErrorDetail(
            code=exc.code,
            message=str(exc),
            retryable=exc.retryable,
            request_id=request.state.request_id,
            trace_id=request.state.trace_id,
        ))
        status_code = 503 if exc.retryable or exc.code is ErrorCode.AI_PROVIDER_NOT_CONFIGURED else 422
        return JSONResponse(
            status_code=status_code,
            content=envelope.model_dump(mode="json", by_alias=True),
        )

    @application.exception_handler(AmbiguityResolutionFailure)
    async def handle_resolution_error(
        request: Request,
        exc: AmbiguityResolutionFailure,
    ) -> JSONResponse:
        envelope = ErrorEnvelope(error=ErrorDetail(
            code=exc.code,
            message=str(exc),
            retryable=exc.retryable,
            request_id=request.state.request_id,
            trace_id=request.state.trace_id,
        ))
        return JSONResponse(
            status_code=409,
            content=envelope.model_dump(mode="json", by_alias=True),
        )

    @application.exception_handler(FitAnalysisFailure)
    async def handle_fit_error(
        request: Request,
        exc: FitAnalysisFailure,
    ) -> JSONResponse:
        envelope = ErrorEnvelope(error=ErrorDetail(
            code=exc.code,
            message=str(exc),
            retryable=exc.retryable,
            request_id=request.state.request_id,
            trace_id=request.state.trace_id,
        ))
        status_code = 503 if exc.retryable or exc.code is ErrorCode.AI_PROVIDER_NOT_CONFIGURED else 422
        if exc.code is ErrorCode.ANALYSIS_STALE_RESULT:
            status_code = 409
        return JSONResponse(
            status_code=status_code,
            content=envelope.model_dump(mode="json", by_alias=True),
        )

    @application.exception_handler(CapabilityNormalizationFailure)
    async def handle_normalization_error(
        request: Request,
        exc: CapabilityNormalizationFailure,
    ) -> JSONResponse:
        envelope = ErrorEnvelope(error=ErrorDetail(
            code=exc.code,
            message=str(exc),
            retryable=exc.retryable,
            request_id=request.state.request_id,
            trace_id=request.state.trace_id,
        ))
        status_code = 503 if exc.retryable or exc.code is ErrorCode.AI_PROVIDER_NOT_CONFIGURED else 422
        return JSONResponse(
            status_code=status_code,
            content=envelope.model_dump(mode="json", by_alias=True),
        )

    @application.exception_handler(RoadmapDraftFailure)
    async def handle_roadmap_error(
        request: Request,
        exc: RoadmapDraftFailure,
    ) -> JSONResponse:
        envelope = ErrorEnvelope(error=ErrorDetail(
            code=exc.code,
            message=str(exc),
            retryable=exc.retryable,
            request_id=request.state.request_id,
            trace_id=request.state.trace_id,
        ))
        status_code = 503 if exc.retryable or exc.code is ErrorCode.AI_PROVIDER_NOT_CONFIGURED else 422
        return JSONResponse(
            status_code=status_code,
            content=envelope.model_dump(mode="json", by_alias=True),
        )

    @application.exception_handler(AnalysisPipelineFailure)
    async def handle_pipeline_error(
        request: Request,
        exc: AnalysisPipelineFailure,
    ) -> JSONResponse:
        envelope = ErrorEnvelope(error=ErrorDetail(
            code=exc.code,
            message=str(exc),
            retryable=exc.retryable,
            request_id=request.state.request_id,
            trace_id=request.state.trace_id,
        ))
        status_code = 503 if exc.retryable else 422
        return JSONResponse(
            status_code=status_code,
            content=envelope.model_dump(mode="json", by_alias=True),
        )

    @application.exception_handler(AssessmentFailure)
    async def handle_assessment_error(
        request: Request,
        exc: AssessmentFailure,
    ) -> JSONResponse:
        envelope = ErrorEnvelope(error=ErrorDetail(
            code=exc.code,
            message=str(exc),
            retryable=exc.retryable,
            request_id=request.state.request_id,
            trace_id=request.state.trace_id,
        ))
        status_code = 503 if exc.retryable or exc.code is ErrorCode.AI_PROVIDER_NOT_CONFIGURED else 422
        return JSONResponse(
            status_code=status_code,
            content=envelope.model_dump(mode="json", by_alias=True),
        )

    def require_internal_client(
        x_jobis_ai_secret: str | None = Header(default=None, alias="X-JOBIS-AI-SECRET"),
        x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
        x_jobis_ai_contract: str | None = Header(default=None, alias="X-JOBIS-AI-CONTRACT"),
    ) -> None:
        if x_jobis_ai_secret is None or not hmac.compare_digest(x_jobis_ai_secret, resolved.shared_secret):
            raise ApiContractException(
                status_code=401,
                error=ErrorDetail(
                    code=ErrorCode.UNAUTHORIZED_AI_CLIENT,
                    message="The internal AI client secret is missing or invalid.",
                    retryable=False,
                    request_id=x_request_id,
                ),
            )
        if x_jobis_ai_contract is not None and x_jobis_ai_contract != CONTRACT_VERSION:
            raise ApiContractException(
                status_code=409,
                error=ErrorDetail(
                    code=ErrorCode.UNSUPPORTED_CONTRACT_VERSION,
                    message=(
                        f"Unsupported AI contract {x_jobis_ai_contract}; "
                        f"expected {CONTRACT_VERSION}."
                    ),
                    retryable=False,
                    request_id=x_request_id,
                ),
            )

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "UP", "service": "jobis-ai-v3", "version": SERVICE_VERSION}

    @application.get("/v1/meta", dependencies=[Depends(require_internal_client)])
    def meta() -> dict[str, str]:
        return {
            "service": "jobis-ai-v3",
            "serviceVersion": SERVICE_VERSION,
            "contractVersion": CONTRACT_VERSION,
            "environment": resolved.environment,
        }

    @application.get(
        "/v1/capabilities",
        response_model=CapabilitiesResponse,
        response_model_by_alias=True,
        dependencies=[Depends(require_internal_client)],
    )
    def capabilities() -> CapabilitiesResponse:
        posting_available = (
            resolved.llm_provider in {"claude_code", "codex_cli"}
            or (resolved.llm_provider == "openai" and bool(resolved.gms_key))
        )
        return CapabilitiesResponse(
            service_version=SERVICE_VERSION,
            capabilities=[
                CapabilityFlag(name="CONTRACTS", available=True),
                CapabilityFlag(
                    name="SOURCE_ACQUISITION",
                    available=True,
                    reason="TEXT and URL enabled; IMAGE requires CLOVA_API_KEY",
                ),
                CapabilityFlag(
                    name="POSTING_INTERPRETATION",
                    available=posting_available,
                    reason=(None if posting_available else "Configure LLM_PROVIDER for Phase 3"),
                ),
                CapabilityFlag(name="AMBIGUITY_RESOLUTION", available=True),
                CapabilityFlag(
                    name="FIT_ANALYSIS",
                    available=posting_available,
                    reason=(None if posting_available else "Configure LLM_PROVIDER for Phase 5"),
                ),
                CapabilityFlag(name="CAPABILITY_NORMALIZATION", available=True),
                CapabilityFlag(
                    name="CAPABILITY_GRAPH",
                    available=bool(resolved.capability_graph_url),
                    reason=(
                        None
                        if resolved.capability_graph_url
                        else "Configure CAPABILITY_GRAPH_URL after the external Phase 6.5 service is ready"
                    ),
                ),
                CapabilityFlag(
                    name="ROADMAP_PROPOSAL",
                    available=posting_available and bool(resolved.capability_graph_url),
                    reason=(
                        None
                        if posting_available and resolved.capability_graph_url
                        else "Configure an LLM provider and CAPABILITY_GRAPH_URL for Phase 7"
                    ),
                ),
                CapabilityFlag(
                    name="ANALYSIS_PIPELINE",
                    available=posting_available and bool(resolved.capability_graph_url),
                    reason=(
                        None
                        if posting_available and resolved.capability_graph_url
                        else "Configure an LLM provider and CAPABILITY_GRAPH_URL for the full pipeline"
                    ),
                ),
                CapabilityFlag(
                    name="ATOMIC_CAPABILITY_ASSESSMENT",
                    available=posting_available,
                    reason=(None if posting_available else "Configure an LLM provider for assessment"),
                ),
            ],
        )

    @application.get(
        "/v1/schemas/{schema_name}",
        dependencies=[Depends(require_internal_client)],
    )
    def schema(schema_name: str) -> dict:
        model = SCHEMA_MODELS.get(schema_name)
        if model is None:
            raise ApiContractException(
                status_code=404,
                error=ErrorDetail(
                    code=ErrorCode.CAPABILITY_NOT_AVAILABLE,
                    message=f"Unknown schema: {schema_name}",
                    retryable=False,
                ),
            )
        return model.model_json_schema(by_alias=True)

    @application.post(
        "/v1/sources/acquire",
        response_model=SourceDocument,
        response_model_by_alias=True,
        dependencies=[Depends(require_internal_client)],
    )
    def acquire_source(request: SourceAcquisitionRequest) -> SourceDocument:
        return application.state.source_service.acquire(request)

    @application.post(
        "/v1/sources/{source_document_id}/verify",
        response_model=SourceVerificationResult,
        response_model_by_alias=True,
        dependencies=[Depends(require_internal_client)],
    )
    def verify_source(
        source_document_id: str,
        request: SourceVerificationRequest,
    ) -> SourceVerificationResult:
        if source_document_id != request.source_document.source_document_id:
            raise ApiContractException(
                status_code=409,
                error=ErrorDetail(
                    code=ErrorCode.CONTRACT_VALIDATION_FAILED,
                    message="sourceDocumentId in the path and request body must match.",
                    retryable=False,
                ),
            )
        try:
            return application.state.source_service.verify(request)
        except ValueError as exc:
            raise ApiContractException(
                status_code=422,
                error=ErrorDetail(
                    code=ErrorCode.CONTRACT_VALIDATION_FAILED,
                    message=str(exc),
                    retryable=False,
                ),
            ) from exc

    @application.post(
        "/v1/postings/structure",
        response_model=StructuredPosting,
        response_model_by_alias=True,
        dependencies=[Depends(require_internal_client)],
    )
    def structure_posting(request: PostingInterpretationRequest) -> StructuredPosting:
        return application.state.posting_service.interpret(request)

    @application.post(
        "/v1/postings/resolve",
        response_model=PostingResolutionResult,
        response_model_by_alias=True,
        dependencies=[Depends(require_internal_client)],
    )
    def resolve_posting(request: PostingResolutionRequest) -> PostingResolutionResult:
        return application.state.resolution_service.resolve(request)

    @application.post(
        "/v1/fit/analyze",
        response_model=FitAnalysisResult,
        response_model_by_alias=True,
        dependencies=[Depends(require_internal_client)],
    )
    def analyze_fit(request: FitAnalysisRequest) -> FitAnalysisResult:
        return application.state.fit_service.analyze(request)

    @application.post(
        "/v1/capabilities/normalize",
        response_model=CapabilityNormalizationResult,
        response_model_by_alias=True,
        dependencies=[Depends(require_internal_client)],
    )
    def normalize_capabilities(
        request: CapabilityNormalizationRequest,
    ) -> CapabilityNormalizationResult:
        return application.state.normalization_service.normalize(request)

    @application.post(
        "/v1/roadmaps/propose",
        response_model=RoadmapProposal,
        response_model_by_alias=True,
        dependencies=[Depends(require_internal_client)],
    )
    def propose_roadmap(request: RoadmapDraftRequest) -> RoadmapProposal:
        return application.state.roadmap_service.compose(request)

    @application.post(
        "/v1/assessments/questions",
        response_model=CapabilityAssessmentQuestion,
        response_model_by_alias=True,
        dependencies=[Depends(require_internal_client)],
    )
    def create_assessment_question(
        request: CapabilityQuestionRequest,
    ) -> CapabilityAssessmentQuestion:
        return application.state.assessment_service.question(request)

    @application.post(
        "/v1/assessments/grade",
        response_model=CapabilityAssessmentGrade,
        response_model_by_alias=True,
        dependencies=[Depends(require_internal_client)],
    )
    def grade_assessment_answer(
        request: CapabilityGradeRequest,
    ) -> CapabilityAssessmentGrade:
        return application.state.assessment_service.grade(request)

    @application.post(
        "/v1/analysis-pipeline/run",
        response_model=AnalysisPipelineResult,
        response_model_by_alias=True,
        dependencies=[Depends(require_internal_client)],
    )
    def run_analysis_pipeline(request: AnalysisPipelineRequest) -> AnalysisPipelineResult:
        return application.state.pipeline_service.run(request)

    @application.post(
        "/v1/analysis-pipeline/stream",
        dependencies=[Depends(require_internal_client)],
    )
    def stream_analysis_pipeline(
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
                    result = application.state.pipeline_service.run(
                        pipeline_request,
                        event_sink=on_progress,
                    )
                last_sequence += 1
                queue.put(PipelineStreamEvent(
                    type=PipelineStreamType.RESULT,
                    sequence=last_sequence,
                    result=result,
                ))
            except Exception as exc:  # stream headers may already have been sent
                LOGGER.exception(
                    "analysis pipeline failed (job_id=%s)",
                    pipeline_request.job_id,
                )
                last_sequence += 1
                queue.put(PipelineStreamEvent(
                    type=PipelineStreamType.ERROR,
                    sequence=last_sequence,
                    error=_stream_error(
                        exc,
                        request_id=http_request.state.request_id,
                        trace_id=http_request.state.trace_id,
                    ),
                ))
            finally:
                queue.put(sentinel)

        def body():
            Thread(target=work, name=f"v3-pipeline-{pipeline_request.job_id}", daemon=True).start()
            while True:
                item = queue.get()
                if item is sentinel:
                    return
                yield item.model_dump_json(by_alias=True) + "\n"

        return StreamingResponse(
            body(),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @application.post(
        "/v1/analysis-pipeline/{job_id}/cancel",
        dependencies=[Depends(require_internal_client)],
    )
    def cancel_analysis_pipeline(job_id: str) -> dict[str, object]:
        return {
            "jobId": job_id,
            "cancelRequested": True,
            "activeProcessInterrupted": cancel_analysis(job_id),
        }

    return application


def _stream_error(exc: Exception, *, request_id: str, trace_id: str) -> ErrorDetail:
    code = getattr(exc, "code", ErrorCode.INTERNAL_ERROR)
    retryable = bool(getattr(exc, "retryable", False))
    message = str(exc) if hasattr(exc, "code") else "The analysis pipeline stopped unexpectedly."
    return ErrorDetail(
        code=code,
        message=message,
        retryable=retryable,
        request_id=request_id,
        trace_id=trace_id,
    )


app = create_app()
