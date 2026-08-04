"""Codex OAuth + Responses SSE 변환 로직의 AI 전용 구현.

이 모듈은 외부 서비스 구현을 import하지 않는다. 인증 상태는
``CODEX_OAUTH_STATE_DIR``로 명시적인 영속 경로에 격리한다. OAuth access/refresh token은
로그나 예외에 포함하지 않는다.

참조 구현은 Hermes Agent 0.18.2 provider 코드의 축소·변형본이며 MIT 라이선스다. 저장소의
``AI/NOTICE``에 원 출처와 범위가 기록돼 있다.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Iterator

import httpx

ISSUER = "https://auth.openai.com"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
TOKEN_URL = f"{ISSUER}/oauth/token"
BASE_URL = "https://chatgpt.com/backend-api/codex"
DEFAULT_MODEL = "gpt-5.4"
DEFAULT_SCHEMA_NAME = "jobis_response"
REASONING_EFFORTS = frozenset(
    {"minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
)
_SCHEMA_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class CodexError(RuntimeError):
    """Codex provider 오류. 영구 오류는 ``retryable=False``로 재시도를 막는다."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


def _uses_posix_permissions() -> bool:
    return os.name != "nt"


def state_file() -> Path:
    """명시된 Codex OAuth 상태 디렉터리의 인증 파일을 사용한다."""

    root = os.getenv("CODEX_OAUTH_STATE_DIR")
    if root:
        return Path(root).expanduser() / "auth.json"
    root = os.getenv("XDG_STATE_HOME")
    if root:
        return Path(root).expanduser() / "codex-oauth-test/auth.json"
    return Path.home() / ".local/state/codex-oauth-test/auth.json"


def _claims(token: str) -> dict[str, Any]:
    try:
        chunk = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(chunk + "=" * (-len(chunk) % 4)))
    except Exception:
        return {}


def _save(access_token: str, refresh_token: str) -> None:
    path = state_file()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if _uses_posix_permissions():
        os.chmod(path.parent, 0o700)
    temp = path.with_suffix(".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        json.dump({"access_token": access_token, "refresh_token": refresh_token}, file)
    os.replace(temp, path)
    if _uses_posix_permissions():
        os.chmod(path, 0o600)


def _load() -> dict[str, str] | None:
    path = state_file()
    if not path.exists():
        return None
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        with os.fdopen(fd, encoding="utf-8") as file:
            if _uses_posix_permissions() and os.fstat(file.fileno()).st_mode & 0o077:
                raise ValueError
            data = json.load(file)
        data = data.get("tokens", data)
        if not data.get("access_token") or not data.get("refresh_token"):
            raise ValueError
        return data
    except Exception:
        raise CodexError(
            "Codex 인증 파일이 손상되었습니다. 다시 로그인하세요.", retryable=False
        ) from None


def login() -> None:
    """OpenAI 기기 인증을 수행하고 로컬 상태 파일에 토큰을 저장한다."""

    try:
        response = httpx.post(
            f"{ISSUER}/api/accounts/deviceauth/usercode",
            json={"client_id": CLIENT_ID},
            timeout=15,
        )
    except httpx.HTTPError:
        raise CodexError("OpenAI 로그인 서버에 연결하지 못했습니다.") from None
    if response.status_code != 200:
        raise CodexError(f"device code 요청 실패: HTTP {response.status_code}")

    data = response.json()
    user_code, device_id = data.get("user_code"), data.get("device_auth_id")
    if not user_code or not device_id:
        raise CodexError("device code 응답이 올바르지 않습니다.")
    interval = max(3, int(data.get("interval", 5)))
    print(f"브라우저에서 다음 URL을 여세요: {ISSUER}/codex/device")
    print(f"인증 코드: {user_code}")
    print("로그인 완료를 기다리는 중입니다. Ctrl+C로 취소할 수 있습니다.")

    deadline = time.monotonic() + 900
    authorization = None
    while time.monotonic() < deadline:
        time.sleep(interval)
        response = httpx.post(
            f"{ISSUER}/api/accounts/deviceauth/token",
            json={"device_auth_id": device_id, "user_code": user_code},
            timeout=15,
        )
        if response.status_code == 200:
            authorization = response.json()
            break
        if response.status_code not in {403, 404}:
            raise CodexError(f"로그인 확인 실패: HTTP {response.status_code}")
    if not authorization:
        raise CodexError("로그인 시간이 초과되었습니다.", retryable=False)

    response = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": authorization.get("authorization_code"),
            "redirect_uri": f"{ISSUER}/deviceauth/callback",
            "client_id": CLIENT_ID,
            "code_verifier": authorization.get("code_verifier"),
        },
        timeout=15,
    )
    if response.status_code != 200:
        raise CodexError(f"token 교환 실패: HTTP {response.status_code}")
    tokens = response.json()
    if not tokens.get("access_token") or not tokens.get("refresh_token"):
        raise CodexError("token 응답이 올바르지 않습니다.")
    _save(tokens["access_token"], tokens["refresh_token"])


