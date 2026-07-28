"""트레이스 레코더 + 관찰 UI 저장소 테스트 (LLM 없음, 결정론).

레코더가 꺼져 있으면 계측이 no-op 인지(운영 무영향), 켜면 오케스트레이터~판정 엔진의
이벤트가 실제로 잡히는지, DB 왕복이 온전한지 검증한다.
"""

from __future__ import annotations

import pytest

from jobis_ai import trace
from jobis_ai.contracts.api import ChatAttachment, ChatRequest, SourceType
from jobis_ai.prototype.db import RunStore
from jobis_ai.orchestrator import session as session_mod
from jobis_ai.orchestrator.chat import handle_chat
from jobis_ai.orchestrator.session import SessionStore


@pytest.fixture(autouse=True)
def fresh_session_store(monkeypatch):
    store = SessionStore()
    monkeypatch.setattr(session_mod, "_STORE", store)
    return store


@pytest.fixture(autouse=True)
def stub_planner(monkeypatch):
    """플래너 선택을 주입한다 — 계측 대상은 그 뒤 실행 경로다(LLM 추론은 여기 관심사가 아니다)."""

    from jobis_ai.orchestrator.planner import AgentPlan

    plan = AgentPlan(agents=["fit_analysis"], confidence=0.9, ack="적합도 분석을 실행할게요.")
    monkeypatch.setattr("jobis_ai.orchestrator.chat.plan_agents",
                        lambda message, session: (plan, []))


def _request(message: str) -> ChatRequest:
    return ChatRequest(
        sessionId="trace-s1",
        message=message,
        attachments=[
            ChatAttachment(kind="resume", sourceType=SourceType.text,
                           value="Python Django 백엔드 개발 3년. PostgreSQL 사용."),
            ChatAttachment(kind="job_posting", sourceType=SourceType.text,
                           value="백엔드 개발자 모집. 필수: Python, Django. 우대: AWS."),
        ],
    )


# --- 레코더 기본 동작 ----------------------------------------------------------
def test_emit_is_noop_without_recorder():
    """레코더 비활성 시 emit 은 아무 것도 하지 않는다 — 운영 경로 무영향."""

    assert not trace.active()
    trace.emit("node", "should vanish")  # 예외 없이 무시


def test_recording_is_scoped():
    with trace.recording() as rec:
        assert trace.active()
        trace.emit("planner", "inside", {"a": 1})
    assert not trace.active()
    assert len(rec.events) == 1
    ev = rec.events[0]
    assert ev["seq"] == 1 and ev["kind"] == "planner" and ev["detail"] == {"a": 1}
    assert ev["elapsedMs"] >= 0


# --- 오케스트레이터~판정 엔진 계측 (LLM off → mock 폴백 경로) -------------------
def test_full_turn_produces_detailed_trace():
    with trace.recording() as rec:
        response = handle_chat(_request("이 공고 나 되나?"))

    kinds = {e["kind"] for e in rec.events}
    # 플래너 선택 + 검증기 확정은 반드시 찍힌다 (자율 판단이 무엇을 골랐는지 항상 보인다)
    assert "planner" in kinds and "dispatch" in kinds
    # 에이전트 실행 왕복
    assert "agent_start" in kinds and "agent_end" in kinds
    # 판정 엔진 노드 스트리밍 — 10노드 경로 중 핵심 노드가 보여야 한다
    node_names = [e["detail"]["node"] for e in rec.events if e["kind"] == "node"]
    assert "parse_job_posting" in node_names
    assert "analyze_gap" in node_names
    assert "assemble_output" in node_names
    # 매칭 캐스케이드 판정 — 요구사항별 상세 (method/status/reason)
    judgments = [e for e in rec.events if e["kind"] == "judgment"]
    assert judgments and judgments[0]["detail"]["matches"]
    first = judgments[0]["detail"]["matches"][0]
    assert {"requirementId", "status", "method", "reason"} <= set(first)
    # LLM 계층 — 미설정이면 미설정 이벤트로라도 기록된다 (누가 호출됐는지 항상 보임)
    assert any(e["kind"] == "llm_call" for e in rec.events)
    # 응답은 정상
    assert response.dispatched == ["fit_analysis"]


def test_trace_events_are_ordered():
    with trace.recording() as rec:
        handle_chat(_request("이 공고 나 되나?"))
    seqs = [e["seq"] for e in rec.events]
    assert seqs == sorted(seqs) and seqs[0] == 1


# --- DB 왕복 -------------------------------------------------------------------
def test_run_store_roundtrip(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite3")
    run_id = store.save_run(
        session_id="s1", message="이 공고 나 되나?",
        resume_text="이력서 원문", posting_text="공고 원문",
        response={"reply": "완료", "dispatched": ["fit_analysis"]},
        trace_events=[{"seq": 1, "kind": "dispatch", "label": "l", "detail": {}, "elapsedMs": 0}],
    )

    listed = store.list_runs()
    assert len(listed) == 1 and listed[0]["id"] == run_id
    assert "resume_text" not in listed[0]  # 목록은 요약만

    record = store.get_run(run_id)
    assert record["resume_text"] == "이력서 원문"
    assert record["response"]["dispatched"] == ["fit_analysis"]
    assert record["trace"][0]["kind"] == "dispatch"
    assert store.get_run("missing") is None
