from __future__ import annotations

import json
import logging
import queue
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol, TypeVar

import httpx
from pydantic import BaseModel

from jobis_ai_v3.cancellation import register_process, raise_if_cancelled

from jobis_ai_v3.config import Settings
from jobis_ai_v3.contracts.parsing import StructuredContractError, parse_structured_payload


ModelT = TypeVar("ModelT", bound=BaseModel)
# A child of uvicorn.error inherits the server's INFO handler, so usage records
# remain visible in the PowerShell server log without logging prompts or output.
LOGGER = logging.getLogger("uvicorn.error.jobis_ai_v3.llm")


class JsonProviderError(RuntimeError):
    pass


class JsonProviderNotConfigured(JsonProviderError):
    pass


class JsonCompletionProvider(Protocol):
    name: str
    model: str

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
        effort: str,
        progress_callback: "LlmProgressCallback | None" = None,
    ) -> "JsonCompletion | str | dict[str, Any]": ...


@dataclass(frozen=True, slots=True)
class JsonCompletion:
    payload: str | dict[str, Any]
    effort: str | None = None
    session_id: str | None = None
    duration_ms: int | None = None
    duration_api_ms: int | None = None
    total_cost_usd: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass(frozen=True, slots=True)
class LlmProgressEvent:
    kind: str
    elapsed_ms: int
    message: str
    stream_event_count: int = 0


LlmProgressCallback = Callable[[LlmProgressEvent], None]


class UnconfiguredJsonProvider:
    name = "none"
    model = "none"

    def complete_json(self, **_kwargs: Any) -> str:
        raise JsonProviderNotConfigured("LLM_PROVIDER is not configured for posting interpretation")


