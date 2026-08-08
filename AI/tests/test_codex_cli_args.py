from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from jobis_ai.codex_cli_llm import CodexCliChat
from jobis_ai.career_pipeline.cancellation import (
    AnalysisCancelled,
    bind_analysis_job,
    cancel_analysis,
)


class Result(BaseModel):
    answer: str


def _events(text: str, *, input_tokens: int = 10, output_tokens: int = 3) -> str:
    return "\n".join([
        json.dumps({"type": "thread.started", "thread_id": "thread-1"}),
        json.dumps({
            "type": "item.completed",
            "item": {"type": "agent_message", "text": text},
        }),
        json.dumps({
            "type": "turn.completed",
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            },
        }),
    ])


def test_structured_call_uses_stdin_model_effort_and_output_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        captured["command"] = command
        captured["kwargs"] = kwargs
        schema_path = command[command.index("--output-schema") + 1]
        with open(schema_path, encoding="utf-8") as schema_file:
            captured["schema"] = json.load(schema_file)
        return SimpleNamespace(
            returncode=0,
            stdout=_events('{"answer":"ok"}'),
            stderr="",
        )

    monkeypatch.setattr("jobis_ai.codex_cli_llm.shutil.which", lambda _name: "C:\\tools\\codex.cmd")
    monkeypatch.setattr(subprocess, "run", fake_run)

    chat = CodexCliChat(model="gpt-5.6-luna", effort="low")
    result = chat.with_structured_output(Result).invoke([
        ("system", "system instruction"),
        ("human", "posting body"),
    ])

    command = captured["command"]
    kwargs = captured["kwargs"]
    assert isinstance(command, list)
    assert isinstance(kwargs, dict)
    assert command[0] == "C:\\tools\\codex.cmd"
    assert command[1] == "exec"
    assert command[command.index("--model") + 1] == "gpt-5.6-luna"
    assert command[command.index("--config") + 1] == 'model_reasoning_effort="low"'
    assert command[-1] == "-"
    assert "posting body" in str(kwargs["input"])
    assert captured["schema"] == {
        "properties": {"answer": {"title": "Answer", "type": "string"}},
        "required": ["answer"],
        "title": "Result",
        "type": "object",
        "additionalProperties": False,
    }
    assert result.answer == "ok"


def test_text_call_exposes_codex_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("jobis_ai.codex_cli_llm.shutil.which", lambda _name: "codex.cmd")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout=_events("hello", input_tokens=21, output_tokens=7),
            stderr="",
        ),
    )

    result = CodexCliChat(model="gpt-5.6-luna").invoke([("human", "hello")])

    assert result.content == "hello"
    assert result.usage_metadata == {"input_tokens": 21, "output_tokens": 7}


def test_codex_error_is_not_silently_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("jobis_ai.codex_cli_llm.shutil.which", lambda _name: "codex.cmd")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1,
            stdout=json.dumps({
                "type": "turn.failed",
                "error": {"message": "login required"},
            }),
            stderr="",
        ),
    )

    with pytest.raises(RuntimeError, match="login required"):
        CodexCliChat(model="gpt-5.6-luna").invoke([("human", "hello")])


def test_formal_analysis_cancellation_kills_bound_codex_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeProcess:
        returncode = -9
        killed = False

        def communicate(self, input: str | None = None, timeout: int | None = None):
            assert input and timeout
            cancel_analysis("analysis-job-1")
            return "", ""

        def poll(self):
            return None if not self.killed else self.returncode

        def kill(self):
            self.killed = True

    process = FakeProcess()
    monkeypatch.setattr("jobis_ai.codex_cli_llm.shutil.which", lambda _name: "codex.cmd")
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: process)

    with bind_analysis_job("analysis-job-1"):
        with pytest.raises(AnalysisCancelled):
            CodexCliChat(model="gpt-5.6-luna").invoke([("human", "hello")])

    assert process.killed is True
