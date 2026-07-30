"""에이전트 시퀀스 병렬 실행 (평가 문서 §3 남은 축).

계약:
- 서로의 산출을 기다리지 않는 연속 구간만 동시에 돈다. 의존이 있으면 거기서 끊는다.
- 병렬로 돌아도 **결과 순서는 계획 순서**다(답변·dispatched·세션 반영 전부).
- 각 에이전트는 세션 사본을 받는다 — 남의 턴 내부 캐시를 보고 판단하지 않는다.
- 관찰은 구간 **뒤에 한 번**. 중간 재선택 지점을 포기하는 것이 이 최적화의 대가다.
- 병렬 구간에서는 토큰 델타를 끈다(프론트가 한 버퍼에 이어 붙여 섞인다).
"""

from __future__ import annotations

import threading
import time

from jobis_ai.agents import AgentResult
from jobis_ai.contracts.api import ChatAttachment, ChatRequest, SourceType
from jobis_ai.orchestrator.chat import handle_chat, parallel_group
from jobis_ai.orchestrator.planner import AgentPlan


def _stub_planner(monkeypatch, agents):
    plan = AgentPlan(agents=list(agents), requestedAgents=list(agents),
                     confidence=0.9, ack="")
    monkeypatch.setattr("jobis_ai.orchestrator.chat.plan_agents",
                        lambda message, session: (plan, []))


def _resume() -> ChatAttachment:
    return ChatAttachment(kind="resume", sourceType=SourceType.text,
                          value="Python Django 백엔드 개발 3년")


def _posting() -> ChatAttachment:
    return ChatAttachment(kind="job_posting", sourceType=SourceType.text,
                          value="백엔드 개발자 채용. 자격요건: Python, Django 3년 이상")


# --- 구간 선택 (순수 함수) --------------------------------------------------------
def test_independent_prefix_is_grouped():
    """공고 정리 ∥ 이력서 진단 — 둘 다 지금 가능하고 서로의 산출을 안 쓴다."""

    session = {"resume": {"sourceType": "text", "value": "x"},
               "job_posting": {"sourceType": "text", "value": "y"}}
    assert parallel_group(["posting_analysis", "resume_diagnosis"], [], session) == [
        "posting_analysis", "resume_diagnosis"]


def test_group_breaks_at_dependency():
    """앞이 만드는 자산을 뒤가 전제로 쓰면 거기서 끊는다 — 순서가 있는 일이다."""

    session = {"resume": {"sourceType": "text", "value": "x"}}
    # preference_intake → preferences → job_recommend(preferences/resume 로 동작)
    assert parallel_group(["preference_intake", "job_recommend"], [], session) == [
        "preference_intake"]


def test_group_breaks_at_not_runnable():
    """지금 못 도는 것은 앞 단계가 만들어 줘야 한다 — 동시에 태우지 않는다."""

    session = {"resume": {"sourceType": "text", "value": "x"},
               "job_posting": {"sourceType": "text", "value": "y"}}
    # coverletter_draft 는 analysis 가 있어야 하고, 그것을 fit_analysis 가 만든다
    assert parallel_group(["fit_analysis", "coverletter_draft"], [], session) == ["fit_analysis"]


# --- 실행 ------------------------------------------------------------------------
def test_group_runs_concurrently_and_keeps_plan_order(monkeypatch):
    """동시에 돌지만 답변·dispatched 순서는 계획 순서를 지킨다."""

    running: list[str] = []
    peak = {"n": 0}
    lock = threading.Lock()

    def _slow(name: str):
        def run(session):
            with lock:
                running.append(name)
                peak["n"] = max(peak["n"], len(running))
            time.sleep(0.15)          # 겹칠 시간을 준다
            with lock:
                running.remove(name)
            return AgentResult(reply=f"{name} 결과")
        return run

    # **에이전트**로 검증한다 — 도구(posting_analysis 등)는 표현 계층이 reply 를 덮으므로
    # 스텁 문장이 답변에 남지 않는다(0729 표현 분리). 순서·동시성 계약은 성격이 같다.
    monkeypatch.setattr("jobis_ai.agents.career_chat.run", _slow("career_chat"))
    monkeypatch.setattr("jobis_ai.agents.preference_intake.run", _slow("preference_intake"))
    _stub_planner(monkeypatch, ["career_chat", "preference_intake"])

    started = time.perf_counter()
    res = handle_chat(ChatRequest(sessionId="par-1", message="공고랑 이력서 봐줘",
                                  attachments=[_resume(), _posting()]))
    elapsed = time.perf_counter() - started

    assert peak["n"] == 2, "둘이 동시에 돌아야 한다"
    assert elapsed < 0.30, "순차였다면 0.3초를 넘긴다"
    assert res.dispatched == ["career_chat", "preference_intake"]
    assert res.reply.index("career_chat 결과") < res.reply.index("preference_intake 결과")