class ClaudeCliJsonProvider:
    name = "claude_code"

    def __init__(self, *, cli: str, model: str, timeout_seconds: float) -> None:
        self._command = shlex.split(cli or "claude")
        self.model = model
        self._timeout = timeout_seconds

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
        effort: str = "medium",
        progress_callback: LlmProgressCallback | None = None,
    ) -> JsonCompletion:
        prompt = (
            f"{system_prompt}\n\n---\n[입력]\n{user_prompt}\n\n---\n"
            "제공된 JSON Schema를 만족하는 구조화 결과만 반환하세요."
        )
        encoded_schema = json.dumps(
            json_schema, ensure_ascii=False, separators=(",", ":")
        )
        command = [
            *self._command,
            "-p",
            "--model",
            self.model,
            "--output-format",
            "stream-json",
            "--include-partial-messages",
            "--verbose",
            "--json-schema",
            encoded_schema,
            "--effort",
            effort,
            "--max-turns",
            "1",
            "--strict-mcp-config",
            "--tools",
            "",
        ]
        started = time.perf_counter()
        _notify_progress(
            progress_callback,
            LlmProgressEvent(
                kind="STARTED",
                elapsed_ms=0,
                message="AI에 구조화 요청을 보냈어요",
            ),
        )
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=tempfile.gettempdir(),
            )
            register_process(process)
        except OSError as exc:
            raise JsonProviderError(f"Claude CLI could not start: {exc}") from exc

        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None
        try:
            process.stdin.write(prompt)
            process.stdin.close()
        except OSError as exc:
            process.kill()
            process.wait()
            raise JsonProviderError(f"Claude CLI input failed: {exc}") from exc

        stdout_lines: queue.Queue[str | None] = queue.Queue()
        stderr_parts: list[str] = []
        stdout_thread = threading.Thread(
            target=_read_stream_lines,
            args=(process.stdout, stdout_lines),
            name="claude-json-stream",
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_read_stream_text,
            args=(process.stderr, stderr_parts),
            name="claude-error-stream",
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        wrapper: dict[str, Any] | None = None
        event_count = 0
        last_notice = started
        deadline = started + self._timeout
        while True:
            raise_if_cancelled()
            now = time.perf_counter()
            if now >= deadline:
                process.kill()
                process.wait()
                raise JsonProviderError(
                    f"Claude CLI timed out after {self._timeout:g} seconds"
                )
            try:
                line = stdout_lines.get(timeout=min(5.0, deadline - now))
            except queue.Empty:
                elapsed_ms = round((time.perf_counter() - started) * 1000)
                _notify_progress(
                    progress_callback,
                    LlmProgressEvent(
                        kind="HEARTBEAT",
                        elapsed_ms=elapsed_ms,
                        message=f"AI 응답을 생성하고 있어요 · {elapsed_ms // 1000}초 경과",
                        stream_event_count=event_count,
                    ),
                )
                continue
            if line is None:
                break
            event_count += 1
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and event.get("type") == "result":
                wrapper = event
            now = time.perf_counter()
            if event_count == 1 or now - last_notice >= 5.0:
                elapsed_ms = round((now - started) * 1000)
                _notify_progress(
                    progress_callback,
                    LlmProgressEvent(
                        kind="STREAM_ACTIVE",
                        elapsed_ms=elapsed_ms,
                        message=f"AI 응답 스트림을 받고 있어요 · {elapsed_ms // 1000}초 경과",
                        stream_event_count=event_count,
                    ),
                )
                last_notice = now

        remaining = max(0.1, deadline - time.perf_counter())
        try:
            return_code = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait()
            raise JsonProviderError(
                f"Claude CLI timed out after {self._timeout:g} seconds"
            ) from exc
        stdout_thread.join(timeout=1)
        stderr_thread.join(timeout=1)
        if return_code != 0:
            detail = "".join(stderr_parts)[:500]
            raise JsonProviderError(f"Claude CLI exited with {return_code}: {detail}")
        if wrapper is None:
            raise JsonProviderError("Claude CLI stream ended without a result event")
        if wrapper.get("is_error"):
            raise JsonProviderError(f"Claude CLI returned an error: {str(wrapper.get('result'))[:500]}")
        structured_output = wrapper.get("structured_output")
        payload: str | dict[str, Any]
        if isinstance(structured_output, dict):
            payload = structured_output
        else:
            payload = str(wrapper.get("result") or "")
        usage = wrapper.get("usage") if isinstance(wrapper.get("usage"), dict) else {}
        completion = JsonCompletion(
            payload=payload,
            effort=effort,
            session_id=_optional_string(wrapper.get("session_id")),
            duration_ms=_optional_non_negative_int(wrapper.get("duration_ms")),
            duration_api_ms=_optional_non_negative_int(wrapper.get("duration_api_ms")),
            total_cost_usd=_optional_non_negative_float(wrapper.get("total_cost_usd")),
            input_tokens=_non_negative_int(usage.get("input_tokens")),
            output_tokens=_non_negative_int(usage.get("output_tokens")),
            cache_creation_input_tokens=_non_negative_int(
                usage.get("cache_creation_input_tokens")
            ),
            cache_read_input_tokens=_non_negative_int(
                usage.get("cache_read_input_tokens")
            ),
        )
        LOGGER.info(
            "llm_usage provider=%s model=%s effort=%s session_id=%s "
            "duration_ms=%s duration_api_ms=%s input_tokens=%d output_tokens=%d "
            "cache_creation_input_tokens=%d cache_read_input_tokens=%d total_cost_usd=%s",
            self.name,
            self.model,
            effort,
            completion.session_id or "-",
            completion.duration_ms,
            completion.duration_api_ms,
            completion.input_tokens,
            completion.output_tokens,
            completion.cache_creation_input_tokens,
            completion.cache_read_input_tokens,
            completion.total_cost_usd,
        )
        _notify_progress(
            progress_callback,
            LlmProgressEvent(
                kind="COMPLETED",
                elapsed_ms=round((time.perf_counter() - started) * 1000),
                message="AI 구조화 결과를 받았어요",
                stream_event_count=event_count,
            ),
        )
        return completion


class CodexCliJsonProvider:
    name = "codex_cli"

    def __init__(self, *, cli: str, model: str, timeout_seconds: float) -> None:
        configured = shlex.split(cli or "codex")
        self._command = _resolve_windows_cli(configured, windows_name="codex.cmd")
        self.model = model
        self._timeout = timeout_seconds

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
        effort: str = "low",
        progress_callback: LlmProgressCallback | None = None,
    ) -> JsonCompletion:
        prompt = (
            f"{system_prompt}\n\n---\n[INPUT]\n{user_prompt}\n\n---\n"
            "Return only the final JSON object that conforms to the supplied output schema."
        )
        schema_directory = tempfile.TemporaryDirectory(prefix="jobis-codex-schema-")
        schema_path = Path(schema_directory.name, "output-schema.json")
        schema_path.write_text(
            json.dumps(
                _codex_output_schema(json_schema),
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        command = [
            *self._command,
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--model",
            self.model,
            "--config",
            f'model_reasoning_effort="{effort}"',
            "--output-schema",
            str(schema_path),
            "--json",
            "--color",
            "never",
            "-",
        ]
        started = time.perf_counter()
        _notify_progress(
            progress_callback,
            LlmProgressEvent(
                kind="STARTED",
                elapsed_ms=0,
                message="JOBIS 의미 분석 에이전트가 구조화 작업을 시작했어요",
            ),
        )
        try:
            try:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    cwd=schema_directory.name,
                )
                register_process(process)
            except OSError as exc:
                raise JsonProviderError(f"Codex CLI could not start: {exc}") from exc

            assert process.stdin is not None
            assert process.stdout is not None
            assert process.stderr is not None
            try:
                process.stdin.write(prompt)
                process.stdin.close()
            except OSError as exc:
                process.kill()
                process.wait()
                raise JsonProviderError(f"Codex CLI input failed: {exc}") from exc

            stdout_lines: queue.Queue[str | None] = queue.Queue()
            stderr_parts: list[str] = []
            stdout_thread = threading.Thread(
                target=_read_stream_lines,
                args=(process.stdout, stdout_lines),
                name="codex-json-stream",
                daemon=True,
            )
            stderr_thread = threading.Thread(
                target=_read_stream_text,
                args=(process.stderr, stderr_parts),
                name="codex-error-stream",
                daemon=True,
            )
            stdout_thread.start()
            stderr_thread.start()

            final_message = ""
            thread_id: str | None = None
            usage: dict[str, Any] = {}
            event_errors: list[str] = []
            unparsed_lines: list[str] = []
            event_count = 0
            last_notice = started
            deadline = started + self._timeout
            while True:
                raise_if_cancelled()
                now = time.perf_counter()
                if now >= deadline:
                    process.kill()
                    process.wait()
                    raise JsonProviderError(
                        f"Codex CLI timed out after {self._timeout:g} seconds"
                    )
                try:
                    line = stdout_lines.get(timeout=min(5.0, deadline - now))
                except queue.Empty:
                    elapsed_ms = round((time.perf_counter() - started) * 1000)
                    _notify_progress(
                        progress_callback,
                        LlmProgressEvent(
                            kind="HEARTBEAT",
                            elapsed_ms=elapsed_ms,
                            message=f"JOBIS 의미 분석 에이전트가 결과를 구성하고 있어요 · {elapsed_ms // 1000}초 경과",
                            stream_event_count=event_count,
                        ),
                    )
                    continue
                if line is None:
                    break
                event_count += 1
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    unparsed_lines.append(line.strip())
                    continue
                if not isinstance(event, dict):
                    continue
                event_type = event.get("type")
                if event_type == "thread.started":
                    thread_id = _optional_string(event.get("thread_id"))
                elif event_type == "item.completed":
                    item = event.get("item")
                    if isinstance(item, dict) and item.get("type") == "agent_message":
                        text = item.get("text")
                        if isinstance(text, str) and text.strip():
                            final_message = text
                elif event_type == "turn.completed":
                    raw_usage = event.get("usage")
                    if isinstance(raw_usage, dict):
                        usage = raw_usage
                elif event_type in {"turn.failed", "error"}:
                    event_errors.append(_codex_event_error(event))
                now = time.perf_counter()
                if event_count == 1 or now - last_notice >= 5.0:
                    elapsed_ms = round((now - started) * 1000)
                    _notify_progress(
                        progress_callback,
                        LlmProgressEvent(
                            kind="STREAM_ACTIVE",
                            elapsed_ms=elapsed_ms,
                            message=f"JOBIS 의미 분석 에이전트가 근거를 확인하고 있어요 · {elapsed_ms // 1000}초 경과",
                            stream_event_count=event_count,
                        ),
                    )
                    last_notice = now

            remaining = max(0.1, deadline - time.perf_counter())
            try:
                return_code = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired as exc:
                process.kill()
                process.wait()
                raise JsonProviderError(
                    f"Codex CLI timed out after {self._timeout:g} seconds"
                ) from exc
            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)
            if return_code != 0 or event_errors:
                details = event_errors + ["".join(stderr_parts).strip()] + unparsed_lines
                detail = next((item for item in details if item), "unknown Codex CLI error")
                raise JsonProviderError(
                    f"Codex CLI exited with {return_code}: {detail[:500]}"
                )
            if not final_message:
                raise JsonProviderError("Codex CLI stream ended without a final agent message")

            elapsed_ms = round((time.perf_counter() - started) * 1000)
            completion = JsonCompletion(
                payload=final_message,
                effort=effort,
                session_id=thread_id,
                duration_ms=elapsed_ms,
                input_tokens=_non_negative_int(usage.get("input_tokens")),
                output_tokens=_non_negative_int(usage.get("output_tokens")),
                cache_read_input_tokens=_non_negative_int(usage.get("cached_input_tokens")),
            )
            LOGGER.info(
                "llm_usage provider=%s model=%s effort=%s session_id=%s "
                "duration_ms=%s input_tokens=%d output_tokens=%d cache_read_input_tokens=%d",
                self.name,
                self.model,
                effort,
                completion.session_id or "-",
                completion.duration_ms,
                completion.input_tokens,
                completion.output_tokens,
                completion.cache_read_input_tokens,
            )
            _notify_progress(
                progress_callback,
                LlmProgressEvent(
                    kind="COMPLETED",
                    elapsed_ms=elapsed_ms,
                    message="JOBIS 의미 분석 에이전트가 구조화 결과를 완성했어요",
                    stream_event_count=event_count,
                ),
            )
            return completion
        finally:
            schema_directory.cleanup()


