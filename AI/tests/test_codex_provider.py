"""Codex OAuth provider — 기존 AI 지침/모델 티어 계약을 바꾸지 않는 추가 경로."""

from __future__ import annotations

import httpx
from pydantic import BaseModel

from jobis_ai.codex_llm import CodexChat
from jobis_ai.codex_oauth_adapter import provider


def test_payload_preserves_system_instructions_and_user_input():
    """GMS에 보내던 system/human 경계를 Codex instructions/input으로 그대로 옮긴다."""

    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    }
    payload = provider.build_payload(
        [
            {"role": "system", "content": "기존 JOBIS 모델 지침"},
            {"role": "user", "content": "기존 분석 입력"},
        ],
        "gpt-codex-test",
        "high",
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "answer", "schema": schema, "strict": False},
        },
    )

    assert payload["instructions"] == "기존 JOBIS 모델 지침"
    assert payload["input"] == [{"role": "user", "content": "기존 분석 입력"}]
    assert payload["model"] == "gpt-codex-test"
    assert payload["reasoning"]["effort"] == "high"
    assert payload["text"]["format"]["schema"] == schema
    assert payload["text"]["format"]["strict"] is False
    assert "max_output_tokens" not in payload


def test_structured_adapter_uses_existing_messages_and_schema(monkeypatch):
    class Result(BaseModel):
        answer: str
        optional_note: str = ""

    seen = {}

    def fake_complete(messages, model, effort, timeout, **kwargs):
        seen.update(
            messages=messages,
            model=model,
            effort=effort,
            timeout=timeout,
            kwargs=kwargs,
        )
        return {"content": '{"answer":"정상"}', "usage": None, "tool_calls": None}

    monkeypatch.setattr("jobis_ai.codex_llm.complete", fake_complete)
    chat = CodexChat(
        "gpt-codex-test",
        reasoning_effort="xhigh",
        timeout_sec=123,
    )

    result = chat.with_structured_output(Result).invoke(
        [("system", "현재 AI 지침"), ("human", "분석할 본문")]
    )

    assert result == Result(answer="정상")
    assert seen["messages"] == [
        {"role": "system", "content": "현재 AI 지침"},
        {"role": "user", "content": "분석할 본문"},
    ]
    assert (seen["model"], seen["effort"], seen["timeout"]) == (
        "gpt-codex-test",
        "xhigh",
        123,
    )
    response_format = seen["kwargs"]["response_format"]["json_schema"]
    assert response_format["schema"] == Result.model_json_schema()
    assert response_format["strict"] is False


def test_stream_adapter_hides_reasoning_and_reports_usage(monkeypatch):
    def fake_events(*args, **kwargs):
        yield {
            "type": "response.output_item.added",
            "item": {"type": "message", "phase": "analysis"},
        }
        yield {"type": "response.output_text.delta", "delta": "숨은 추론"}
        yield {
            "type": "response.output_item.added",
            "item": {"type": "message", "phase": "final"},
        }
        yield {"type": "response.output_text.delta", "delta": "최종 답변"}
        yield {
            "type": "response.completed",
            "response": {"usage": {"input_tokens": 10, "output_tokens": 4}},
        }

    monkeypatch.setattr("jobis_ai.codex_llm.stream_events", fake_events)
    chunks = list(CodexChat("gpt-codex-test").stream([("human", "질문")]))

    assert "".join(chunk.content for chunk in chunks) == "최종 답변"
    assert chunks[-1].usage_metadata == {
        "input_tokens": 10,
        "output_tokens": 4,
        "total_tokens": 14,
    }


def test_codex_provider_uses_independent_model_tiers(monkeypatch):
    from jobis_ai.config import get_settings
    from jobis_ai.llm import get_llm

    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.setenv("CODEX_MODEL", "gpt-codex-default")
    monkeypatch.setenv("CODEX_MODEL_LIGHT", "gpt-codex-light")
    monkeypatch.setenv("CODEX_MODEL_ROUTER", "gpt-codex-router")
    monkeypatch.setenv("CODEX_REASONING_EFFORT", "high")
    monkeypatch.setenv("CODEX_TIMEOUT_SEC", "77")
    get_settings.cache_clear()
    get_llm.cache_clear()
    try:
        default = get_llm("default")
        light = get_llm("light")
        router = get_llm("router")
        assert isinstance(default, CodexChat)
        assert (default.model, light.model, router.model) == (
            "gpt-codex-default",
            "gpt-codex-light",
            "gpt-codex-router",
        )
        assert default.reasoning_effort == "high"
        assert default.timeout_sec == 77
        assert get_settings().has_llm_key is True
    finally:
        get_llm.cache_clear()
        get_settings.cache_clear()


def test_fake_ai_auth_state_contract_is_retained(monkeypatch, tmp_path):
    """CODEX_OAUTH_STATE_DIR만 바꾸면 격리할 수 있고 기본 파일명 계약은 auth.json이다."""

    monkeypatch.setenv("CODEX_OAUTH_STATE_DIR", str(tmp_path))
    assert provider.state_file() == tmp_path / "auth.json"


def test_http_error_exposes_only_provider_message():
    response = httpx.Response(
        400,
        json={"error": {"message": "Unsupported parameter: example"}},
    )
    assert provider._http_error_detail(response) == ": Unsupported parameter: example"
    string_error = httpx.Response(400, json={"error": "Instructions are required"})
    assert provider._http_error_detail(string_error) == ": Instructions are required"
