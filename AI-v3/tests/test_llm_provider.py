from __future__ import annotations

import json
import io
import subprocess

import pytest
from pydantic import BaseModel

from jobis_ai_v3.llm.provider import (
    ClaudeCliJsonProvider,
    CodexCliJsonProvider,
    JsonProviderError,
    StructuredGenerator,
)


class OkResult(BaseModel):
    ok: bool


def test_codex_cli_uses_jsonl_schema_and_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class InputBuffer:
        def __init__(self) -> None:
            self.value = ""

        def write(self, value: str) -> None:
            self.value += value

        def close(self) -> None:
            pass

    class FakeProcess:
        def __init__(self) -> None:
            events = [
                {"type": "thread.started", "thread_id": "codex-thread-1"},
                {"type": "turn.started"},
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": '{"ok":true}'},
                },
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 91,
                        "cached_input_tokens": 40,
                        "output_tokens": 12,
                    },
                },
            ]
            self.stdin = InputBuffer()
            self.stdout = io.StringIO("\n".join(json.dumps(item) for item in events) + "\n")
            self.stderr = io.StringIO("")

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def kill(self) -> None:
            pass

    def fake_popen(command: list[str], **kwargs: object) -> FakeProcess:
        captured["command"] = command
        captured["kwargs"] = kwargs
        schema_path = command[command.index("--output-schema") + 1]
        captured["schema"] = json.loads(open(schema_path, encoding="utf-8").read())
        process = FakeProcess()
        captured["process"] = process
        return process

    monkeypatch.setattr("jobis_ai_v3.llm.provider.shutil.which", lambda _name: "C:\\tools\\codex.cmd")
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    provider = CodexCliJsonProvider(
        cli="codex",
        model="gpt-5.6-luna",
        timeout_seconds=120,
    )
    progress = []

    result = provider.complete_json(
        system_prompt="Structure the posting.",
        user_prompt="A long posting body",
        json_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
        effort="low",
        progress_callback=progress.append,
    )

    command = captured["command"]
    process = captured["process"]
    assert isinstance(command, list)
    assert isinstance(process, FakeProcess)
    assert command[0] == "C:\\tools\\codex.cmd"
    assert command[1] == "exec"
    assert "--ephemeral" in command
    assert "--ignore-user-config" in command
    assert "--ignore-rules" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert command[command.index("--model") + 1] == "gpt-5.6-luna"
    assert command[command.index("--config") + 1] == 'model_reasoning_effort="low"'
    assert command[-1] == "-"
    assert captured["schema"] == {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "additionalProperties": False,
        "required": ["ok"],
    }
    assert "A long posting body" in process.stdin.value
    assert result.payload == '{"ok":true}'
    assert result.session_id == "codex-thread-1"
    assert result.input_tokens == 91
    assert result.output_tokens == 12
    assert result.cache_read_input_tokens == 40
    assert [event.kind for event in progress] == [
        "STARTED",
        "STREAM_ACTIVE",
        "COMPLETED",
    ]


def test_codex_cli_reports_jsonl_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class InputBuffer:
        def write(self, _value: str) -> None:
            pass

        def close(self) -> None:
            pass

    class FakeProcess:
        stdin = InputBuffer()
        stdout = io.StringIO(json.dumps({
            "type": "turn.failed",
            "error": {"message": "usage limit reached"},
        }) + "\n")
        stderr = io.StringIO("")

        def wait(self, timeout: float | None = None) -> int:
            return 1

        def kill(self) -> None:
            pass

    monkeypatch.setattr("jobis_ai_v3.llm.provider.shutil.which", lambda _name: "C:\\tools\\codex.cmd")
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: FakeProcess())
    provider = CodexCliJsonProvider(
        cli="codex",
        model="gpt-5.6-luna",
        timeout_seconds=120,
    )

    with pytest.raises(JsonProviderError, match="usage limit reached"):
        provider.complete_json(
            system_prompt="system",
            user_prompt="posting",
            json_schema={"type": "object"},
        )


