"""Ollama-compatible HTTP routes backed by the Codex OAuth provider."""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address, ip_network
from typing import Any, Iterator

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from jsonschema import FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError
from jsonschema.validators import validator_for

from codex_oauth_adapter.provider import (
    CodexError,
    _usage,
    complete,
    list_models,
    stream_events,
)

router = APIRouter(prefix="/api", tags=["Ollama compatibility"])

_PRIVATE_NETWORKS = (
    ip_network("10.0.0.0/8"),
    ip_network("172.16.0.0/12"),
    ip_network("192.168.0.0/16"),
    ip_network("fc00::/7"),
)
_STRUCTURED_ATTEMPTS = 3
_EFFORTS = {"minimal", "low", "medium", "high", "xhigh", "max", "ultra"}


def _enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _configured_networks() -> Iterator[Any]:
    for value in os.getenv("CODEX_SERVER_ALLOWED_NETWORKS", "").split(","):
        value = value.strip()
        if not value:
            continue
        try:
            yield ip_network(value, strict=False)
        except ValueError:
            continue


def request_allowed(request: Request) -> bool:
    """Allow loopback by default and explicitly configured Docker/LAN networks."""

    try:
        address = ip_address(request.client.host) if request.client else None
    except ValueError:
        return False
    if address is None:
        return False
    if getattr(address, "ipv4_mapped", None) is not None:
        address = address.ipv4_mapped
    if address.is_loopback:
        return True
    networks = list(_configured_networks())
    if _enabled(os.getenv("CODEX_SERVER_ALLOW_PRIVATE")):
        networks.extend(_PRIVATE_NETWORKS)
    return any(address.version == network.version and address in network for network in networks)


def _error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message})


def _status_for(error: CodexError) -> int:
    message = str(error)
    if "HTTP 404" in message:
        return 404
    if "한도" in message or "HTTP 429" in message:
        return 429
    if "거부" in message or "HTTP 403" in message:
        return 403
    return 502


def _now(*, after: timedelta | None = None) -> str:
    value = datetime.now(timezone.utc)
    if after is not None:
        value += after
    return value.isoformat().replace("+00:00", "Z")


