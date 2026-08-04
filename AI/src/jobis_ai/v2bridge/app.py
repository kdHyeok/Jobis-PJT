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
from jobis_ai.v2bridge.models import (
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
            # 사유별 코드 — 입력 부족은 재시도로 안 풀리고 사용자가 할 일이 있다(EngineFailed).
            detail={"code": getattr(exc, "code", "AI_PROVIDER_UNAVAILABLE"),
                    "message": str(exc)},
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
    "/v1/analyses/stream",
    dependencies=[Depends(verify_internal_secret)],
)
async def analyze_stream(request: AnalysisRequest) -> StreamingResponse:
    """분석 진행을 NDJSON 으로 흘린다 — 백엔드 진행 휠(피자)의 입력.

    한 줄 = 한 이벤트. 백엔드는 이 경로가 404/405 면 `/v1/analyses` 로 자동 폴백하므로,
    **이 엔드포인트가 없거나 죽어도 분석 자체는 깨지지 않는다.** 그래서 여기서 예외를
    HTTP 로 올리지 않고 `ERROR` 이벤트 한 줄로 끝낸다(이미 200 이 나간 뒤라 방법이 없다).
    """

    import json as json_mod

    def _lines():
        try:
            for event in service.analyze_events(request):
                yield event.model_dump_json(by_alias=True) + "\n"
        except Exception as exc:   # 스트림 도중 실패도 본문으로 알린다(HTTP 는 이미 200)
            log.exception("[v2bridge] 분석 스트림 처리 실패")
            yield json_mod.dumps({
                "type": "ERROR", "runId": str(request.analysis_job_id), "sequence": 9999,
                "occurredAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "stages": [], "stage": None, "result": None,
                # 스트림 경로가 실제 경로다 — 여기서도 사유별 코드를 낸다(app._run 과 동일).
                "errorCode": getattr(exc, "code", "AI_PROVIDER_UNAVAILABLE"),
                "errorMessage": str(exc)[:2000],
            }, ensure_ascii=False) + "\n"

    return StreamingResponse(_lines(), media_type="application/x-ndjson")


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
        try:
            for item in service.chat_events(request):
                if item.get("type") == "result":
                    # **직렬화는 pydantic 에 맡긴다.** `model_dump()` 는 파이썬 객체를 그대로
                    # 남기므로(Decimal·UUID·datetime) `json.dumps` 가 거기서 죽는다 —
                    # 실측(08-03 22:56): 지도 재료(confidence: Decimal)를 실은 순간
                    # "Object of type Decimal is not JSON serializable" 로 스트림이 끊겨,
                    # 판정까지 다 끝낸 턴의 답변과 로드맵이 통째로 유실됐다.
                    # `model_dump_json` 은 계약이 정한 형식(camelCase·JSON 타입)으로 낸다.
                    yield ('{"type":"result","response":'
                           + item["response"].model_dump_json(by_alias=True) + "}\n")
                    continue
                yield json_mod.dumps(item, ensure_ascii=False) + "\n"
        except service.EngineNotConfigured as exc:
            yield json_mod.dumps({"type": "error", "code": "AI_PROVIDER_NOT_CONFIGURED",
                                  "message": str(exc)}, ensure_ascii=False) + "\n"
        except service.EngineFailed as exc:
            yield json_mod.dumps({"type": "error", "code": "AI_PROVIDER_UNAVAILABLE",
                                  "message": str(exc)}, ensure_ascii=False) + "\n"
        except Exception as exc:   # noqa: BLE001 — 예상 밖 실패도 재시도 가능한 실패로 알린다
            log.exception("[v2bridge] chat 스트림 처리 실패")
            yield json_mod.dumps({"type": "error", "code": "AI_PROVIDER_UNAVAILABLE",
                                  "message": str(exc)}, ensure_ascii=False) + "\n"

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
    """역량 검증 한 턴 — 마지막 답변 채점 + 다음 문제.

    무엇을 물을지·언제 끝낼지는 규칙이 정하고(`v2bridge/assessment.py`) LLM 은 문제를
    만들고 답을 읽는다. 이 경로가 없어서 역량 검증 화면이 통째로 죽어 있었다.
    """

    return await _run(lambda: service.assess_competency(request))
