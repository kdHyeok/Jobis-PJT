"""Codex OAuth provider를 기존 JOBIS LLM 계약에 맞추는 얇은 어댑터.

노드·프롬프트·재시도 계층은 provider를 알 필요가 없다. 기존 GMS 경로와 똑같이
``[("system", 지침), ("human", 입력)]``을 받고, system 지침은 Codex Responses API의
``instructions``로, human 입력은 ``input``으로 전달한다.
"""

from __future__ import annotations

import re
from typing import Any, Iterator

from jobis_ai.codex_oauth_adapter.provider import (
    CodexError,
    REASONING_EFFORTS,
    complete,
    stream_events,
)

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def extract_json(text: str) -> str:
    text = (text or "").strip()
    fenced = _FENCE.search(text)
    if fenced:
        return fenced.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


def _message_dicts(messages: list[tuple[str, str]]) -> list[dict[str, str]]:
    role_map = {"human": "user", "ai": "assistant"}
    return [
        {"role": role_map.get(role, role), "content": content}
        for role, content in messages
        if content
    ]


def _schema_name(schema: type) -> str:
    name = re.sub(r"[^A-Za-z0-9_-]", "_", schema.__name__)[:64]
    return name or "jobis_response"


def _usage_metadata(usage: dict[str, int] | None) -> dict[str, int] | None:
    if not usage:
        return None
    return {
        "input_tokens": int(usage.get("prompt_tokens") or 0),
        "output_tokens": int(usage.get("completion_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
    }


class _TextResult:
    """LangChain 메시지에서 JOBIS가 사용하는 content/usage_metadata 표면."""

    def __init__(self, content: str, usage_metadata: dict[str, int] | None = None) -> None:
        self.content = content
        self.usage_metadata = usage_metadata


class CodexChat:
    """Codex OAuth Responses API를 LangChain 유사 계약으로 노출한다."""

    def __init__(
        self,
        model: str,
        *,
        reasoning_effort: str = "medium",
        timeout_sec: float = 200,
    ) -> None:
        if not model.strip():
            raise CodexError("CODEX_MODEL은 비어 있을 수 없습니다.", retryable=False)
        effort = reasoning_effort.strip().lower()
        if effort not in REASONING_EFFORTS:
            raise CodexError(
                f"지원하지 않는 CODEX_REASONING_EFFORT={reasoning_effort!r}.",
                retryable=False,
            )
        if timeout_sec <= 0:
            raise CodexError("CODEX_TIMEOUT_SEC는 0보다 커야 합니다.", retryable=False)
        self.model = model.strip()
        self.reasoning_effort = effort
        self.timeout_sec = timeout_sec

    def with_structured_output(self, schema: type, **_ignored: Any) -> "_Structured":
        return _Structured(self, schema)

    def invoke(self, messages: list[tuple[str, str]]) -> _TextResult:
        result = complete(
            _message_dicts(messages),
            self.model,
            self.reasoning_effort,
            self.timeout_sec,
        )
        return _TextResult(
            str(result.get("content") or ""),
            _usage_metadata(result.get("usage")),
        )

    def stream(self, messages: list[tuple[str, str]]) -> Iterator[_TextResult]:
        """Codex SSE의 최종 답변 delta만 전달하고 analysis/commentary는 숨긴다."""

        phase = None
        saw_delta = False
        terminal = None
        fallback: list[str] = []
        for event in stream_events(
            _message_dicts(messages),
            self.model,
            self.reasoning_effort,
            self.timeout_sec,
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
                if delta := str(event.get("delta") or ""):
                    saw_delta = True
                    yield _TextResult(delta)
            elif kind == "response.output_item.done":
                item = event.get("item") or {}
                if item.get("type") == "message":
                    fallback.extend(
                        str(part.get("text") or "")
                        for part in item.get("content", [])
                        if part.get("type") == "output_text"
                    )
            elif kind in {
                "response.completed",
                "response.incomplete",
                "response.failed",
            }:
                terminal = kind
                if not saw_delta and fallback:
                    yield _TextResult("".join(fallback))
                usage = (event.get("response") or {}).get("usage")
                input_tokens = int((usage or {}).get("input_tokens") or 0)
                output_tokens = int((usage or {}).get("output_tokens") or 0)
                yield _TextResult(
                    "",
                    {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "total_tokens": int(
                            (usage or {}).get("total_tokens")
                            or input_tokens + output_tokens
                        ),
                    }
                    if usage
                    else None,
                )
                break
        if terminal == "response.incomplete":
            raise CodexError("Codex 응답이 불완전합니다.")
        if terminal != "response.completed":
            raise CodexError("Codex 응답 생성에 실패했습니다.")


class _Structured:
    def __init__(self, chat: CodexChat, schema: type) -> None:
        self._chat = chat
        self._schema = schema

    def invoke(self, messages: list[tuple[str, str]]) -> Any:
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": _schema_name(self._schema),
                "schema": self._schema.model_json_schema(),
                # 현재 스키마에는 기본값 필드가 있어 strict 필수필드 규칙과 충돌할 수 있다.
                # GMS가 function_calling으로 같은 문제를 피하는 것과 동일한 경계다.
                "strict": False,
            },
        }
        result = complete(
            _message_dicts(messages),
            self._chat.model,
            self._chat.reasoning_effort,
            self._chat.timeout_sec,
            response_format=response_format,
        )
        return self._schema.model_validate_json(
            extract_json(str(result.get("content") or ""))
        )
