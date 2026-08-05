"""LLM 사용량 집계(llm_usage) — 평가 리포트 §1-2·§2-1 의 "집계기가 없다"를 닫는 계층.

계약:
- 수집기가 없으면 record 는 no-op (trace.emit 과 같은 규약 — 운영 경로에 부담 없음).
- 콜은 논리 콜(재시도 포함 1건) 단위. not_configured 는 콜로 세지 않는다.
- 토큰을 못 받은 콜은 0 으로 지어내지 않고 unmeteredCalls 로 따로 센다 (모른다 ≠ 0).
- 중첩 수집기는 부모에게도 전달한다 — 평가 하네스가 턴 안의 콜을 놓치지 않게.
- run_structured 의 성공·실패가 전부 기록된다 (호출 지점 16개가 전부 그 파일을 지난다).
"""

from __future__ import annotations

from pydantic import BaseModel

from jobis_ai import llm_usage


def test_record_without_collector_is_noop():
    """수집기 없이 record 해도 아무 일도 없다 — 계측이 실행을 막지 않는다."""

    llm_usage.record(node="n", tier="default", outcome="ok")   # 예외 없으면 통과


def test_summary_counts_calls_tokens_and_unmetered():
    with llm_usage.collecting() as usage:
        llm_usage.record(node="planner", tier="default", outcome="ok", attempts=1,
                         input_tokens=100, output_tokens=20, duration_ms=500)
        llm_usage.record(node="career_chat", tier="default", outcome="ok", attempts=2)
        llm_usage.record(node="planner", tier="default", outcome="failed", attempts=3)
        llm_usage.record(node="skip", tier="default", outcome="not_configured", attempts=0)

    s = usage.summary()
    assert s["calls"] == 3                      # not_configured 는 콜이 아니다
    assert s["ok"] == 2 and s["failed"] == 1 and s["notConfigured"] == 1
    assert s["retries"] == 3                    # (2-1) + (3-1)
    assert s["inputTokens"] == 100 and s["outputTokens"] == 20
    assert s["unmeteredCalls"] == 2             # 토큰 못 받은 ok 1 + failed 1
    assert s["byNode"] == {"planner": 2, "career_chat": 1}


def test_summary_without_any_metered_call_reports_none_not_zero():
    """토큰을 하나도 못 받았으면 합계는 None 이다 — 0 은 '없음'이지 '모름'이 아니다."""

    with llm_usage.collecting() as usage:
        llm_usage.record(node="n", tier="default", outcome="ok")
    s = usage.summary()
    assert s["inputTokens"] is None and s["outputTokens"] is None
    assert s["unmeteredCalls"] == 1


def test_nested_collector_propagates_to_parent():
    """하네스(바깥)가 턴(안쪽)의 콜을 놓치지 않는다 — trace 의 _parent 와 같은 규약."""

    with llm_usage.collecting() as outer:
        with llm_usage.collecting() as inner:
            llm_usage.record(node="planner", tier="default", outcome="ok",
                             input_tokens=10, output_tokens=5)
        assert inner.summary()["calls"] == 1
    assert outer.summary()["calls"] == 1
    assert outer.summary()["inputTokens"] == 10


def test_run_structured_records_success(monkeypatch):
    """run_structured 성공이 콜 1건으로 기록된다 — 집계의 원천은 그 파일 하나다."""

    from jobis_ai import structured

    class Dummy(BaseModel):
        value: str

    class OkLLM:
        def with_structured_output(self, schema, **kwargs):
            return self

        def invoke(self, messages):
            return Dummy(value="응답")

    monkeypatch.setattr(structured, "get_llm", lambda tier: OkLLM())
    with llm_usage.collecting() as usage:
        result, warnings = structured.run_structured(Dummy, "sys", "본문", node="test_node")

    assert result is not None
    s = usage.summary()
    assert s["calls"] == 1 and s["ok"] == 1
    # 가짜 LLM 은 usage 를 안 준다 — 지어내지 않고 미계측으로 남아야 한다.
    assert s["unmeteredCalls"] == 1 and s["inputTokens"] is None
    assert s["byNode"] == {"test_node": 1}