class OpenAiCompatibleJsonProvider:
    name = "openai"

    def __init__(self, *, api_key: str, base_url: str, model: str, timeout_seconds: float) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self.model = model
        self._timeout = timeout_seconds

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
        effort: str = "medium",
        progress_callback: LlmProgressCallback | None = None,
    ) -> str:
        if not self._api_key:
            raise JsonProviderNotConfigured("GMS_KEY is required when LLM_PROVIDER=openai")
        schema_instruction = (
            "Return one JSON object matching this JSON Schema. Do not use Markdown.\n"
            + json.dumps(json_schema, ensure_ascii=False)
        )
        try:
            response = httpx.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"{user_prompt}\n\n{schema_instruction}"},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0,
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
            return str(payload["choices"][0]["message"]["content"] or "")
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise JsonProviderError(f"OpenAI-compatible JSON request failed: {exc}") from exc


@dataclass(frozen=True, slots=True)
class StructuredGeneration:
    value: BaseModel
    provider: str
    model: str
    attempts: int
    duration_ms: int
    final_effort: str
    effort_history: tuple[str, ...]
    provider_duration_ms: int
    provider_api_duration_ms: int
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    total_cost_usd: float
    session_ids: tuple[str, ...]


class StructuredGenerator:
    def __init__(
        self,
        provider: JsonCompletionProvider,
        *,
        max_attempts: int = 3,
        retry_backoff_seconds: float = 0.5,
        initial_effort: str = "medium",
        retry_effort: str = "high",
    ) -> None:
        self._provider = provider
        self._max_attempts = max_attempts
        self._retry_backoff = retry_backoff_seconds
        self._initial_effort = initial_effort
        self._retry_effort = retry_effort

    @property
    def provider_name(self) -> str:
        return self._provider.name

    @property
    def model_name(self) -> str:
        return self._provider.model

    def generate(
        self,
        model: type[ModelT],
        *,
        system_prompt: str,
        user_prompt: str,
        progress_callback: LlmProgressCallback | None = None,
    ) -> tuple[ModelT, StructuredGeneration]:
        started = time.perf_counter()
        last_error: Exception | None = None
        prompt = user_prompt
        completions: list[JsonCompletion] = []
        effort_history: list[str] = []
        for attempt in range(1, self._max_attempts + 1):
            effort = self._initial_effort if attempt == 1 else self._retry_effort
            effort_history.append(effort)
            try:
                raw_completion = self._provider.complete_json(
                    system_prompt=system_prompt,
                    user_prompt=prompt,
                    json_schema=model.model_json_schema(by_alias=True),
                    effort=effort,
                    progress_callback=progress_callback,
                )
            except JsonProviderNotConfigured:
                raise
            except JsonProviderError as exc:
                last_error = exc
                if attempt < self._max_attempts:
                    time.sleep(self._retry_backoff * attempt)
                    continue
                raise JsonProviderError(
                    f"provider failed after {self._max_attempts} attempts: {exc}"
                ) from exc
            completion = _as_completion(raw_completion, effort=effort)
            completions.append(completion)
            try:
                value = parse_structured_payload(completion.payload, model)
                metadata = StructuredGeneration(
                    value=value,
                    provider=self._provider.name,
                    model=self._provider.model,
                    attempts=attempt,
                    duration_ms=round((time.perf_counter() - started) * 1000),
                    final_effort=effort,
                    effort_history=tuple(effort_history),
                    provider_duration_ms=sum(item.duration_ms or 0 for item in completions),
                    provider_api_duration_ms=sum(
                        item.duration_api_ms or 0 for item in completions
                    ),
                    input_tokens=sum(item.input_tokens for item in completions),
                    output_tokens=sum(item.output_tokens for item in completions),
                    cache_creation_input_tokens=sum(
                        item.cache_creation_input_tokens for item in completions
                    ),
                    cache_read_input_tokens=sum(
                        item.cache_read_input_tokens for item in completions
                    ),
                    total_cost_usd=sum(item.total_cost_usd or 0 for item in completions),
                    session_ids=tuple(
                        item.session_id for item in completions if item.session_id
                    ),
                )
                return value, metadata
            except StructuredContractError as exc:
                last_error = exc
                if attempt < self._max_attempts:
                    prompt = (
                        f"{user_prompt}\n\n직전 응답은 계약 검증에 실패했습니다: {str(exc)[:1200]}\n"
                        "의미를 새로 만들지 말고 원문 근거를 유지한 채 JSON 계약만 바로잡으세요."
                    )
        raise JsonProviderError(
            f"structured response failed validation after {self._max_attempts} attempts: {last_error}"
        )