def test_parallel_members_get_session_copies(monkeypatch):
    """각자 사본을 받는다 — 같은 구간의 다른 에이전트가 턴 중에 넣은 값을 보지 않는다.

    보이게 두면 실행 순서(스레드 스케줄)에 따라 판단이 달라진다 — 병렬의 가장 나쁜 실패다.
    """

    seen: dict[str, bool] = {}

    def _writer(session):
        session["profile"] = {"skills": [{"name": "몰래 넣은 값"}]}
        return AgentResult(reply="공고 정리")

    def _reader(session):
        seen["sawWriterValue"] = (session.get("profile") or {}).get("skills") == [
            {"name": "몰래 넣은 값"}]
        return AgentResult(reply="이력서 진단")

    monkeypatch.setattr("jobis_ai.agents.posting_analysis.run", _writer)
    monkeypatch.setattr("jobis_ai.agents.resume_diagnosis.run", _reader)
    _stub_planner(monkeypatch, ["posting_analysis", "resume_diagnosis"])

    handle_chat(ChatRequest(sessionId="par-2", message="둘 다 봐줘",
                            attachments=[_resume(), _posting()]))
    assert seen["sawWriterValue"] is False


def test_parallel_group_is_traced(monkeypatch):
    """무엇을 왜 동시에 돌렸는지 궤적에 남는다 — 안 남기면 순서 문제를 사후에 못 쫓는다."""

    from jobis_ai import trace

    monkeypatch.setattr("jobis_ai.agents.posting_analysis.run",
                        lambda s: AgentResult(reply="공고 정리"))
    monkeypatch.setattr("jobis_ai.agents.resume_diagnosis.run",
                        lambda s: AgentResult(reply="이력서 진단"))
    _stub_planner(monkeypatch, ["posting_analysis", "resume_diagnosis"])

    with trace.recording() as rec:
        handle_chat(ChatRequest(sessionId="par-3", message="둘 다 봐줘",
                                attachments=[_resume(), _posting()]))
    events = [e for e in rec.events if e["kind"] == "parallel"]
    assert events, "병렬 실행 사실이 궤적에 남아야 한다"
    assert events[0]["detail"]["agents"] == ["posting_analysis", "resume_diagnosis"]
    # 워커 스레드에서도 에이전트 이벤트가 보여야 한다(컨텍스트를 복사해 넘긴다)
    agent_events = {e["detail"].get("agent") for e in rec.events if e["kind"] == "agent_start"}
    assert {"posting_analysis", "resume_diagnosis"} <= agent_events


def test_tokens_are_muted_inside_parallel_group(monkeypatch):
    """병렬 구간의 토큰 델타는 중계하지 않는다 — 두 에이전트 토큰이 한 버퍼에서 섞인다."""

    from jobis_ai import trace

    def _streamer(session):
        trace.emit("token", "", {"node": "x", "text": "조각"})
        return AgentResult(reply="공고 정리")

    monkeypatch.setattr("jobis_ai.agents.posting_analysis.run", _streamer)
    monkeypatch.setattr("jobis_ai.agents.resume_diagnosis.run",
                        lambda s: AgentResult(reply="이력서 진단"))
    _stub_planner(monkeypatch, ["posting_analysis", "resume_diagnosis"])

    seen: list[dict] = []
    with trace.recording(sink=seen.append):
        handle_chat(ChatRequest(sessionId="par-4", message="둘 다 봐줘",
                                attachments=[_resume(), _posting()]))
    assert not [e for e in seen if e["kind"] == "token"]
    # 진행 이벤트는 그대로 흘러야 한다 — 끈 것은 토큰뿐이다
    assert [e for e in seen if e["kind"] == "agent_start"]


def test_single_runnable_agent_stays_sequential(monkeypatch):
    """혼자면 병렬 경로로 새지 않는다 — 기존 동작 그대로."""

    from jobis_ai import trace

    monkeypatch.setattr("jobis_ai.agents.resume_diagnosis.run",
                        lambda s: AgentResult(reply="이력서 진단"))
    _stub_planner(monkeypatch, ["resume_diagnosis"])
    with trace.recording() as rec:
        res = handle_chat(ChatRequest(sessionId="par-5", message="이력서 봐줘",
                                      attachments=[_resume()]))
    assert res.dispatched == ["resume_diagnosis"]
    assert not [e for e in rec.events if e["kind"] == "parallel"]
