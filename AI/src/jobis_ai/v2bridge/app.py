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
from datetime import UTC, datetime
from hmac import compare_digest
from typing import Annotated, Awaitable, Callable, TypeVar

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from jobis_ai.v2bridge import service
from jobis_ai.career_pipeline.api_adapter import router as career_pipeline_router
from jobis_ai.v2bridge.models import (
    AnalysisRequest,
    AnalysisResponse,
    CareerExtractionRequest,
    CareerExtractionResponse,
    ChatRequest,
    ChatResponse,
    CompetencyAssessmentRequest,
    CompetencyAssessmentResponse,
    CompetencyLearningRequest,
    CompetencyLearningResponse,
    EvidenceVerificationRequest,
    EvidenceVerificationResponse,
    PostingImportRequest,
    PostingImportResponse,
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
    return os.getenv("JOBISS_AI_SHARED_SECRET") or os.getenv(
        "AI_SHARED_SECRET", "local-ai-secret"
    )


def verify_internal_secret(
    x_jobiss_ai_secret: Annotated[
        str | None,
        Header(alias="X-JOBISS-AI-SECRET"),
    ] = None,
    x_jobis_ai_secret: Annotated[
        str | None,
        Header(alias="X-JOBIS-AI-SECRET"),
    ] = None,
) -> None:
    supplied = x_jobiss_ai_secret or x_jobis_ai_secret or ""
    if not compare_digest(supplied, _shared_secret()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal AI credential",
        )


# Career analysis now runs inside this same FastAPI process.  Applying the
# dependency at include time keeps one authentication boundary for both the
# existing v2 service contract and the transitional career-pipeline URLs.
app.include_router(
    career_pipeline_router,
    dependencies=[Depends(verify_internal_secret)],
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
    except service.EngineTimedOut as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail={"code": "AI_TIMEOUT", "message": str(exc)},
        ) from exc
    except ValidationError as exc:
        # 엔진 산출물이 계약을 통과하지 못했다 — 무엇이 어긋났는지 로그에 남긴다(§2-6).
        log.error("[v2bridge] 계약 검증 실패: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "INVALID_AI_RESPONSE", "message": str(exc)},
        ) from exc
    except service.AnalysisConvergenceFailed as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "ANALYSIS_CONVERGENCE_FAILED", "message": str(exc)},
        ) from exc
    except service.EngineFailed as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": exc.code, "message": str(exc)},
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
    "/v1/posting-imports",
    response_model=PostingImportResponse,
    response_model_by_alias=True,
    dependencies=[Depends(verify_internal_secret)],
)
async def import_posting(request: PostingImportRequest) -> PostingImportResponse:
    return await _run(lambda: service.import_posting(request))


@app.post(
    "/v1/analyses",
    response_model=AnalysisResponse,
    response_model_by_alias=True,
    dependencies=[Depends(verify_internal_secret)],
)
async def analyze(request: AnalysisRequest) -> AnalysisResponse:
    return await _run(lambda: service.analyze(request))


@app.post(
    "/v1/analyses/stream",
    dependencies=[Depends(verify_internal_secret)],
)
async def analyze_stream(request: AnalysisRequest) -> StreamingResponse:
    """Stream bounded analysis progress and exactly one terminal event."""

    def lines():
        for event in service.analyze_events(request):
            yield event.model_dump_json(by_alias=True) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")


@app.post(
    "/v1/chat",
    response_model=ChatResponse,
    response_model_by_alias=True,
    dependencies=[Depends(verify_internal_secret)],
)
async def chat(request: ChatRequest) -> ChatResponse:
    return await _run(lambda: service.chat(request))


