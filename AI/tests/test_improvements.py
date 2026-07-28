"""멀티에이전트 개선방안(_docs/agent) 반영분 테스트.

- 재계획 루프(§2-1): 에이전트 하나 실행 후 결과를 보고 계속/중단/수정을 다시 정한다.
- 세션 write-back(§3-5): 턴에 읽기 1회·쓰기 1회.
- 입력 절단 휴리스틱(§4): 후반부 자격요건/우대사항을 버리지 않는다.
- MemorySessionStore 깊은 복사(§4): 복사본 규약이 중첩 dict 에도 성립.
- intent 라벨(§4): 검증기가 계획을 바꾸면 라벨도 실제 실행 시퀀스를 따른다.
"""

from __future__ import annotations

import pytest

from jobis_ai.contracts.api import ChatAttachment, ChatRequest, SourceType
from jobis_ai.orchestrator import session as session_mod
from jobis_ai.orchestrator.chat import handle_chat
from jobis_ai.orchestrator.planner import AgentPlan, ReplanDecision
from jobis_ai.orchestrator.session import SessionStore
from jobis_ai.structured import _truncate


@pytest.fixture(autouse=True)
def fresh_session_store(monkeypatch):
    store = SessionStore()
    monkeypatch.setattr(session_mod, "_STORE", store)
    return store


def stub_planner(monkeypatch, agents, ack: str = ""):
    plan = AgentPlan(agents=list(agents), confidence=0.9, ack=ack)
    monkeypatch.setattr("jobis_ai.orchestrator.chat.plan_agents",
                        lambda message, session: (plan, []))


def _resume() -> ChatAttachment:
    return ChatAttachment(kind="resume", sourceType=SourceType.text,
                          value="Python Django 백엔드 개발 3년")


def _posting() -> ChatAttachment:
    return ChatAttachment(kind="job_posting", sourceType=SourceType.text,
                          value="백엔드 개발자 모집. 필수: Python, Django 3년.")


# --- 재계획 루프 (§2-1) --------------------------------------------------------
def test_replan_stop_halts_remaining_agents(monkeypatch):
    """재계획이 stop 을 내면 남은 에이전트를 돌리지 않는다 — 결과를 보고 다시 정하는 루프.

    (posting_analysis 처럼 후속 질문을 내는 에이전트는 기존 규칙으로 이미 멈추므로,
    후속 질문 없는 career_chat 을 첫 자리에 둬 재계획 경로만 분리해 본다.)
    """

    stub_planner(monkeypatch, ["career_chat", "resume_diagnosis"])
    monkeypatch.setattr(
        "jobis_ai.orchestrator.chat.replan_after",
        lambda executed, outcome, remaining, session: ReplanDecision(
            action="stop", reason="앞 결과로 이번 턴을 끝내는 게 낫다"),
    )
    res = handle_chat(ChatRequest(
        sessionId="rp1", message="고민 들어주고 이력서도 진단해줘",
        attachments=[_resume()],
    ))
    assert res.dispatched == ["career_chat"]          # 두 번째는 실행되지 않았다


def test_replan_none_keeps_original_sequence(monkeypatch):
    """재계획 불가(LLM 미설정) → 예정대로 계속 — 기존 동작이 그대로 보존된다."""

    stub_planner(monkeypatch, ["career_chat", "resume_diagnosis"])
    res = handle_chat(ChatRequest(
        sessionId="rp2", message="고민 들어주고 이력서도 진단해줘",
        attachments=[_resume()],
    ))
    assert res.dispatched == ["career_chat", "resume_diagnosis"]


def test_replan_not_called_for_single_agent_turn(monkeypatch):
    """단일 에이전트 턴에는 재계획을 부르지 않는다 — 턴 지연을 늘리지 않는다."""

    calls = []
    stub_planner(monkeypatch, ["resume_diagnosis"])
    monkeypatch.setattr(
        "jobis_ai.orchestrator.chat.replan_after",
        lambda *a, **k: calls.append(1),
    )
    handle_chat(ChatRequest(sessionId="rp3", message="이력서 진단해줘",
                            attachments=[_resume()]))
    assert not calls


# --- 세션 write-back (§3-5) ----------------------------------------------------
def test_turn_reads_once_and_writes_once(monkeypatch, fresh_session_store):
    """한 턴에 저장소 읽기 1회·쓰기 1회 — 첨부·last_message·이력이 한 번에 저장된다."""

    reads, writes = [], []
    orig_get, orig_update = fresh_session_store.get, fresh_session_store.update
    monkeypatch.setattr(fresh_session_store, "get",
                        lambda sid: reads.append(sid) or orig_get(sid))
    monkeypatch.setattr(fresh_session_store, "update",
                        lambda sid, u: writes.append(sorted(u)) or orig_update(sid, u))

    stub_planner(monkeypatch, ["resume_diagnosis"])
    handle_chat(ChatRequest(sessionId="wb1", message="이력서 진단해줘",
                            attachments=[_resume()]))
    assert len(reads) == 1
    assert len(writes) == 1
    # 첨부·발화·이력이 마지막 한 번의 쓰기에 전부 실려 있다
    assert {"resume", "last_message", "history"} <= set(writes[0])

    # 저장 결과도 온전하다 — 다음 턴이 이 자산을 읽는다
    saved = orig_get("wb1")
    assert saved.get("resume") and saved.get("history")


# --- 입력 절단 휴리스틱 (§4) ---------------------------------------------------
def test_truncate_preserves_requirement_sections():
    """긴 공고를 자를 때 후반부의 자격요건/우대사항을 버리지 않는다."""

    filler = "회사 소개와 복지 이야기. " * 2000            # 앞부분 노이즈 (>16000자)
    tail = "자격요건: Python 3년, Django 실무. 우대사항: AWS."
    warnings: list[dict] = []
    out = _truncate(filler + tail, "test", warnings)
    assert "자격요건: Python 3년" in out
    assert warnings and warnings[0]["code"] == "input_truncated"


def test_truncate_short_input_untouched():
    warnings: list[dict] = []
    assert _truncate("짧은 입력", "test", warnings) == "짧은 입력"
    assert not warnings


# --- MemorySessionStore 깊은 복사 (§4) -----------------------------------------
def test_memory_store_returns_deep_copies(fresh_session_store):
    """get() 복사본의 중첩 dict 를 고쳐도 저장분이 오염되지 않는다 — SQLite 와 동일 규약."""

    fresh_session_store.update("dc1", {"resume": {"sourceType": "text", "value": "원본"}})
    copy1 = fresh_session_store.get("dc1")
    copy1["resume"]["value"] = "오염 시도"
    assert fresh_session_store.get("dc1")["resume"]["value"] == "원본"


# --- intent 라벨 (§4) ----------------------------------------------------------
def test_intent_label_follows_actual_dispatch(monkeypatch):
    """검증기가 실행 불가 에이전트를 빼면 intent 라벨도 실제 실행을 따른다.

    이력서 없이 fit_analysis 를 골랐다 → posting_analysis 만 실행 →
    프론트에 나가는 intent 도 posting_analysis (원안 fit_analysis 가 아니라).
    """

    stub_planner(monkeypatch, ["fit_analysis", "posting_analysis"])
    res = handle_chat(ChatRequest(
        sessionId="lb1", message="이 공고 나 되나?", attachments=[_posting()],
    ))
    assert res.dispatched == ["posting_analysis"]
    assert res.intent == "posting_analysis"
