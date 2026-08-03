import json
from datetime import UTC, datetime
from functools import lru_cache
from hmac import compare_digest
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import StreamingResponse

from app.models import (
    AnalysisRequest,
    AnalysisResponse,
    CareerExtractionRequest,
    CareerExtractionResponse,
    ChatRequest,
    ChatResponse,
    CompetencyAssessmentRequest,
    CompetencyAssessmentResponse,
    EvidenceVerificationRequest,
    EvidenceVerificationResponse,
)
from app.providers.base import ProviderExecutionError, ProviderNotConfigured
from app.providers.json_support import InvalidProviderResponse
from app.service import AnalysisService
from app.settings import Settings, get_settings

app = FastAPI(
    title="JOBISS AI Server",
    version="1.0.0",
    description="Stateless, authenticated analysis boundary. It never connects to the service DB.",
)


@lru_cache
def get_analysis_service() -> AnalysisService:
    return AnalysisService(get_settings())


def verify_internal_secret(
    x_jobiss_ai_secret: Annotated[str, Header(alias="X-JOBISS-AI-SECRET")],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if not compare_digest(x_jobiss_ai_secret, settings.shared_secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal AI credential",
        )


@app.get("/health")
async def health(
    service: Annotated[AnalysisService, Depends(get_analysis_service)],
) -> dict[str, str]:
    return {
        "status": "ok",
        "service": "jobiss-ai-server",
        "provider": service.provider_name,
    }


@app.post(
    "/v1/analyses",
    response_model=AnalysisResponse,
    response_model_by_alias=True,
    dependencies=[Depends(verify_internal_secret)],
)
async def analyze(
    request: AnalysisRequest,
    service: Annotated[AnalysisService, Depends(get_analysis_service)],
) -> AnalysisResponse:
    try:
        return await service.analyze(request)
    except ProviderNotConfigured as exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "AI_PROVIDER_NOT_CONFIGURED",
                "message": str(exception),
            },
        ) from exception
    except InvalidProviderResponse as exception:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "INVALID_AI_RESPONSE", "message": str(exception)},
        ) from exception
    except ProviderExecutionError as exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "AI_PROVIDER_UNAVAILABLE", "message": str(exception)},
        ) from exception


@app.post(
    "/v1/analyses/stream",
    dependencies=[Depends(verify_internal_secret)],
)
async def analyze_stream(
    request: AnalysisRequest,
    service: Annotated[AnalysisService, Depends(get_analysis_service)],
) -> StreamingResponse:
    async def events():
        try:
            async for event in service.analyze_stream(request):
                yield event.model_dump_json(by_alias=True) + "\n"
        except ProviderNotConfigured as exception:
            yield _stream_error(
                request,
                "AI_PROVIDER_NOT_CONFIGURED",
                str(exception),
            )
        except InvalidProviderResponse as exception:
            yield _stream_error(
                request,
                "INVALID_AI_RESPONSE",
                str(exception),
            )
        except ProviderExecutionError as exception:
            yield _stream_error(
                request,
                "AI_PROVIDER_UNAVAILABLE",
                str(exception),
            )

    return StreamingResponse(events(), media_type="application/x-ndjson")


def _stream_error(
    request: AnalysisRequest,
    code: str,
    message: str,
) -> str:
    return json.dumps(
        {
            "type": "ERROR",
            "runId": str(request.analysis_job_id),
            "sequence": 10000,
            "occurredAt": datetime.now(UTC).isoformat(),
            "stages": [],
            "stage": None,
            "result": None,
            "errorCode": code,
            "errorMessage": message,
        },
        ensure_ascii=False,
    ) + "\n"


@app.post(
    "/v1/chat",
    response_model=ChatResponse,
    response_model_by_alias=True,
    dependencies=[Depends(verify_internal_secret)],
)
async def chat(
    request: ChatRequest,
    service: Annotated[AnalysisService, Depends(get_analysis_service)],
) -> ChatResponse:
    try:
        return await service.chat(request)
    except ProviderNotConfigured as exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "AI_PROVIDER_NOT_CONFIGURED", "message": str(exception)},
        ) from exception
    except InvalidProviderResponse as exception:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "INVALID_AI_RESPONSE", "message": str(exception)},
        ) from exception
    except ProviderExecutionError as exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "AI_PROVIDER_UNAVAILABLE", "message": str(exception)},
        ) from exception


@app.post(
    "/v1/evidence-verifications",
    response_model=EvidenceVerificationResponse,
    response_model_by_alias=True,
    dependencies=[Depends(verify_internal_secret)],
)
async def verify_evidence(
    request: EvidenceVerificationRequest,
    service: Annotated[AnalysisService, Depends(get_analysis_service)],
) -> EvidenceVerificationResponse:
    try:
        return await service.verify_evidence(request)
    except ProviderNotConfigured as exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "AI_PROVIDER_NOT_CONFIGURED", "message": str(exception)},
        ) from exception
    except InvalidProviderResponse as exception:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "INVALID_AI_RESPONSE", "message": str(exception)},
        ) from exception
    except ProviderExecutionError as exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "AI_PROVIDER_UNAVAILABLE", "message": str(exception)},
        ) from exception


@app.post(
    "/v1/career-extractions",
    response_model=CareerExtractionResponse,
    response_model_by_alias=True,
    dependencies=[Depends(verify_internal_secret)],
)
async def extract_career(
    request: CareerExtractionRequest,
    service: Annotated[AnalysisService, Depends(get_analysis_service)],
) -> CareerExtractionResponse:
    try:
        return await service.extract_career(request)
    except ProviderNotConfigured as exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "AI_PROVIDER_NOT_CONFIGURED", "message": str(exception)},
        ) from exception
    except InvalidProviderResponse as exception:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "INVALID_AI_RESPONSE", "message": str(exception)},
        ) from exception
    except ProviderExecutionError as exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "AI_PROVIDER_UNAVAILABLE", "message": str(exception)},
        ) from exception


@app.post(
    "/v1/competency-assessments",
    response_model=CompetencyAssessmentResponse,
    response_model_by_alias=True,
    dependencies=[Depends(verify_internal_secret)],
)
async def assess_competency(
    request: CompetencyAssessmentRequest,
    service: Annotated[AnalysisService, Depends(get_analysis_service)],
) -> CompetencyAssessmentResponse:
    try:
        return await service.assess_competency(request)
    except ProviderNotConfigured as exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "AI_PROVIDER_NOT_CONFIGURED", "message": str(exception)},
        ) from exception
    except InvalidProviderResponse as exception:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "INVALID_AI_RESPONSE", "message": str(exception)},
        ) from exception
    except ProviderExecutionError as exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "AI_PROVIDER_UNAVAILABLE", "message": str(exception)},
        ) from exception
