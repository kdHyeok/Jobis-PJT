"""감사 로그(정책 결정 영속)와 비용 환산 — 둘 다 "모른다 ≠ 0" 을 지키는지가 핵심이다."""

from __future__ import annotations

import json

from jobis_ai import llm_usage, trace


def test_audit_writes_only_policy_events(tmp_path, monkeypatch):
    """감사 대상만 남는다 — 관찰용 이벤트까지 남기면 정책 기록이 그 안에 묻힌다."""

    log = tmp_path / "audit.jsonl"
    monkeypatch.setenv("JOBIS_AUDIT_LOG", str(log))

    with trace.audit_session("s-1"):
        trace.emit("consent_gate", "동의 요청", {"ask": "진행할까요?"})
        trace.emit("delegate_refused", "위임 거부", {"target": "fit_analysis", "reason": "heavy"})
        trace.emit("agent_start", "관찰용 — 남지 않아야 한다", {})

    lines = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    assert [e["kind"] for e in lines] == ["consent_gate", "delegate_refused"]
    # 세션 id 가 없으면 "누구의 턴이었나"에 답할 수 없어 감사가 아니다.
    assert all(e["sessionId"] == "s-1" for e in lines)
    assert lines[1]["detail"]["reason"] == "heavy"


def test_audit_survives_without_recorder(tmp_path, monkeypatch):
    """레코더가 없어도 남는다 — trace 는 창문이지만 감사는 창문이 아니다."""

    log = tmp_path / "audit.jsonl"
    monkeypatch.setenv("JOBIS_AUDIT_LOG", str(log))
    assert not trace.active()
    trace.emit("consent_granted", "동의 소진", {"granted": ["fit_analysis"]})
    assert json.loads(log.read_text(encoding="utf-8").strip())["kind"] == "consent_granted"


def test_audit_off_switch(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBIS_AUDIT_LOG", "off")
    monkeypatch.chdir(tmp_path)
    trace.emit("consent_gate", "꺼져 있으면 아무것도 안 쓴다", {})
    assert list(tmp_path.rglob("*.jsonl")) == []


def test_cost_is_none_when_price_unknown():
    """단가를 모르면 **0 이 아니라 모른다.** 0 이면 "공짜로 돌았다"로 읽힌다."""

    assert llm_usage.call_cost_usd("claude-opus-5", 1000, 500) is None
    assert llm_usage.call_cost_usd("gpt-4.1-mini", None, None) is None


def test_cost_sums_only_priced_calls():
    collector = llm_usage.UsageCollector()
    collector.record({"node": "a", "tier": "default", "model": "gpt-4.1-mini", "outcome": "ok",
                      "attempts": 1, "durationMs": 10,
                      "inputTokens": 1_000_000, "outputTokens": 1_000_000})
    collector.record({"node": "b", "tier": "router", "model": "claude-opus-5", "outcome": "ok",
                      "attempts": 1, "durationMs": 10,
                      "inputTokens": None, "outputTokens": None})

    s = collector.summary()
    assert s["costUsd"] == 2.0            # 0.40 + 1.60
    assert s["uncostedCalls"] == 1        # 단가 미상은 합계에 섞지 않고 따로 센다
    assert s["unmeteredCalls"] == 1