@app.post(
    "/v1/chat/stream",
    dependencies=[Depends(verify_internal_secret)],
)
async def chat_stream(request: ChatRequest) -> "StreamingResponse":
    """대화 한 턴을 NDJSON 으로 스트리밍한다(D75) — 진행 단계가 생기는 즉시 한 줄씩.

    줄 형식: {"type":"progress",...} × N → {"type":"result","response":ChatResponse} 1건.
    실패는 {"type":"error","code","message"} 한 줄로 끝난다 — 스트림 도중의 오류는 HTTP
    상태로 표현할 수 없으므로(이미 200 이 나갔다) 본문 이벤트로 알린다. 기존 /v1/chat
    (단건)은 그대로다 — 팀 ai-server 호환 자리를 깨지 않는 **추가** 엔드포인트다.
    """

    import json as json_mod

    def _lines():
        sequence = 1
        legacy_stream = False
        try:
            for item in service.chat_events(request):
                if item.get("type") == "result":
                    if legacy_stream:
                        yield json_mod.dumps({
                            "type": "result",
                            "response": item["response"].model_dump(
                                by_alias=True,
                                mode="json",
                            ),
                        }, ensure_ascii=False) + "\n"
                        sequence += 1
                        continue
                    payload = {
                        "type": "RESULT",
                        "sequence": sequence,
                        "occurredAt": datetime.now(UTC).isoformat(),
                        "agentId": None,
                        "label": None,
                        "status": "COMPLETED",
                        "message": None,
                        "result": item["response"].model_dump(
                            by_alias=True,
                            mode="json",
                        ),
                        "plan": None,
                        "errorCode": None,
                        "errorMessage": None,
                    }
                elif item.get("type") == "plan":
                    payload = {
                        "type": "PLAN",
                        "sequence": sequence,
                        "occurredAt": datetime.now(UTC).isoformat(),
                        "agentId": None,
                        "label": "실행 계획",
                        "status": None,
                        "message": "이번 요청에 참여할 에이전트를 배치했어요.",
                        "result": None,
                        "plan": item["plan"].model_dump(
                            by_alias=True,
                            mode="json",
                        ),
                        "errorCode": None,
                        "errorMessage": None,
                    }
                else:
                    progress = item.get("progress")
                    if progress is None:
                        # 구 stream adapter의 사전형 이벤트를 단계적 전환 동안 그대로
                        # 통과시킨다. 실제 서비스 경로는 AgentProgress를 사용한다.
                        legacy_stream = True
                        yield json_mod.dumps(item, ensure_ascii=False) + "\n"
                        sequence += 1
                        continue
                    payload = {
                        "type": "PROGRESS",
                        "sequence": sequence,
                        "occurredAt": datetime.now(UTC).isoformat(),
                        "agentId": progress.agent_id,
                        "label": progress.label,
                        "status": "RUNNING" if item.get("running") else "COMPLETED",
                        "message": progress.message,
                        "result": None,
                        "plan": None,
                        "errorCode": None,
                        "errorMessage": None,
                    }
                yield json_mod.dumps(payload, ensure_ascii=False) + "\n"
                sequence += 1
        except service.EngineNotConfigured as exc:
            yield json_mod.dumps({
                "type": "ERROR", "sequence": sequence,
                "occurredAt": datetime.now(UTC).isoformat(),
                "agentId": "agent_error_boundary", "label": "AI 설정 확인",
                "status": "FAILED", "message": "실제 AI 공급자 설정을 확인해 주세요.",
                "result": None, "plan": None, "errorCode": "AI_PROVIDER_NOT_CONFIGURED",
                "errorMessage": str(exc),
            }, ensure_ascii=False) + "\n"
        except service.EngineTimedOut as exc:
            yield json_mod.dumps({
                "type": "ERROR", "sequence": sequence,
                "occurredAt": datetime.now(UTC).isoformat(),
                "agentId": "agent_error_boundary", "label": "AI 응답 시간 초과",
                "status": "FAILED", "message": "AI 모델의 응답 제한 시간을 초과했습니다.",
                "result": None, "plan": None, "errorCode": "AI_TIMEOUT",
                "errorMessage": str(exc),
            }, ensure_ascii=False) + "\n"
        except ValidationError as exc:
            yield json_mod.dumps({
                "type": "ERROR", "sequence": sequence,
                "occurredAt": datetime.now(UTC).isoformat(),
                "agentId": "agent_error_boundary", "label": "계약 검증",
                "status": "FAILED", "message": "실제 AI 응답이 서비스 JSON 계약과 다릅니다.",
                "result": None, "plan": None, "errorCode": "INVALID_AI_RESPONSE",
                "errorMessage": str(exc),
            }, ensure_ascii=False) + "\n"
        except service.EngineFailed as exc:
            yield json_mod.dumps({
                "type": "ERROR", "sequence": sequence,
                "occurredAt": datetime.now(UTC).isoformat(),
                "agentId": "agent_error_boundary", "label": "AI 실행 오류",
                "status": "FAILED", "message": "실제 AI 에이전트가 결과를 만들지 못했습니다.",
                "result": None, "plan": None, "errorCode": exc.code,
                "errorMessage": str(exc),
            }, ensure_ascii=False) + "\n"
        except Exception as exc:   # noqa: BLE001 — 예상 밖 실패도 재시도 가능한 실패로 알린다
            log.exception("[v2bridge] chat 스트림 처리 실패")
            yield json_mod.dumps({
                "type": "ERROR", "sequence": sequence,
                "occurredAt": datetime.now(UTC).isoformat(),
                "agentId": "agent_error_boundary", "label": "AI 실행 오류",
                "status": "FAILED", "message": "실제 AI 에이전트 실행 중 오류가 발생했습니다.",
                "result": None, "plan": None, "errorCode": "AI_PROVIDER_UNAVAILABLE",
                "errorMessage": str(exc),
            }, ensure_ascii=False) + "\n"

    return StreamingResponse(_lines(), media_type="application/x-ndjson")


@app.get(
    "/v1/sessions/{conversation_id}",
    dependencies=[Depends(verify_internal_secret)],
)
async def session_state(conversation_id: str) -> dict:
    """세션 자산 요약 조회 — 디버그·관측용(D128). 판단·수정 없음, 읽기 전용."""

    return await _run(lambda: service.session_state(conversation_id))


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


@app.post(
    "/v1/competency-assessments",
    response_model=CompetencyAssessmentResponse,
    response_model_by_alias=True,
    dependencies=[Depends(verify_internal_secret)],
)
async def assess_competency(
    request: CompetencyAssessmentRequest,
) -> CompetencyAssessmentResponse:
    return await _run(lambda: service.assess_competency(request))


@app.post(
    "/v1/competency-learning",
    response_model=CompetencyLearningResponse,
    response_model_by_alias=True,
    dependencies=[Depends(verify_internal_secret)],
)
async def competency_learning(
    request: CompetencyLearningRequest,
) -> CompetencyLearningResponse:
    return await _run(lambda: service.competency_learning(request))