def test_run_structured_records_failure_with_attempts(monkeypatch):
    """재시도 소진 실패도 기록된다 — 실패 콜을 빼면 재시도 비용이 통계에서 사라진다."""

    from jobis_ai import structured

    class Dummy(BaseModel):
        value: str

    class DeadLLM:
        def with_structured_output(self, schema, **kwargs):
            return self

        def invoke(self, messages):
            raise RuntimeError("죽음")

    monkeypatch.setattr(structured, "get_llm", lambda tier: DeadLLM())
    monkeypatch.setattr(structured, "_RETRY_BACKOFF_SEC", 0)
    with llm_usage.collecting() as usage:
        result, warnings = structured.run_structured(Dummy, "sys", "본문", node="test_node")

    assert result is None
    s = usage.summary()
    assert s["calls"] == 1 and s["failed"] == 1
    assert s["retries"] == structured._MAX_ATTEMPTS - 1


def test_run_structured_does_not_retry_permanent_provider_failure(monkeypatch):
    """구독 주간 한도처럼 재실행해도 같은 실패는 한 번만 호출한다."""

    from jobis_ai import structured

    class Dummy(BaseModel):
        value: str

    class PermanentError(RuntimeError):
        retryable = False

    class DeadLLM:
        calls = 0

        def with_structured_output(self, schema, **kwargs):
            return self

        def invoke(self, messages):
            self.calls += 1
            raise PermanentError("주간 사용 한도 초과")

    llm = DeadLLM()
    monkeypatch.setattr(structured, "get_llm", lambda tier: llm)
    monkeypatch.setattr(structured, "_RETRY_BACKOFF_SEC", 0)
    with llm_usage.collecting() as usage:
        result, warnings = structured.run_structured(Dummy, "sys", "본문", node="test_node")

    assert result is None and llm.calls == 1
    assert "1회 시도 후 실패" in warnings[-1]["message"]
    assert usage.summary()["retries"] == 0


def test_run_streaming_text_does_not_retry_permanent_provider_failure(monkeypatch):
    """비스트리밍 Claude CLI 표현 경로도 영구 실패를 반복하지 않는다."""

    from jobis_ai import structured

    class PermanentError(RuntimeError):
        retryable = False

    class DeadLLM:
        calls = 0

        def invoke(self, messages):
            self.calls += 1
            raise PermanentError("주간 사용 한도 초과")

    llm = DeadLLM()
    monkeypatch.setattr(structured, "get_llm", lambda tier: llm)
    monkeypatch.setattr(structured, "_RETRY_BACKOFF_SEC", 0)
    with llm_usage.collecting() as usage:
        result, warnings = structured.run_streaming_text("sys", "본문", node="test_node")

    assert result == "" and llm.calls == 1
    assert "1회 시도 후 실패" in warnings[-1]["message"]
    assert usage.summary()["retries"] == 0


def test_handle_chat_emits_turn_usage_trace(monkeypatch):
    """턴에 실제 콜이 있었으면 turn 요약이 trace 로 남는다 (관찰 UI 용 사본)."""

    from jobis_ai import trace
    from jobis_ai.contracts.api import ChatRequest
    from jobis_ai.orchestrator import chat

    def fake_turn(request):
        llm_usage.record(node="planner", tier="default", outcome="ok",
                         input_tokens=10, output_tokens=5)
        from jobis_ai.contracts.api import ChatResponse
        return ChatResponse(sessionId=request.sessionId, reply="답", intent="career_chat",
                            confidence=1.0, dispatched=[], results={},
                            followUpQuestions=[], warnings=[])

    monkeypatch.setattr(chat, "_handle_chat_turn", fake_turn)
    with trace.recording() as rec:
        chat.handle_chat(ChatRequest(sessionId="s1", message="안녕", attachments=[]))

    events = [e for e in rec.events if e["kind"] == "llm_usage"]
    assert len(events) == 1
    assert events[0]["detail"]["calls"] == 1
    assert events[0]["detail"]["inputTokens"] == 10
