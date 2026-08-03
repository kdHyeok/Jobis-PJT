"""분석 진행 스트림 불변식 (`docs/분석-진행-스트리밍-설계.md` §6). LLM 없이 돈다.

여기서 지키는 것은 **백엔드가 검증하고 실패시키는** 값들이다. `AnalysisWorker.recordProgress`
는 `runId != analysisJobId` 이거나 `sequence` 가 범위 밖이면 예외를 던져 그 job 을 FAILED 로
끝낸다 — 즉 **스트림이 잘못되면 분석이 죽는다.** 창문이 집을 무너뜨리면 안 된다.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from jobis_ai.v2bridge.models import AnalysisStreamEvent
from jobis_ai.v2bridge.stream import StreamBuilder, agent_stage_id

_RUN = uuid4()


def _builder() -> StreamBuilder:
    return StreamBuilder(_RUN)


def _drain(builder: StreamBuilder, traces: list[dict]) -> list[AnalysisStreamEvent]:
    out = [builder.backbone()]
    for ev in traces:
        out.extend(builder.from_trace(ev))
    return out


# --- 불변식 ------------------------------------------------------------------------
def test_sequence_is_strictly_increasing_and_run_id_is_constant():
    events = _drain(_builder(), [
        {"kind": "planner", "detail": {"selectedAgents": ["fit_analysis"], "confidence": 0.9}},
        {"kind": "dispatch", "detail": {"agents": ["fit_analysis"]}},
        {"kind": "agent_start", "detail": {"agent": "fit_analysis"}, "summary": "실행 중"},
        {"kind": "agent_end", "detail": {"agent": "fit_analysis"}, "summary": "완료"},
    ])
    sequences = [e.sequence for e in events]
    assert sequences == sorted(sequences) and len(sequences) == len(set(sequences))
    assert sequences[0] == 1
    assert {e.run_id for e in events} == {_RUN}


def test_first_line_is_run_started():
    assert _builder().backbone().type == "RUN_STARTED"


def test_stage_updates_for_undeclared_stages_are_dropped():
    """선언 안 된 스테이지로 갱신을 보내면 프론트가 무시한다 — 보내지 않는다."""

    builder = _builder()
    builder.backbone()
    assert builder.from_trace(
        {"kind": "agent_start", "detail": {"agent": "fit_analysis"}}) == []


def test_dispatch_republishes_the_plan_with_agent_stages():
    """2단 발행 — 플래너 전에는 어떤 담당이 돌지 모른다(설계 결정 ③)."""

    builder = _builder()
    builder.backbone()
    events = builder.from_trace(
        {"kind": "dispatch", "detail": {"agents": ["posting_analysis", "fit_analysis"]}})
    republished = next(e for e in events if e.type == "RUN_STARTED")
    ids = [s.id for s in republished.stages]
    assert "AGENT_POSTING_ANALYSIS" in ids and "AGENT_FIT_ANALYSIS" in ids
    assert ids[0] == "CONTEXT_ASSEMBLY" and ids[-1] == "RESULT_ASSEMBLY"
    # 이제 그 담당으로 갱신이 나간다
    assert builder.from_trace({"kind": "agent_start", "detail": {"agent": "fit_analysis"}})


def test_stage_cap_keeps_result_assembly_and_says_what_was_cut():
    """상한 12를 코드로 지키되 **잘랐다는 사실을 삼키지 않는다**(§2-6)."""

    builder = _builder()
    builder.backbone()
    many = [f"agent_{i}" for i in range(20)]
    republished = next(e for e in builder.from_trace(
        {"kind": "dispatch", "detail": {"agents": many}}) if e.type == "RUN_STARTED")
    assert len(republished.stages) <= 12
    assert republished.stages[-1].id == "RESULT_ASSEMBLY"
    assert "담지 못한 담당" in republished.stages[-1].message


def test_tool_calls_flow_into_the_stage_message():
    """설계 결정 ②: 어느 담당이 무슨 툴을 썼는지가 여기 실린다."""

    builder = _builder()
    builder.backbone()
    builder.from_trace({"kind": "dispatch", "detail": {"agents": ["posting_analysis"]}})
    events = builder.from_trace({"kind": "agent_step", "detail": {
        "agent": "posting_analysis", "action": "use_tool", "tool": "search_postings",
        "observation": "'백엔드 Kafka' 검색 결과 3건: 가나테크 | 백엔드 …"}})
    assert len(events) == 1
    assert events[0].stage.id == "AGENT_POSTING_ANALYSIS"
    assert "도구 search_postings 호출" in events[0].stage.message


def test_agent_stage_id_is_pattern_safe():
    assert agent_stage_id("fit_analysis") == "AGENT_FIT_ANALYSIS"
    assert agent_stage_id("") == "AGENT_UNKNOWN"
    AnalysisStreamEvent(type="STAGE_UPDATED", run_id=_RUN, sequence=1,
                        occurred_at="2026-08-03T00:00:00Z",
                        stage={"id": agent_stage_id("a-b c"), "status": "RUNNING"})


# --- 계약 검증 ---------------------------------------------------------------------
@pytest.mark.parametrize("bad", [
    {"type": "RUN_STARTED", "stages": []},                      # 빈 계획은 프론트 계획을 지운다
    {"type": "STAGE_UPDATED"},                                  # stage 없음
    {"type": "RESULT"},                                         # result 없음
    {"type": "ERROR"},                                          # 코드 없음
])
def test_events_must_carry_their_payload(bad):
    with pytest.raises(ValidationError):
        AnalysisStreamEvent(run_id=_RUN, sequence=1,
                            occurred_at="2026-08-03T00:00:00Z", **bad)


def test_sequence_upper_bound_matches_the_backend_guard():
    """백엔드는 sequence > 10000 을 예외로 던져 job 을 FAILED 로 끝낸다."""

    with pytest.raises(ValidationError):
        AnalysisStreamEvent(type="ERROR", run_id=_RUN, sequence=10_001,
                            occurred_at="2026-08-03T00:00:00Z",
                            error_code="AI_PROVIDER_UNAVAILABLE")


def test_error_event_is_terminal_and_carries_a_code():
    builder = _builder()
    builder.backbone()
    event = builder.error("AI_PROVIDER_NOT_CONFIGURED", "LLM 이 설정되지 않았어요")
    assert event.type == "ERROR" and event.error_code == "AI_PROVIDER_NOT_CONFIGURED"
