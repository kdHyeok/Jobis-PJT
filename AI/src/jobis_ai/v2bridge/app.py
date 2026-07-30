"""서비스 v2 백엔드용 AI 서버 — 팀의 `ai-server/`(계약 검증 어댑터) 자리에 그대로 들어간다.

실행 (Windows, uv):
    cmd.exe /c "cd /d C:\\Users\\SSAFY\\Desktop\\S15P11C202-ai\\AI&& set PYTHONUTF8=1&& ^
        C:\\Users\\SSAFY\\.local\\bin\\uv.exe run --with fastapi,uvicorn ^
        uvicorn jobis_ai.v2bridge.app:app --host 127.0.0.1 --port 8000 --reload --reload-dir src"
    (push 자동 반영까지 포함한 실행은 scripts/run_v2bridge.sh 참고)

교체 지점: v2 백엔드는 `AI_SERVER_URL` 하나로 AI 서버를 고른다(팀 README §해당 절).
이 앱이 같은 계약(/health, /v1/analyses, /v1/chat, /v1/evidence-verifications,
/v1/career-extractions)을 구현하므로 백엔드 환경변수만 바꾸면 진짜 에이전트로 바뀐다.

오류 코드는 팀 ai-server 와 동일하게 유지한다 — 백엔드 워커가 이 코드로 재시도를 판단한다:
  · 503 AI_PROVIDER_NOT_CONFIGURED — LLM 미설정 (가짜 성공을 만들지 않는다)
  · 503 AI_PROVIDER_UNAVAILABLE  — 엔진이 결과에 이르지 못함 (재시도 가능)
  · 502 INVALID_AI_RESPONSE      — 엔진 산출물이 계약 검증을 통과하지 못함
"""

from __future__ import annotations

import asyncio
import logging
import os
from hmac import compare_digest
from typing import Annotated, Awaitable, Callable, TypeVar

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import ValidationError

from jobis_ai.v2bridge import service
from jobis_ai.v2bridge.models import (
    AnalysisRequest,
    AnalysisResponse,
    CareerExtractionRequest,
    CareerExtractionResponse,
    ChatRequest,
    ChatResponse,
    EvidenceVerificationRequest,
    EvidenceVerificationResponse,
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

app = FastAPI(
    title="JOBIS AI v2 bridge",
    version="1.0.0",
    description="Stateless, authenticated analysis boundary backed by the jobis-ai engine.",
)


def _shared_secret() -> str:
    # 팀 ai-server 와 같은 환경변수 이름 — 배포 문서(operations.md)가 그대로 성립하게.
    return os.getenv("JOBISS_AI_SHARED_SECRET", "local-ai-secret")


def verify_internal_secret(
    x_jobiss_ai_secret: Annotated[str, Header(alias="X-JOBISS-AI-SECRET")],
) -> None:
    if not compare_digest(x_jobiss_ai_secret, _shared_secret()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal AI credential",
        )


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "jobis-ai-v2bridge",
        "engine": "jobis-ai",
        "provider": service.provider_name(),
    }


_T = TypeVar("_T")


async def _run(handler: Callable[[], _T]) -> _T:
    """엔진 호출(동기·블로킹)을 스레드로 돌리고, 어댑터 예외를 계약 오류 코드로 옮긴다."""

    try:
        return await asyncio.to_thread(handler)
    except service.EngineNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "AI_PROVIDER_NOT_CONFIGURED", "message": str(exc)},
        ) from exc
    except ValidationError as exc:
        # 엔진 산출물이 계약을 통과하지 못했다 — 무엇이 어긋났는지 로그에 남긴다(§2-6).
        log.error("[v2bridge] 계약 검증 실패: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "INVALID_AI_RESPONSE", "message": str(exc)},
        ) from exc
    except service.EngineFailed as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "AI_PROVIDER_UNAVAILABLE", "message": str(exc)},
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:   # noqa: BLE001 — 예상 밖 실패도 재시도 가능한 실패로 알린다
        log.exception("[v2bridge] 처리 실패")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "AI_PROVIDER_UNAVAILABLE", "message": str(exc)},
        ) from exc


@app.post(
    "/v1/analyses",
    response_model=AnalysisResponse,
    response_model_by_alias=True,
    dependencies=[Depends(verify_internal_secret)],
)
async def analyze(request: AnalysisRequest) -> AnalysisResponse:
    return await _run(lambda: service.analyze(request))


@app.post(
    "/v1/chat",
    response_model=ChatResponse,
    response_model_by_alias=True,
    dependencies=[Depends(verify_internal_secret)],
)
async def chat(request: ChatRequest) -> ChatResponse:
    return await _run(lambda: service.chat(request))


@app.post(
    "/v1/evidence-verifications",
    response_model=EvidenceVerificationResponse,
    response_model_by_alias=True,
    dependencies=[Depends(verify_internal_secret)],
)
async def verify_evidence(
    request: EvidenceVerificationRequest,
) -> EvidenceVerificationResponse:
    return await _run(lambda: service.verify_evidence(request))


@app.post(
    "/v1/career-extractions",
    response_model=CareerExtractionResponse,
    response_model_by_alias=True,
    dependencies=[Depends(verify_internal_secret)],
)
async def extract_career(request: CareerExtractionRequest) -> CareerExtractionResponse:
    return await _run(lambda: service.extract_career(request))
