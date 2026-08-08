"""웹 브릿지 서버 — fake-ai(node, :8000) 자리에 그대로 들어간다.

실행:
    PYTHONUTF8=1 uv run --with fastapi,uvicorn,websockets \
        uvicorn jobis_ai.webbridge.app:app --host 127.0.0.1 --port 8000

포트 8000 과 루트 경로(ws://localhost:8000)를 지키는 이유는 백엔드 설정을 건드리지 않기
위해서다(application.yml 의 jobiss.agent.url / http-url). 즉 웹 쪽은 코드·설정·DB 를
그대로 두고, 이 서버만 켜면 진짜 에이전트로 바뀐다.

계약 두 갈래:
  · WS  /            — 분석 대화 (START/USER_MESSAGE ↔ JOB_CONTEXT/PROGRESS/QUESTION/AGENT_MESSAGE/DONE/ERROR)
  · HTTP POST        — /extract(자료 파편화) /roadmap(로드맵 생성) /reassess(산출물 재진단) /roadmap-ask(로드맵 Q&A)

관찰 UI(jobis_ai.prototype.app)도 기본이 8000이라 겹친다. 8000 을 팀원이 쓰고 있으면 그 프로세스를
죽이지 말고 이 서버를 다른 포트로 띄운 뒤, 백엔드에 AGENT_WS_URL / AGENT_HTTP_URL 환경변수만 준다
(application.yml 이 이미 그 변수를 읽는다 — 코드·설정 파일 변경 없음). docs/webbridge.md 참고.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import threading
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from jobis_ai.webbridge import http_handlers as handlers
from jobis_ai.webbridge.runner import Channel, run_session

log = logging.getLogger(__name__)

# uvicorn 은 자기 로거만 설정하고 루트는 건드리지 않는다 — 그래서 오케스트레이터가 남기는
# 판단 궤적(planner/dispatch/observe INFO)이 서버 로그에 아예 안 찍혔다. 여기서 한 번
# 설정해 준다. 레벨은 LOG_LEVEL 로 조절(기본 INFO, 조용히 하려면 WARNING).
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = FastAPI(title="jobis-ai 웹 브릿지", docs_url=None, redoc_url=None)

_DEV_UI = Path(__file__).with_name("devui.html")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "engine": "jobis-ai"}


@app.get("/ui", response_class=HTMLResponse)
def dev_ui() -> str:
    """브라우저에서 직접 대화해 보는 개발용 페이지.

    백엔드·DB 없이 이 브릿지만 띄워도 대화가 된다. 페이지는 웹백엔드와 **같은 WS 계약**으로
    말하므로(START/USER_MESSAGE ↔ PROGRESS/QUESTION/DONE), 여기서 보이는 것이 브라우저에
    중계되는 것과 같다. WS 루트(/)는 백엔드용이라 그대로 두고 페이지만 /ui 로 낸다.
    """

    return _DEV_UI.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# WS — 분석 대화
# ---------------------------------------------------------------------------
async def _drain(ws: WebSocket, out: "asyncio.Queue[dict]") -> None:
    """워커 스레드가 큐에 넣은 메시지를 순서대로 브라우저(백엔드)로 보낸다."""

    while True:
        message = await out.get()
        try:
            await ws.send_text(json.dumps(message, ensure_ascii=False))
        except Exception:   # 연결이 이미 닫힘 — 남은 메시지는 버린다
            return
        log.info("  → %s", message.get("type"))


@app.websocket("/")
async def agent_ws(ws: WebSocket) -> None:
    await ws.accept()
    log.info("[브릿지] 백엔드 접속")

    out: "asyncio.Queue[dict]" = asyncio.Queue()
    loop = asyncio.get_running_loop()
    # 워커 스레드에서 호출되므로 이벤트 루프에 스레드 안전하게 넘긴다.
    channel = Channel(lambda m: loop.call_soon_threadsafe(out.put_nowait, m))
    sender = asyncio.create_task(_drain(ws, out))
    worker: threading.Thread | None = None

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                log.warning("[브릿지] JSON 이 아닌 메시지 무시")
                continue

            kind = msg.get("type")
            log.info("  ← %s", kind)
            if kind == "START":
                if worker is not None:
                    log.info("[브릿지] 이미 진행 중인 분석 — 중복 START 무시")
                    continue
                # 판정 그래프는 동기 코드이고 질문 때 사용자 답을 기다린다 → 별도 스레드.
                worker = threading.Thread(
                    target=run_session, args=(msg, channel), daemon=True,
                    name=f"analysis-{msg.get('analysisId', '?')}",
                )
                worker.start()
            elif kind == "USER_MESSAGE":
                channel.push_answer(str(msg.get("text") or ""))
            else:
                log.info("[브릿지] 모르는 메시지 타입 무시: %s", kind)
    except WebSocketDisconnect:
        log.info("[브릿지] 접속 종료")
    finally:
        channel.close()
        # 남은 메시지를 잠깐 흘려보낸 뒤 sender 를 정리한다(DONE 유실 방지).
        await asyncio.sleep(0.1)
        sender.cancel()


# ---------------------------------------------------------------------------
# HTTP — 웹백엔드가 부르는 단발 요청 (계약: fake-ai/server.js 의 4개 라우트)
# ---------------------------------------------------------------------------
@app.post("/extract")
async def extract(body: dict) -> dict:
    """커리어 저장소 자료 파편화. {sourceType, content} → {fragments:[{kind,label,description}]}"""

    return await asyncio.to_thread(handlers.extract_fragments, body)


@app.post("/extract-file")
async def extract_file(body: dict) -> dict:
    """이력서 파일 → 텍스트 + 저장소 조각. 브라우저가 못 읽는 pdf·docx 를 위해 있다.

    {filename, contentBase64} → {text, fragments}. text 는 대화에서 판정 근거로 바로 쓰고,
    fragments 는 커리어 저장소에 적재한다. multipart 대신 JSON 인 이유는 웹백엔드(Java)가
    이 요청을 중계하기 때문이다 — 다른 라우트와 같은 방식으로 맞춰 뒀다.
    """

    raw = base64.b64decode(str(body.get("contentBase64") or ""), validate=False)
    return await asyncio.to_thread(
        handlers.extract_uploaded_file, str(body.get("filename") or ""), raw)


@app.post("/chat/stream")
async def chat_stream(body: dict):
    """대화 한 턴 + 실시간 진행(SSE).

    /chat 과 같은 처리를 하되, 오케스트레이터·판정 그래프가 남기는 trace 를
    progress 이벤트로 흘린다 — 파싱·항목화·판정이 수십 초 걸리는 동안 사용자가
    "지금 무엇을 하고 있는지"를 본다. 마지막 이벤트(done)가 /chat 응답 전문이다.

    진행 문구는 지어내지 않는다: 에이전트 라벨(agent_label)과 노드가 toolLog 에
    직접 쓴 문구만 흘린다 (WS 경로의 PROGRESS 와 같은 원칙).
    """

    import json as _json
    import queue as _queue
    import threading

    from fastapi.responses import StreamingResponse

    from jobis_ai.orchestrator.router import agent_label

    events: "_queue.Queue[dict | None]" = _queue.Queue()

    def _sink(event: dict) -> None:
        kind = event.get("kind")
        detail = event.get("detail") or {}
        if kind == "token":
            # 표현 계층 토큰 스트리밍(run_streaming_text) — 답변이 생기는 대로 화면에 흐른다.
            # 최종 문장은 done 의 reply 가 정본이다(금지표현 검증 통과본으로 교체될 수 있다).
            text = str(detail.get("text") or "")
            if text:
                events.put({"type": "delta", "text": text,
                            "agent": str(detail.get("node") or "")})
            return
        if kind == "agent_start":
            agent = str(detail.get("agent") or "")
            if agent:
                events.put({"type": "progress", "agent": agent,
                            "label": agent_label(agent), "message": ""})
        elif kind == "node":
            node = str(detail.get("node") or "")
            logs = (detail.get("update") or {}).get("toolLog") or []
            said = str((logs[-1] or {}).get("message") or "") if logs else ""
            if node:
                events.put({"type": "progress", "agent": node,
                            "label": agent_label(node), "message": said})

    def _work() -> None:
        from jobis_ai import trace
        try:
            with trace.recording(sink=_sink):
                resp = handlers.chat_turn(body)
            events.put({"type": "done", "response": resp})
        except Exception as exc:   # noqa: BLE001 — 스트림으로도 실패를 알린다
            log.exception("[/chat/stream] 처리 실패")
            events.put({"type": "error", "message": str(exc)})
        finally:
            events.put(None)

    threading.Thread(target=_work, daemon=True).start()

    async def _gen():
        while True:
            item = await asyncio.to_thread(events.get)
            if item is None:
                break
            yield f"data: {_json.dumps(item, ensure_ascii=False)}\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


@app.post("/chat")
async def chat(body: dict) -> dict:
    """일반 대화 한 턴 (오케스트레이터). 분석 WS 와 달리 요청·응답 한 번으로 끝난다."""

    return await asyncio.to_thread(handlers.chat_turn, body)


@app.post("/roadmap")
async def roadmap(body: dict) -> dict:
    """선택한 경로의 준비 로드맵 생성 (roadmap.html 이 렌더하는 steps 형태)."""

    return await asyncio.to_thread(handlers.build_roadmap, body)


@app.post("/reassess")
async def reassess(body: dict) -> dict:
    """스텝 산출물 제출 → 요건 충족 재진단."""

    return await asyncio.to_thread(handlers.reassess_step, body)


@app.post("/submission-review")
async def submission_review(body: dict) -> dict:
    """산출물 제출 → 공고 요건별 피드백. {githubUrl, deployUrl, note, requirements[]}"""

    return await asyncio.to_thread(handlers.review_submission, body)


@app.post("/roadmap-ask")
async def roadmap_ask(body: dict) -> dict:
    """로드맵에 대한 자유 질문 → 답변."""

    return await asyncio.to_thread(handlers.answer_roadmap_question, body)