def build_json_provider(settings: Settings) -> JsonCompletionProvider:
    if settings.llm_provider in {"", "none", "null"}:
        return UnconfiguredJsonProvider()
    if settings.llm_provider == "claude_code":
        return ClaudeCliJsonProvider(
            cli=settings.claude_cli,
            model=settings.claude_code_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    if settings.llm_provider == "codex_cli":
        return CodexCliJsonProvider(
            cli=settings.codex_cli,
            model=settings.codex_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    if settings.llm_provider == "openai":
        return OpenAiCompatibleJsonProvider(
            api_key=settings.gms_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    raise JsonProviderNotConfigured(f"unsupported LLM_PROVIDER: {settings.llm_provider}")


def _as_completion(
    value: JsonCompletion | str | dict[str, Any], *, effort: str
) -> JsonCompletion:
    if isinstance(value, JsonCompletion):
        return value
    return JsonCompletion(payload=value, effort=effort)


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _non_negative_int(value: Any) -> int:
    parsed = _optional_non_negative_int(value)
    return parsed if parsed is not None else 0


def _optional_non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _optional_non_negative_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _resolve_windows_cli(command: list[str], *, windows_name: str) -> list[str]:
    if not command:
        return [windows_name]
    if len(command) != 1 or command[0].lower() not in {"codex", "codex.exe", "codex.cmd"}:
        return command
    resolved = shutil.which(windows_name) or shutil.which(command[0])
    return [resolved] if resolved else command


def _codex_event_error(event: dict[str, Any]) -> str:
    error = event.get("error")
    if isinstance(error, str):
        return error
    if isinstance(error, dict):
        for key in ("message", "detail", "code"):
            value = error.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return json.dumps(error, ensure_ascii=False)
    message = event.get("message")
    return message if isinstance(message, str) and message.strip() else str(event)


def _codex_output_schema(schema: dict[str, Any]) -> dict[str, Any]:
    normalized = json.loads(json.dumps(schema))

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                visit(item)
            return
        if not isinstance(node, dict):
            return
        properties = node.get("properties")
        if node.get("type") == "object" and isinstance(properties, dict):
            node["additionalProperties"] = False
            node["required"] = list(properties)
        for value in node.values():
            visit(value)

    visit(normalized)
    return normalized


def _read_stream_lines(stream: Any, target: queue.Queue[str | None]) -> None:
    try:
        for line in stream:
            if line.strip():
                target.put(line)
    finally:
        target.put(None)


def _read_stream_text(stream: Any, target: list[str]) -> None:
    for chunk in stream:
        target.append(chunk)


def _notify_progress(
    callback: LlmProgressCallback | None,
    event: LlmProgressEvent,
) -> None:
    if callback is None:
        return
    try:
        callback(event)
    except Exception:
        LOGGER.warning("LLM progress callback failed", exc_info=True)
