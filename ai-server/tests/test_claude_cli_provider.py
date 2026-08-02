import asyncio
import json
import logging

import pytest

from app.models import ChatResponse
from app.providers.base import ProviderExecutionError
from app.providers.claude_cli import ClaudeCliProvider
from app.settings import Settings


class FakeWriter:
    def __init__(self) -> None:
        self.data = bytearray()

    def write(self, data: bytes) -> None:
        self.data.extend(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None

    async def wait_closed(self) -> None:
        return None


class FakeReader:
    def __init__(self, lines: list[bytes] | None = None, body: bytes = b"") -> None:
        self.lines = list(lines or [])
        self.body = body

    async def readline(self) -> bytes:
        await asyncio.sleep(0)
        return self.lines.pop(0) if self.lines else b""

    async def read(self) -> bytes:
        await asyncio.sleep(0)
        return self.body


class HangingReader(FakeReader):
    async def readline(self) -> bytes:
        await asyncio.Event().wait()
        return b""


class FakeProcess:
    def __init__(
        self,
        stdout: FakeReader,
        *,
        stderr: bytes = b"",
        return_code: int = 0,
    ) -> None:
        self.stdin = FakeWriter()
        self.stdout = stdout
        self.stderr = FakeReader(body=stderr)
        self.returncode: int | None = None
        self._return_code = return_code

    async def wait(self) -> int:
        if self.returncode is None:
            self.returncode = self._return_code
        return self.returncode

    def kill(self) -> None:
        self.returncode = -9


def event_line(event: dict) -> bytes:
    return json.dumps(event).encode("utf-8") + b"\n"


def success_event(
    result: str,
    *,
    structured_output: dict | None = None,
) -> dict:
    event = {
        "type": "result",
        "is_error": False,
        "result": result,
        "total_cost_usd": 0.001,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    if structured_output is not None:
        event["structured_output"] = structured_output
    return event


def provider(monkeypatch: pytest.MonkeyPatch) -> ClaudeCliProvider:
    monkeypatch.setattr("app.providers.claude_cli.shutil.which", lambda _: "claude.exe")
    return ClaudeCliProvider(
        Settings(
            analysis_provider="claude_cli",
            request_timeout_seconds=12,
            progress_log_interval_seconds=10,
            _env_file=None,
        )
    )


def test_run_streams_cli_events_and_writes_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claude = provider(monkeypatch)
    captured: dict = {}
    process = FakeProcess(
        FakeReader(
            [
                event_line({"type": "system", "subtype": "init", "model": "sonnet"}),
                event_line(success_event('{"message":"ok"}')),
            ]
        )
    )

    async def fake_create(*command, **kwargs):
        captured["command"] = list(command)
        captured["kwargs"] = kwargs
        return process

    monkeypatch.setattr(
        "app.providers.claude_cli.asyncio.create_subprocess_exec",
        fake_create,
    )

    result = asyncio.run(claude._run("hello"))

    assert result == '{"message":"ok"}'
    assert captured["command"][:4] == [
        "claude.exe",
        "-p",
        "--output-format",
        "stream-json",
    ]
    assert "--include-partial-messages" in captured["command"]
    assert "--verbose" in captured["command"]
    assert process.stdin.data == b"hello"


def test_run_timeout_stops_streaming_process(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    claude = provider(monkeypatch)
    claude._progress_interval = 0.01
    process = FakeProcess(HangingReader())

    async def fake_create(*_command, **_kwargs):
        return process

    monkeypatch.setattr(
        "app.providers.claude_cli.asyncio.create_subprocess_exec",
        fake_create,
    )
    caplog.set_level(logging.INFO, logger="uvicorn.error")

    with pytest.raises(ProviderExecutionError, match="timed out"):
        asyncio.run(claude._run("hello", timeout=0.04))

    assert process.returncode == -9
    assert "state=running" in caplog.text
    assert "state=timed_out" in caplog.text


def test_run_translates_process_start_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claude = provider(monkeypatch)

    async def fake_create(*_command, **_kwargs):
        raise OSError("cannot execute")

    monkeypatch.setattr(
        "app.providers.claude_cli.asyncio.create_subprocess_exec",
        fake_create,
    )

    with pytest.raises(ProviderExecutionError, match="could not be started"):
        asyncio.run(claude._run("hello"))


def test_stream_logs_milestones_without_partial_content(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    claude = provider(monkeypatch)
    structured = {
        "message": "ok",
        "intent": "PROFILE_DISCOVERY",
        "shouldRequestPosting": False,
        "suggestedActions": [],
    }
    process = FakeProcess(
        FakeReader(
            [
                event_line({"type": "system", "subtype": "init", "model": "sonnet"}),
                event_line(
                    {
                        "type": "stream_event",
                        "ttft_ms": 123,
                        "event": {"type": "message_start"},
                    }
                ),
                event_line(
                    {
                        "type": "stream_event",
                        "event": {
                            "type": "content_block_delta",
                            "delta": {
                                "type": "input_json_delta",
                                "partial_json": "TOP_SECRET_USER_CONTENT",
                            },
                        },
                    }
                ),
                event_line(success_event(json.dumps(structured), structured_output=structured)),
            ]
        )
    )

    async def fake_create(*_command, **_kwargs):
        return process

    monkeypatch.setattr(
        "app.providers.claude_cli.asyncio.create_subprocess_exec",
        fake_create,
    )
    caplog.set_level(logging.INFO, logger="uvicorn.error")

    result = asyncio.run(
        claude._run(
            "hello",
            json_schema=ChatResponse.model_json_schema(by_alias=True),
            operation="chat_reply",
            request_id="conversation-1",
            phase="response",
        )
    )

    assert json.loads(result) == structured
    assert "state=connected" in caplog.text
    assert "state=generation_started" in caplog.text
    assert "state=completed" in caplog.text
    assert "TOP_SECRET_USER_CONTENT" not in caplog.text


def test_structured_retry_stays_inside_total_time_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claude = provider(monkeypatch)
    timeouts: list[float] = []

    async def fake_run(
        prompt: str,
        timeout: float | None = None,
        json_schema: dict | None = None,
        **_progress,
    ) -> str:
        assert json_schema is not None
        timeouts.append(timeout or 0)
        if len(timeouts) == 1:
            return '{"message":"missing required fields"}'
        return (
            '{"message":"ok","intent":"PROFILE_DISCOVERY",'
            '"shouldRequestPosting":false,"suggestedActions":[]}'
        )

    monkeypatch.setattr(claude, "_run", fake_run)

    result = asyncio.run(claude._ask("hello", ChatResponse))

    assert result.message == "ok"
    assert len(timeouts) == 2
    assert 10.5 <= timeouts[0] <= 11
    assert 0 < timeouts[1] <= 12