def test_claude_cli_sends_large_prompt_through_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class InputBuffer:
        def __init__(self) -> None:
            self.value = ""

        def write(self, value: str) -> None:
            self.value += value

        def close(self) -> None:
            pass

    class FakeProcess:
        def __init__(self, payload: dict) -> None:
            self.stdin = InputBuffer()
            self.stdout = io.StringIO(json.dumps(payload) + "\n")
            self.stderr = io.StringIO("")

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def kill(self) -> None:
            pass

    def fake_popen(command: list[str], **kwargs: object) -> FakeProcess:
        captured["command"] = command
        captured["kwargs"] = kwargs
        process = FakeProcess({
                "type": "result",
                "is_error": False,
                "structured_output": {"ok": True},
                "session_id": "session-usage-1",
                "duration_ms": 1200,
                "duration_api_ms": 900,
                "total_cost_usd": 0.0123,
                "usage": {
                    "input_tokens": 101,
                    "output_tokens": 29,
                    "cache_creation_input_tokens": 17,
                    "cache_read_input_tokens": 31,
                },
            })
        captured["process"] = process
        return process

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    provider = ClaudeCliJsonProvider(cli="claude", model="sonnet", timeout_seconds=240)
    long_posting = "백엔드 채용 공고\n" + ("필수 역량과 업무 내용입니다.\n" * 10_000)
    progress = []

    result = provider.complete_json(
        system_prompt="공고를 구조화하세요.",
        user_prompt=long_posting,
        json_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
        progress_callback=progress.append,
    )

    command = captured["command"]
    kwargs = captured["kwargs"]
    process = captured["process"]
    assert isinstance(command, list)
    assert isinstance(kwargs, dict)
    assert result.payload == {"ok": True}
    assert result.session_id == "session-usage-1"
    assert result.input_tokens == 101
    assert result.output_tokens == 29
    assert result.total_cost_usd == pytest.approx(0.0123)
    schema = json.dumps(
        {"type": "object", "properties": {"ok": {"type": "boolean"}}},
        separators=(",", ":"),
    )
    assert command == [
        "claude",
        "-p",
        "--model",
        "sonnet",
        "--output-format",
        "stream-json",
        "--include-partial-messages",
        "--verbose",
        "--json-schema",
        schema,
        "--effort",
        "medium",
        "--max-turns",
        "1",
        "--strict-mcp-config",
        "--tools",
        "",
    ]
    assert long_posting not in command
    assert isinstance(process, FakeProcess)
    assert long_posting in process.stdin.value
    assert schema not in process.stdin.value
    assert kwargs["stdin"] is subprocess.PIPE
    assert [event.kind for event in progress] == [
        "STARTED",
        "STREAM_ACTIVE",
        "COMPLETED",
    ]


def test_claude_cli_start_failure_is_reported_as_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_to_start(_command: list[str], **_kwargs: object) -> object:
        raise OSError(206, "The filename or extension is too long")

    monkeypatch.setattr(subprocess, "Popen", fail_to_start)
    provider = ClaudeCliJsonProvider(cli="claude", model="sonnet", timeout_seconds=240)

    with pytest.raises(JsonProviderError, match="Claude CLI could not start"):
        provider.complete_json(
            system_prompt="system",
            user_prompt="posting",
            json_schema={"type": "object"},
        )


def test_structured_generator_escalates_effort_only_after_failed_contract() -> None:
    class RetryingProvider:
        name = "scripted"
        model = "fixture"

        def __init__(self) -> None:
            self.efforts: list[str] = []

        def complete_json(self, **kwargs: object) -> str:
            self.efforts.append(str(kwargs["effort"]))
            return '{"wrong":true}' if len(self.efforts) == 1 else '{"ok":true}'

    provider = RetryingProvider()
    value, metadata = StructuredGenerator(
        provider,
        max_attempts=2,
        retry_backoff_seconds=0,
        initial_effort="medium",
        retry_effort="high",
    ).generate(OkResult, system_prompt="system", user_prompt="input")

    assert value.ok is True
    assert provider.efforts == ["medium", "high"]
    assert metadata.final_effort == "high"
    assert metadata.effort_history == ("medium", "high")
