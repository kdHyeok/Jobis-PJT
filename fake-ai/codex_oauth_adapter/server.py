"""Codex OAuth provider를 노출하는 로컬 OpenAI 호환 서버."""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from typing import Any, Iterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from codex_oauth_adapter.ollama import request_allowed, router as ollama_router
from codex_oauth_adapter.provider import CodexError, _usage, complete, list_models, stream_events

app = FastAPI(title="Standalone Codex OpenAI and Ollama Adapter")
app.include_router(ollama_router)


def _local(request: Request) -> bool:
    return request_allowed(request)


def _error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": "invalid_request_error", "code": None}},
    )


def _chunk(completion_id: str, created: int, model: str, delta: dict[str, Any], finish=None) -> str:
    payload = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"


def _tool_delta(
    index: int,
    *,
    call_id: str | None = None,
    name: str | None = None,
    arguments: str | None = None,
) -> dict[str, Any]:
    function: dict[str, Any] = {}
    if name is not None:
        function["name"] = name
    if arguments is not None:
        function["arguments"] = arguments
    tool_call: dict[str, Any] = {"index": index, "function": function}
    if call_id is not None:
        tool_call.update({"id": call_id, "type": "function"})
    return {"tool_calls": [tool_call]}


def _stream(body: dict[str, Any], completion_id: str, created: int) -> Iterator[str]:
    model = body["model"]
    tool_indexes: dict[Any, int] = {}
    arguments_seen: set[int] = set()
    next_index = 0
    phase = None
    saw_tools = False
    usage = None
    yield _chunk(completion_id, created, model, {"role": "assistant", "content": ""})
    options = (
        body["messages"],
        model,
        body.get("reasoning_effort", "medium"),
        body.get("timeout"),
        body.get("tools"),
        body.get("tool_choice"),
        body.get("parallel_tool_calls"),
    )
    try:
        for event in stream_events(*options):
            kind = event.get("type")
            if kind == "error":
                raise CodexError("Codex 스트림 오류가 발생했습니다.")
            if kind == "response.output_item.added":
                item = event.get("item") or {}
                if item.get("type") == "message":
                    phase = item.get("phase")
                elif item.get("type") == "function_call":
                    phase = None
                    saw_tools = True
                    index = next_index
                    next_index += 1
                    call_id = item.get("call_id") or item.get("id")
                    tool_indexes[item.get("id")] = index
                    tool_indexes[event.get("output_index")] = index
                    tool_indexes[call_id] = index
                    yield _chunk(
                        completion_id,
                        created,
                        model,
                        _tool_delta(index, call_id=call_id, name=item.get("name"), arguments=""),
                    )
            elif kind == "response.output_text.delta" and phase not in {"analysis", "commentary"}:
                if delta := event.get("delta"):
                    yield _chunk(completion_id, created, model, {"content": delta})
            elif kind == "response.function_call_arguments.delta":
                key = event.get("item_id")
                index = tool_indexes.get(key, tool_indexes.get(event.get("output_index")))
                if index is None:
                    raise CodexError("tool call보다 arguments delta가 먼저 도착했습니다.")
                delta = event.get("delta", "")
                if delta:
                    arguments_seen.add(index)
                yield _chunk(completion_id, created, model, _tool_delta(index, arguments=delta))
            elif kind == "response.output_item.done":
                item = event.get("item") or {}
                if item.get("type") == "function_call":
                    saw_tools = True
                    call_id = item.get("call_id") or item.get("id")
                    index = tool_indexes.get(item.get("id"), tool_indexes.get(call_id))
                    if index is None:
                        index = next_index
                        next_index += 1
                        tool_indexes[call_id] = index
                        yield _chunk(
                            completion_id,
                            created,
                            model,
                            _tool_delta(
                                index,
                                call_id=call_id,
                                name=item.get("name"),
                                arguments=item.get("arguments") or "{}",
                            ),
                        )
                    elif index not in arguments_seen and item.get("arguments"):
                        yield _chunk(completion_id, created, model, _tool_delta(index, arguments=item["arguments"]))
            elif kind in {"response.completed", "response.incomplete", "response.failed"}:
                if kind != "response.completed":
                    raise CodexError("Codex 응답이 불완전하거나 실패했습니다.")
                usage = _usage((event.get("response") or {}).get("usage"))
                break
        yield _chunk(completion_id, created, model, {}, "tool_calls" if saw_tools else "stop")
        if body.get("stream_options", {}).get("include_usage") and usage:
            payload = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [],
                "usage": usage,
            }
            yield f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
    except CodexError as error:
        yield f"data: {json.dumps({'error': {'message': str(error), 'type': 'server_error'}}, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/models")
def models(request: Request):
    if not _local(request):
        return _error("로컬 요청만 허용됩니다.", 403)
    try:
        now = int(time.time())
        return {
            "object": "list",
            "data": [
                {"id": model["slug"], "object": "model", "created": now, "owned_by": "openai-codex"}
                for model in list_models()
            ],
        }
    except CodexError as error:
        return _error(str(error), 502)


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    if not _local(request):
        return _error("로컬 요청만 허용됩니다.", 403)
    try:
        body = await request.json()
    except Exception:
        return _error("요청 본문은 JSON이어야 합니다.")
    if not isinstance(body, dict) or not isinstance(body.get("messages"), list) or not body.get("messages"):
        return _error("messages는 비어 있지 않은 배열이어야 합니다.")
    body.setdefault("model", "gpt-5.4")
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    if body.get("stream") is True:
        return StreamingResponse(_stream(body, completion_id, created), media_type="text/event-stream")
    options = (
        body["messages"],
        body["model"],
        body.get("reasoning_effort", "medium"),
        body.get("timeout"),
        body.get("tools"),
        body.get("tool_choice"),
        body.get("parallel_tool_calls"),
    )
    try:
        result = complete(*options)
    except CodexError as error:
        return _error(str(error), 502)
    message: dict[str, Any] = {"role": "assistant", "content": result["content"]}
    if result["tool_calls"]:
        message["tool_calls"] = result["tool_calls"]
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": body["model"],
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if result["tool_calls"] else "stop",
            }
        ],
        "usage": result["usage"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="로컬 OpenAI Chat Completions 및 Ollama 호환 Codex 서버"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument(
        "--allow-network",
        action="append",
        default=[],
        metavar="CIDR",
        help="loopback 외에 허용할 클라이언트 CIDR (여러 번 지정 가능)",
    )
    parser.add_argument(
        "--allow-private",
        action="store_true",
        help="Docker/LAN용 RFC1918 및 IPv6 ULA 사설망 클라이언트 허용",
    )
    args = parser.parse_args()
    if args.allow_network:
        configured = [
            value
            for value in os.getenv("CODEX_SERVER_ALLOWED_NETWORKS", "").split(",")
            if value.strip()
        ]
        os.environ["CODEX_SERVER_ALLOWED_NETWORKS"] = ",".join(
            [*configured, *args.allow_network]
        )
    if args.allow_private:
        os.environ["CODEX_SERVER_ALLOW_PRIVATE"] = "1"
    import uvicorn

    uvicorn.run("codex_oauth_adapter.server:app", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