def _ndjson(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"


def _model_name(model: dict[str, Any]) -> str | None:
    value = model.get("slug") or model.get("model") or model.get("name")
    return str(value) if value else None


def _model_details(model: dict[str, Any]) -> dict[str, Any]:
    family = str(model.get("family") or "codex")
    families = model.get("families")
    if not isinstance(families, list):
        families = [family]
    return {
        "parent_model": "",
        "format": str(model.get("format") or "codex"),
        "family": family,
        "families": [str(value) for value in families],
        "parameter_size": str(model.get("parameter_size") or "unknown"),
        "quantization_level": str(model.get("quantization_level") or "unknown"),
    }


def _model_record(model: dict[str, Any], *, running: bool = False) -> dict[str, Any] | None:
    name = _model_name(model)
    if not name:
        return None
    record: dict[str, Any] = {
        "name": name,
        "model": name,
        "size": 0,
        "digest": hashlib.sha256(name.encode("utf-8")).hexdigest(),
        "details": _model_details(model),
    }
    if running:
        context_length = model.get("context_window") or model.get("context_length") or 0
        try:
            context_length = int(context_length)
        except (TypeError, ValueError):
            context_length = 0
        record.update(
            {
                "expires_at": _now(after=timedelta(minutes=5)),
                "size_vram": 0,
                "context_length": context_length,
            }
        )
    else:
        record["modified_at"] = _now()
    return record


def _models(*, running: bool = False) -> list[dict[str, Any]]:
    return [
        record
        for model in list_models()
        if isinstance(model, dict)
        and (record := _model_record(model, running=running)) is not None
    ]


def _validate_chat(body: Any) -> str | None:
    if not isinstance(body, dict):
        return "request body must be a JSON object"
    if not isinstance(body.get("model"), str) or not body["model"].strip():
        return "model must be a non-empty string"
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return "messages must be a non-empty array"
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            return f"messages[{index}] must be an object"
        if message.get("role") not in {"system", "user", "assistant", "tool"}:
            return f"messages[{index}].role is invalid"
        content = message.get("content")
        assistant_tool_call = (
            message.get("role") == "assistant"
            and content is None
            and isinstance(message.get("tool_calls"), list)
            and bool(message["tool_calls"])
        )
        if not isinstance(content, str) and not assistant_tool_call:
            return f"messages[{index}].content must be a string"
    if "stream" in body and not isinstance(body["stream"], bool):
        return "stream must be a boolean"
    if "tools" in body and not isinstance(body["tools"], list):
        return "tools must be an array"
    value = body.get("format")
    if value is not None and value != "json" and not isinstance(value, dict):
        return 'format must be "json" or a JSON Schema object'
    if isinstance(value, dict):
        try:
            validator_for(value).check_schema(value)
        except SchemaError as error:
            return f"format is not a valid JSON Schema: {error.message}"
    return None


def _effort(body: dict[str, Any]) -> str:
    options = body.get("options")
    if not isinstance(options, dict):
        options = {}
    value = body.get("reasoning_effort") or options.get("reasoning_effort")
    if value is None:
        think = body.get("think")
        if isinstance(think, str):
            value = think
        elif think is True:
            value = "medium"
        elif think is False:
            value = "low"
    return value if value in _EFFORTS else "medium"


def _timeout(body: dict[str, Any]) -> float | None:
    options = body.get("options")
    if not isinstance(options, dict):
        options = {}
    value = body.get("timeout", options.get("timeout"))
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return float(value)
    return None


def _structured_instruction(value: str | dict[str, Any]) -> str:
    if value == "json":
        return "Return exactly one valid JSON value. Do not use Markdown fences or add explanatory text."
    schema = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return (
        "Return exactly one JSON value that satisfies this JSON Schema. "
        "Do not use Markdown fences or add explanatory text.\nJSON Schema:\n"
        f"{schema}"
    )


def _structured_messages(
    messages: list[dict[str, Any]], value: str | dict[str, Any]
) -> list[dict[str, Any]]:
    return [{"role": "system", "content": _structured_instruction(value)}, *messages]


def _provider_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Ollama tool history into the OpenAI-shaped provider history."""

    normalized: list[dict[str, Any]] = []
    pending: list[tuple[str, str]] = []
    for message_index, message in enumerate(messages):
        converted = dict(message)
        if message.get("role") == "assistant":
            calls: list[dict[str, Any]] = []
            for call_index, call in enumerate(message.get("tool_calls") or []):
                function = call.get("function") if isinstance(call, dict) else None
                if not isinstance(function, dict) or not function.get("name"):
                    continue
                name = str(function["name"])
                call_id = str(
                    call.get("id")
                    or f"ollama_call_{message_index}_{call_index}"
                )
                arguments = function.get("arguments") or {}
                if not isinstance(arguments, str):
                    arguments = json.dumps(
                        arguments,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                calls.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": arguments},
                    }
                )
                pending.append((name, call_id))
            if calls:
                converted["tool_calls"] = calls
                if converted.get("content") is None:
                    converted["content"] = ""
        elif message.get("role") == "tool" and not converted.get("tool_call_id"):
            tool_name = converted.get("tool_name") or converted.get("name")
            match = next(
                (
                    index
                    for index, (name, _) in enumerate(pending)
                    if tool_name is None or name == tool_name
                ),
                None,
            )
            if match is not None:
                _, call_id = pending.pop(match)
                converted["tool_call_id"] = call_id
        normalized.append(converted)
    return normalized


def _validated_json(content: str | None, value: str | dict[str, Any]) -> str:
    if not content:
        raise ValueError("response content is empty")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError(f"response is not valid JSON: {error.msg}") from None
    if isinstance(value, dict):
        validator = validator_for(value)(value, format_checker=FormatChecker())
        try:
            validator.validate(parsed)
        except ValidationError as error:
            location = error.json_path or "$"
            raise ValueError(f"response does not match JSON Schema at {location}: {error.message}") from None
    return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))


def _complete(
    body: dict[str, Any],
    *,
    messages: list[dict[str, Any]] | None = None,
    response_format: str | dict[str, Any] | None = None,
) -> dict[str, Any]:
    return complete(
        _provider_messages(messages if messages is not None else body["messages"]),
        body["model"].strip(),
        _effort(body),
        _timeout(body),
        body.get("tools"),
        "auto" if body.get("tools") else None,
        body.get("parallel_tool_calls"),
        response_format,
    )


def _structured_complete(body: dict[str, Any]) -> dict[str, Any]:
    value = body["format"]
    messages = _structured_messages(body["messages"], value)
    native_format: str | dict[str, Any] | None = value
    last_error = "structured response validation failed"
    attempts = 0
    while attempts < _STRUCTURED_ATTEMPTS:
        try:
            result = _complete(body, messages=messages, response_format=native_format)
        except CodexError as error:
            if native_format is not None and "HTTP 400" in str(error):
                native_format = None
                continue
            raise
        attempts += 1
        try:
            result["content"] = _validated_json(result.get("content"), value)
            return result
        except ValueError as error:
            last_error = str(error)
            if attempts >= _STRUCTURED_ATTEMPTS:
                break
            if result.get("content"):
                messages.append({"role": "assistant", "content": result["content"]})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"The previous response was invalid: {last_error}. "
                        "Correct it and return only the JSON value."
                    ),
                }
            )
    raise CodexError(
        f"Codex가 유효한 구조화 응답을 생성하지 못했습니다: {last_error}"
    )


def _tool_calls(value: Any) -> list[dict[str, Any]] | None:
    converted: list[dict[str, Any]] = []
    for call in value or []:
        function = call.get("function") if isinstance(call, dict) else None
        if not isinstance(function, dict) or not function.get("name"):
            continue
        arguments = function.get("arguments") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {"raw": arguments}
        if not isinstance(arguments, dict):
            arguments = {"value": arguments}
        converted.append(
            {
                "function": {
                    "name": function["name"],
                    "arguments": arguments,
                }
            }
        )
    return converted or None


def _statistics(started: int, usage: dict[str, int] | None) -> dict[str, int]:
    usage = usage or {}
    return {
        "total_duration": max(0, time.perf_counter_ns() - started),
        "load_duration": 0,
        "prompt_eval_count": int(usage.get("prompt_tokens") or 0),
        "prompt_eval_duration": 0,
        "eval_count": int(usage.get("completion_tokens") or 0),
        "eval_duration": 0,
    }


def _message(result: dict[str, Any]) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": "assistant",
        "content": result.get("content") or "",
    }
    if calls := _tool_calls(result.get("tool_calls")):
        message["tool_calls"] = calls
    return message


def _response(body: dict[str, Any], result: dict[str, Any], started: int) -> dict[str, Any]:
    return {
        "model": body["model"].strip(),
        "created_at": _now(),
        "message": _message(result),
        "done": True,
        "done_reason": "stop",
        **_statistics(started, result.get("usage")),
    }


def _buffered_stream(
    body: dict[str, Any], result: dict[str, Any], started: int
) -> Iterator[str]:
    message = _message(result)
    yield _ndjson(
        {
            "model": body["model"].strip(),
            "created_at": _now(),
            "message": message,
            "done": False,
        }
    )
    yield _ndjson(
        {
            "model": body["model"].strip(),
            "created_at": _now(),
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "done_reason": "stop",
            **_statistics(started, result.get("usage")),
        }
    )


def _live_stream(body: dict[str, Any], started: int) -> Iterator[str]:
    phase = None
    usage = None
    fallback: list[str] = []
    emitted = False
    terminal = None
    try:
        for event in stream_events(
            _provider_messages(body["messages"]),
            body["model"].strip(),
            _effort(body),
            _timeout(body),
        ):
            kind = event.get("type")
            if kind == "error":
                raise CodexError("Codex 스트림 오류가 발생했습니다.")
            if kind == "response.output_item.added":
                item = event.get("item") or {}
                phase = item.get("phase") if item.get("type") == "message" else None
            elif kind == "response.output_text.delta" and phase not in {
                "analysis",
                "commentary",
            }:
                content = event.get("delta", "")
                if content:
                    emitted = True
                    yield _ndjson(
                        {
                            "model": body["model"].strip(),
                            "created_at": _now(),
                            "message": {"role": "assistant", "content": content},
                            "done": False,
                        }
                    )
            elif kind == "response.output_item.done":
                item = event.get("item") or {}
                if item.get("type") == "message":
                    fallback.extend(
                        part.get("text", "")
                        for part in item.get("content", [])
                        if part.get("type") == "output_text"
                    )
            elif kind in {
                "response.completed",
                "response.incomplete",
                "response.failed",
            }:
                terminal = kind
                usage = _usage((event.get("response") or {}).get("usage"))
                break
        if terminal != "response.completed":
            raise CodexError("Codex 응답이 불완전하거나 실패했습니다.")
        if not emitted and fallback:
            yield _ndjson(
                {
                    "model": body["model"].strip(),
                    "created_at": _now(),
                    "message": {
                        "role": "assistant",
                        "content": "".join(fallback),
                    },
                    "done": False,
                }
            )
        yield _ndjson(
            {
                "model": body["model"].strip(),
                "created_at": _now(),
                "message": {"role": "assistant", "content": ""},
                "done": True,
                "done_reason": "stop",
                **_statistics(started, usage),
            }
        )
    except CodexError as error:
        yield _ndjson({"error": str(error)})


@router.get("/tags")
def tags(request: Request):
    if not request_allowed(request):
        return _error("local or explicitly allowed network requests only", 403)
    try:
        return {"models": _models()}
    except CodexError as error:
        return _error(str(error), _status_for(error))


@router.get("/ps")
def running_models(request: Request):
    if not request_allowed(request):
        return _error("local or explicitly allowed network requests only", 403)
    try:
        # The remote Codex backend has no local residency state. Returning the
        # available models is more compatible with clients that use /api/ps as
        # a readiness check.
        return {"models": _models(running=True)}
    except CodexError as error:
        return _error(str(error), _status_for(error))


@router.post("/chat")
async def chat(request: Request):
    if not request_allowed(request):
        return _error("local or explicitly allowed network requests only", 403)
    try:
        body = await request.json()
    except Exception:
        return _error("request body must be valid JSON")
    if error := _validate_chat(body):
        return _error(error)

    started = time.perf_counter_ns()
    stream = body.get("stream", True)
    buffered = body.get("format") is not None or bool(body.get("tools"))
    if stream and not buffered:
        return StreamingResponse(
            _live_stream(body, started),
            media_type="application/x-ndjson",
        )

    try:
        result = (
            _structured_complete(body)
            if body.get("format") is not None
            else _complete(body)
        )
    except CodexError as error:
        return _error(str(error), _status_for(error))

    if stream:
        return StreamingResponse(
            _buffered_stream(body, result, started),
            media_type="application/x-ndjson",
        )
    return _response(body, result, started)