def logout() -> bool:
    path = state_file()
    if not path.exists():
        return False
    path.unlink()
    return True


def _refresh(tokens: dict[str, str]) -> str:
    try:
        response = httpx.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": CLIENT_ID,
            },
            timeout=20,
        )
    except httpx.HTTPError:
        raise CodexError("token 갱신 서버에 연결하지 못했습니다.") from None
    if response.status_code != 200:
        raise CodexError(
            "token을 갱신할 수 없습니다. 다시 로그인하세요.", retryable=False
        )
    data = response.json()
    access = data.get("access_token")
    if not access:
        raise CodexError("token 갱신 응답이 올바르지 않습니다.")
    _save(access, data.get("refresh_token", tokens["refresh_token"]))
    return access


def access_token(force_refresh: bool = False) -> str:
    tokens = _load()
    if not tokens:
        if not sys.stdin.isatty():
            raise CodexError(
                "Codex 인증 정보가 없습니다. `uv run jobis-codex-oauth --login`을 실행하세요.",
                retryable=False,
            )
        login()
        tokens = _load()
    assert tokens
    exp = _claims(tokens["access_token"]).get("exp", 0)
    if force_refresh or exp <= time.time() + 120:
        return _refresh(tokens)
    return tokens["access_token"]


def _headers(token: str, accept: str = "text/event-stream") -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": accept,
        "User-Agent": "codex_cli_rs/0.0.0 (jobis-ai-codex-adapter)",
        "originator": "codex_cli_rs",
    }
    account = _claims(token).get("https://api.openai.com/auth", {}).get(
        "chatgpt_account_id"
    )
    if account:
        headers["ChatGPT-Account-ID"] = account
    return headers


def list_models() -> list[dict[str, Any]]:
    try:
        response = httpx.get(
            f"{BASE_URL}/models?client_version=1.0.0",
            headers=_headers(access_token(), "application/json"),
            timeout=20,
        )
    except httpx.HTTPError:
        raise CodexError("Codex 모델 목록 서버에 연결하지 못했습니다.") from None
    if response.status_code != 200:
        raise CodexError(f"모델 목록 요청 실패: HTTP {response.status_code}")
    try:
        models = response.json().get("models", [])
    except (AttributeError, ValueError):
        raise CodexError("모델 목록 응답이 올바르지 않습니다.") from None
    if not isinstance(models, list):
        raise CodexError("모델 목록 응답이 올바르지 않습니다.")
    return [
        model
        for model in models
        if isinstance(model, dict)
        and str(model.get("visibility", "")).lower() not in {"hide", "hidden"}
    ]


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return "" if content is None else str(content)
    return "".join(
        str(part.get("text", ""))
        for part in content
        if isinstance(part, dict)
        and part.get("type") in {"text", "input_text", "output_text"}
    )


def _messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    instructions: list[str] = []
    items: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role in {"system", "developer"}:
            if content := _text(message.get("content")):
                instructions.append(content)
            continue
        if role in {"user", "assistant"}:
            if content := _text(message.get("content")):
                items.append({"role": role, "content": content})
            if role == "assistant":
                for call in message.get("tool_calls") or []:
                    function = call.get("function") or {}
                    if function.get("name"):
                        items.append(
                            {
                                "type": "function_call",
                                "call_id": call.get("id"),
                                "name": function["name"],
                                "arguments": function.get("arguments") or "{}",
                            }
                        )
            continue
        if role == "tool" and message.get("tool_call_id"):
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": message["tool_call_id"],
                    "output": _text(message.get("content")),
                }
            )
    return "\n\n".join(instructions), items


