"""Codex CLI adapter for the legacy JOBIS agent runtime.

The adapter deliberately exposes the same tiny surface used by the existing
Claude Code adapter: ``invoke(messages)`` and
``with_structured_output(schema).invoke(messages)``.  Prompts are written to
stdin so long postings never become Windows command-line arguments, and
structured output is constrained with Codex's output-schema option.
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from jobis_ai.claude_code_llm import extract_json

_CALL_TIMEOUT_SEC = 420


class CodexCliChat:
    """Minimal LangChain-compatible facade backed by ``codex exec``."""

    def __init__(
        self,
        model: str,
        cli: str = "codex",
        effort: str = "low",
    ) -> None:
        self.model = model
        self.effort = effort
        self.cli = _resolve_windows_cli(shlex.split(cli or "codex"))

    def with_structured_output(self, schema: type, **_ignored: Any) -> "_Structured":
        return _Structured(self, schema)

    def invoke(self, messages: list[tuple[str, str]]) -> "_TextResult":
        prompt = _prompt(messages, structured=False)
        completion = self._run(prompt, schema=None)
        return _TextResult(completion.text, completion.usage)

    def _run(self, prompt: str, *, schema: dict[str, Any] | None) -> "_Completion":
        with tempfile.TemporaryDirectory(prefix="jobis-codex-") as temp_dir:
            command = [
                *self.cli,
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
                f'model_reasoning_effort="{self.effort}"',
                "--json",
                "--color",
                "never",
            ]
            if schema is not None:
                schema_path = Path(temp_dir, "output-schema.json")
                schema_path.write_text(
                    json.dumps(
                        _codex_output_schema(schema),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    encoding="utf-8",
                )
                command.extend(["--output-schema", str(schema_path)])
            command.append("-")

            try:
                from jobis_ai.career_pipeline.cancellation import (
                    current_analysis_job_id,
                    raise_if_cancelled,
                    register_process,
                )

                if current_analysis_job_id() is None:
                    # 일반 채팅은 기존 실행 경계를 유지한다.
                    result = subprocess.run(
                        command,
                        input=prompt,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=_CALL_TIMEOUT_SEC,
                        stdin=None,
                        cwd=temp_dir,
                    )
                    stdout = result.stdout
                    stderr = result.stderr
                    returncode = result.returncode
                else:
                    # 정식 분석만 Popen registry에 등록해 사용자의 취소 요청이
                    # 실제 Codex CLI 프로세스까지 즉시 전달되게 한다.
                    process = subprocess.Popen(
                        command,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        cwd=temp_dir,
                    )
                    register_process(process)
                    try:
                        stdout, stderr = process.communicate(
                            input=prompt,
                            timeout=_CALL_TIMEOUT_SEC,
                        )
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate()
                        raise
                    raise_if_cancelled()
                    returncode = process.returncode
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise RuntimeError(f"Codex CLI 실행 실패: {exc}") from exc

            final_message = ""
            usage: dict[str, int] | None = None
            event_errors: list[str] = []
            unparsed: list[str] = []
            for line in stdout.splitlines():
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    unparsed.append(line.strip())
                    continue
                if not isinstance(event, dict):
                    continue
                event_type = event.get("type")
                if event_type == "item.completed":
                    item = event.get("item")
                    if isinstance(item, dict) and item.get("type") == "agent_message":
                        text = item.get("text")
                        if isinstance(text, str) and text.strip():
                            final_message = text
                elif event_type == "turn.completed":
                    raw_usage = event.get("usage")
                    if isinstance(raw_usage, dict):
                        usage = {
                            "input_tokens": _non_negative_int(raw_usage.get("input_tokens")),
                            "output_tokens": _non_negative_int(raw_usage.get("output_tokens")),
                        }
                elif event_type in {"turn.failed", "error"}:
                    event_errors.append(_event_error(event))

            if returncode != 0 or event_errors:
                details = [*event_errors, stderr.strip(), *unparsed]
                detail = next((item for item in details if item), "알 수 없는 Codex CLI 오류")
                raise RuntimeError(
                    f"Codex CLI 종료 코드 {returncode}: {detail[:1000]}"
                )
            if not final_message:
                detail = stderr.strip() or (unparsed[0] if unparsed else "최종 응답 없음")
                raise RuntimeError(f"Codex CLI가 최종 답변을 반환하지 않았습니다: {detail[:1000]}")
            return _Completion(final_message, usage)


class _Structured:
    def __init__(self, chat: CodexCliChat, schema: type) -> None:
        self._chat = chat
        self._schema = schema

    def invoke(self, messages: list[tuple[str, str]]) -> Any:
        prompt = _prompt(messages, structured=True)
        completion = self._chat._run(
            prompt,
            schema=self._schema.model_json_schema(),
        )
        return self._schema.model_validate_json(extract_json(completion.text))


class _TextResult:
    def __init__(self, content: str, usage_metadata: dict[str, int] | None) -> None:
        self.content = content
        self.usage_metadata = usage_metadata


class _Completion:
    def __init__(self, text: str, usage: dict[str, int] | None) -> None:
        self.text = text
        self.usage = usage


def _prompt(messages: list[tuple[str, str]], *, structured: bool) -> str:
    system = "\n\n".join(message[1] for message in messages if message[0] == "system")
    human = "\n\n".join(message[1] for message in messages if message[0] != "system")
    suffix = (
        "\n\n---\n출력 스키마를 만족하는 JSON 객체 하나만 반환하세요. "
        "설명이나 코드 펜스를 붙이지 마세요."
        if structured
        else ""
    )
    return f"{system}\n\n---\n[입력]\n{human}{suffix}"


def _resolve_windows_cli(command: list[str]) -> list[str]:
    if not command:
        return ["codex.cmd"]
    if len(command) != 1 or command[0].lower() not in {"codex", "codex.exe", "codex.cmd"}:
        return command
    resolved = shutil.which("codex.cmd") or shutil.which(command[0])
    return [resolved] if resolved else command


def _event_error(event: dict[str, Any]) -> str:
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


def _non_negative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)