def _tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    converted = []
    for tool in tools or []:
        function = tool.get("function") or {}
        if function.get("name"):
            converted.append(
                {
                    "type": "function",
                    "name": function["name"],
                    "description": function.get("description", ""),
                    "strict": bool(function.get("strict", False)),
                    "parameters": function.get("parameters")
                    or {"type": "object", "properties": {}},
                }
            )
    return converted or None


def _tool_choice(choice: Any) -> Any:
    if not isinstance(choice, dict):
        return choice
    function = choice.get("function") or {}
    return (
        {"type": "function", "name": function.get("name")}
        if function.get("name")
        else "auto"
    )


def _json_schema_format(
    schema: Any,
    *,
    name: Any = DEFAULT_SCHEMA_NAME,
    strict: Any = True,
) -> dict[str, Any]:
    if not isinstance(schema, dict):
        raise CodexError("response_format JSON Schema는 객체여야 합니다.")
    if not isinstance(name, str) or not _SCHEMA_NAME_PATTERN.fullmatch(name):
        raise CodexError(
            "response_format schema name은 영문자, 숫자, '_' 또는 '-'로 된 1~64자여야 합니다."
        )
    if not isinstance(strict, bool):
        raise CodexError("response_format strict는 true 또는 false여야 합니다.")
    try:
        schema_copy = json.loads(json.dumps(schema, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError):
        raise CodexError("response_format JSON Schema는 유효한 JSON 값이어야 합니다.") from None
    return {
        "type": "json_schema",
        "name": name,
        "schema": schema_copy,
        "strict": strict,
    }


def _response_format(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, str):
        if value.strip().lower() in {"json", "json_object"}:
            return {"type": "json_object"}
        raise CodexError("response_format 문자열은 'json'이어야 합니다.")
    if not isinstance(value, dict):
        raise CodexError("response_format은 'json' 문자열 또는 JSON Schema 객체여야 합니다.")

    format_type = value.get("type")
    if format_type in {"json", "json_object"}:
        return {"type": "json_object"}
    if format_type == "json_schema":
        wrapper = value.get("json_schema", value)
        if not isinstance(wrapper, dict):
            raise CodexError("response_format json_schema는 객체여야 합니다.")
        if "schema" not in wrapper:
            raise CodexError("response_format json_schema에 schema가 필요합니다.")
        return _json_schema_format(
            wrapper["schema"],
            name=wrapper.get("name", DEFAULT_SCHEMA_NAME),
            strict=wrapper.get("strict", True),
        )
    return _json_schema_format(value)


def build_payload(
    messages: list[dict[str, Any]],
    model: str,
    effort: str,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: Any = None,
    parallel_tool_calls: bool | None = None,
    response_format: Any = None,
) -> dict[str, Any]:
    """Chat messages를 Codex Responses 요청으로 변환한다.

    system/developer 메시지는 ``instructions``로 분리해 GMS 경로가 사용하던 노드 지침을
    그대로 유지한다. user/assistant 메시지만 ``input``으로 보낸다.
    """

    if effort not in REASONING_EFFORTS:
        raise CodexError(
            f"지원하지 않는 CODEX_REASONING_EFFORT={effort!r}. "
            "minimal, low, medium, high, xhigh, max, ultra 중 하나를 사용하세요.",
            retryable=False,
        )
    instructions, items = _messages(messages)
    if not items:
        raise CodexError("messages에 처리할 대화가 없습니다.", retryable=False)
    payload: dict[str, Any] = {
        "model": model,
        "input": items,
        "store": False,
        "stream": True,
        "reasoning": {
            "effort": "low" if effort == "minimal" else effort,
            "summary": "auto",
        },
    }
    if instructions:
        payload["instructions"] = instructions
    if converted := _tools(tools):
        payload["tools"] = converted
        payload["tool_choice"] = _tool_choice(tool_choice or "auto")
        payload["parallel_tool_calls"] = (
            True if parallel_tool_calls is None else parallel_tool_calls
        )
    if normalized_format := _response_format(response_format):
        payload["text"] = {"format": normalized_format}
    return payload


def _sse(lines: Iterable[str]) -> Iterator[dict[str, Any]]:
    for line in lines:
        if isinstance(line, bytes):
            line = line.decode()
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        try:
            yield json.loads(line[6:])
        except json.JSONDecodeError:
            raise CodexError("Codex 스트림 JSON이 올바르지 않습니다.") from None


def _http_error_detail(response: httpx.Response) -> str:
    """요청 원문·토큰 없이 Codex backend의 error.message만 꺼낸다."""

    try:
        response.read()
        body = response.json()
        error = body.get("error") if isinstance(body, dict) else None
        detail = (
            (error.get("message") if isinstance(error, dict) else error)
            or (body.get("message") if isinstance(body, dict) else None)
            or (body.get("detail") if isinstance(body, dict) else None)
        )
    except (httpx.HTTPError, ValueError, AttributeError):
        detail = None
    compact = " ".join(str(detail or "").split())[:1000]
    return f": {compact}" if compact else ""


def stream_events(
    messages: list[dict[str, Any]],
    model: str = DEFAULT_MODEL,
    effort: str = "medium",
    timeout: float | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: Any = None,
    parallel_tool_calls: bool | None = None,
    response_format: Any = None,
) -> Iterator[dict[str, Any]]:
    payload = build_payload(
        messages,
        model,
        effort,
        tools,
        tool_choice,
        parallel_tool_calls,
        response_format,
    )
    for attempt in range(2):
        token = access_token(force_refresh=attempt == 1)
        try:
            with httpx.Client(timeout=timeout or 60) as client:
                with client.stream(
                    "POST",
                    f"{BASE_URL}/responses",
                    headers=_headers(token),
                    json=payload,
                ) as response:
                    if response.status_code == 401 and attempt == 0:
                        continue
                    if response.status_code == 403:
                        raise CodexError(
                            "Codex 접근이 거부되었습니다. 계정 권한을 확인하세요."
                            + _http_error_detail(response),
                            retryable=False,
                        )
                    if response.status_code == 429:
                        raise CodexError(
                            "Codex 요청 한도를 초과했습니다." + _http_error_detail(response)
                        )
                    if response.status_code != 200:
                        raise CodexError(
                            f"Codex 요청 실패: HTTP {response.status_code}"
                            + _http_error_detail(response),
                            retryable=response.status_code >= 500,
                        )
                    yield from _sse(response.iter_lines())
                    return
        except httpx.HTTPError:
            raise CodexError("Codex 서버에 연결하지 못했습니다.") from None
    raise CodexError("Codex 인증에 실패했습니다. 다시 로그인하세요.", retryable=False)


def _usage(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    prompt = int(value.get("input_tokens") or 0)
    completion = int(value.get("output_tokens") or 0)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }


def complete(
    messages: list[dict[str, Any]],
    model: str = DEFAULT_MODEL,
    effort: str = "medium",
    timeout: float | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: Any = None,
    parallel_tool_calls: bool | None = None,
    response_format: Any = None,
) -> dict[str, Any]:
    text: list[str] = []
    fallback: list[str] = []
    calls: list[dict[str, Any]] = []
    phase = None
    usage = None
    terminal = None
    for event in stream_events(
        messages,
        model,
        effort,
        timeout,
        tools,
        tool_choice,
        parallel_tool_calls,
        response_format,
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
            text.append(event.get("delta", ""))
        elif kind == "response.output_item.done":
            item = event.get("item") or {}
            if item.get("type") == "message":
                fallback.extend(
                    part.get("text", "")
                    for part in item.get("content", [])
                    if part.get("type") == "output_text"
                )
            elif item.get("type") == "function_call":
                calls.append(
                    {
                        "id": item.get("call_id"),
                        "type": "function",
                        "function": {
                            "name": item.get("name"),
                            "arguments": item.get("arguments") or "{}",
                        },
                    }
                )
        elif kind in {
            "response.completed",
            "response.incomplete",
            "response.failed",
        }:
            terminal = kind
            usage = _usage((event.get("response") or {}).get("usage"))
            break
    if terminal == "response.incomplete":
        raise CodexError("Codex 응답이 불완전합니다.")
    if terminal != "response.completed":
        raise CodexError("Codex 응답 생성에 실패했습니다.")
    content = "".join(text or fallback) or None
    if not content and not calls:
        raise CodexError("Codex 응답에 텍스트나 tool call이 없습니다.")
    return {"content": content, "tool_calls": calls or None, "usage": usage}
