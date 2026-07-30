"""URL 공고 인입 테스트 (D62) — 규약 셋을 강제한다.

① 발화의 URL 감지는 **결정론**이다(LLM 없음) — 같은 주소는 두 번 등록하지 않는다.
② URL 은 **공고 전용**이다 — 어떤 kind 로 와도 job_posting 으로 저장된다.
③ URL 자산은 첫 소비자가 한 번 수집해 **원문 텍스트로 승격**한다(sourceUrl 보존).
   수집 실패면 자산을 바꾸지 않고 경고만 올린다(다음 턴 재시도 여지).
"""

from __future__ import annotations

import pytest

from jobis_ai.agents._common import ensure_posting_text
from jobis_ai.contracts.api import ChatAttachment, ChatRequest, SourceType
from jobis_ai.extract import ExtractResult
from jobis_ai.orchestrator import session as session_mod
from jobis_ai.orchestrator.chat import detect_posting_url, handle_chat
from jobis_ai.orchestrator.planner import AgentPlan
from jobis_ai.orchestrator.session import SessionStore

_URL = "https://www.jobkorea.co.kr/Recruit/GI_Read/49664777?Oem_Code=C1"


@pytest.fixture(autouse=True)
def fresh_session_store(monkeypatch):
    store = SessionStore()
    monkeypatch.setattr(session_mod, "_STORE", store)
    return store


@pytest.fixture(autouse=True)
def offline_fetch(monkeypatch):
    """URL 턴은 posting_fetch(D64)가 도는데, 테스트가 실제 네트워크를 타면 안 된다.
    기본은 '수집 실패'로 막고, 성공 경로가 필요한 테스트는 _stub_fetch 로 덮는다."""

    _stub_fetch(monkeypatch, "",
                warnings=[{"code": "url_fetch_error", "message": "test: 네트워크 차단"}])


def _stub_planner(monkeypatch, agents):
    plan = AgentPlan(agents=list(agents), requestedAgents=list(agents),
                     confidence=0.9, ack="")
    monkeypatch.setattr("jobis_ai.orchestrator.chat.plan_agents",
                        lambda message, session: (plan, []))


# --- ① 발화 URL 감지 (결정론) --------------------------------------------------
def test_detect_url_in_message_strips_trailing_punctuation():
    assert detect_posting_url(f"이 공고 분석해줘 {_URL}. 부탁해", {}) == _URL


def test_detect_url_none_when_no_url():
    assert detect_posting_url("백엔드 공고 추천해줘", {}) == ""


def test_detect_url_skips_already_registered_posting():
    # 미수집(url 자산) 상태 — value 가 같은 주소
    assert detect_posting_url(_URL, {"job_posting": {"sourceType": "url", "value": _URL}}) == ""
    # 원문 승격 뒤 — sourceUrl 로 남은 같은 주소
    promoted = {"sourceType": "text", "value": "공고 원문", "sourceUrl": _URL}
    assert detect_posting_url(_URL, {"job_posting": promoted}) == ""


def test_chat_message_url_registers_posting_asset(fresh_session_store):
    """URL 을 붙여넣으면 공고 자산으로 등록되고, 접수 확인이 답변에 실린다."""

    res = handle_chat(ChatRequest(sessionId="u1", message=f"{_URL} 이 공고 분석해줘"))
    stored = fresh_session_store.get("u1")
    assert stored["job_posting"] == {"sourceType": "url", "value": _URL}
    assert "공고 링크를 받았어요." in res.reply


def test_chat_same_url_twice_does_not_rereg(fresh_session_store):
    """같은 주소를 다시 붙여도 재등록·분석 무효화가 일어나지 않는다."""

    handle_chat(ChatRequest(sessionId="u2", message=_URL))
    fresh_session_store.update("u2", {"analysis": {"status": "completed"}})
    res = handle_chat(ChatRequest(sessionId="u2", message=f"{_URL} 다시 봐줘"))
    assert "공고 링크를 받았어요." not in res.reply
    assert fresh_session_store.get("u2")["analysis"] == {"status": "completed"}


def test_chat_new_url_invalidates_old_analysis(fresh_session_store):
    """다른 공고 링크가 오면 이전 공고의 분석 자산은 무효다(첨부와 같은 규약)."""

    handle_chat(ChatRequest(sessionId="u3", message=_URL))
    fresh_session_store.update("u3", {"analysis": {"status": "completed"}})
    other = "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=54548292"
    handle_chat(ChatRequest(sessionId="u3", message=f"이건 어때 {other}"))
    stored = fresh_session_store.get("u3")
    assert stored["job_posting"]["value"] == other
    assert not stored.get("analysis")


# --- ② URL 첨부는 공고 전용 -----------------------------------------------------
def test_url_attachment_coerced_to_posting(fresh_session_store):
    """이력서 kind 로 온 URL 첨부도 공고로 저장된다 — 이유는 경고로 남는다."""

    att = ChatAttachment(kind="resume", sourceType=SourceType.url, value=_URL)
    res = handle_chat(ChatRequest(sessionId="u4", message="", attachments=[att]))
    stored = fresh_session_store.get("u4")
    assert stored["job_posting"] == {"sourceType": "url", "value": _URL}
    assert not stored.get("resume")
    assert any(w.get("code") == "url_posting_only" for w in res.warnings)
    assert "공고 링크로 등록했어요" in res.reply


# --- ③ 원문 승격 (ensure_posting_text) -----------------------------------------
def _stub_fetch(monkeypatch, text: str, warnings: list[dict] | None = None):
    def _fake(source):
        result = ExtractResult(text=text)
        result.warnings = list(warnings or [])
        return result

    monkeypatch.setattr("jobis_ai.extract.extract_text", _fake)


def test_ensure_posting_text_promotes_url_to_text(monkeypatch):
    _stub_fetch(monkeypatch, "백엔드 개발자 모집. 필수: Python 3년.")
    staged: dict = {}
    session = {"job_posting": {"sourceType": "url", "value": _URL}, "_stagedUpdates": staged}

    promoted, warnings = ensure_posting_text(session)

    expected = {"sourceType": "text", "value": "백엔드 개발자 모집. 필수: Python 3년.",
                "sourceUrl": _URL}
    assert promoted == expected
    assert session["job_posting"] == expected      # 이번 턴의 뒤 단계가 바로 쓴다
    assert staged["job_posting"] == expected       # write-back 으로 저장된다
    assert warnings == []


def test_ensure_posting_text_keeps_asset_on_fetch_failure(monkeypatch):
    """수집 실패면 자산을 바꾸지 않는다 — 경고만 올린다(폴백은 이유를 삼키지 않는다)."""

    fail = [{"code": "url_fetch_error", "message": "URL 요청 실패"}]
    _stub_fetch(monkeypatch, "", warnings=fail)
    original = {"sourceType": "url", "value": _URL}
    session = {"job_posting": dict(original), "_stagedUpdates": {}}

    posting, warnings = ensure_posting_text(session)

    assert posting == original
    assert session["_stagedUpdates"] == {}
    assert any(w["code"] == "url_fetch_error" for w in warnings)


def test_ensure_posting_text_passthrough_for_text_asset():
    """텍스트 자산은 손대지 않는다 — 수집도 스테이징도 없다."""

    session = {"job_posting": {"sourceType": "text", "value": "공고 원문"}, "_stagedUpdates": {}}
    posting, warnings = ensure_posting_text(session)
    assert posting == {"sourceType": "text", "value": "공고 원문"}
    assert session["_stagedUpdates"] == {} and warnings == []


# --- ④ posting_fetch 도구 (D64) — 수집과 파싱의 분리 -----------------------------
def test_posting_fetch_hidden_from_planner_manifest():
    """internal 도구는 플래너 어휘에 없다 — 오케스트레이터만 끼울 수 있다."""

    from jobis_ai.orchestrator.planner import _build_manifest

    assert "posting_fetch" not in _build_manifest()


def test_chat_url_turn_fetches_before_consumers(fresh_session_store, monkeypatch):
    """URL 공고 턴은 수집 도구가 결정론으로 맨 앞에 돌고, 원문이 자산으로 굳는다."""

    _stub_fetch(monkeypatch, "백엔드 개발자 모집. 자격요건: Python, Django 3년 이상.")
    _stub_planner(monkeypatch, ["posting_analysis"])
    res = handle_chat(ChatRequest(sessionId="f1", message=f"이 공고 분석해줘 {_URL}"))

    assert res.dispatched[:2] == ["posting_fetch", "posting_analysis"]
    stored = fresh_session_store.get("f1")["job_posting"]
    assert stored["sourceType"] == "text" and stored["sourceUrl"] == _URL


def test_chat_url_fetch_failure_drops_consumers_and_asks(fresh_session_store, monkeypatch):
    """수집이 실패하면 공고 소비 단계는 돌지 않고(빈 원문 파싱 방지), 사용자에게
    본문을 청한다. 자산은 URL 형태로 남아 다음 턴에 재시도할 수 있다."""

    _stub_fetch(monkeypatch, "", warnings=[{"code": "url_fetch_error", "message": "실패"}])
    _stub_planner(monkeypatch, ["posting_analysis"])
    res = handle_chat(ChatRequest(sessionId="f2", message=f"이 공고 분석해줘 {_URL}"))

    assert res.dispatched == ["posting_fetch"]          # 소비 단계는 걷어냈다
    assert "읽어오지 못했어요" in res.reply               # 실패는 도구의 표현이 말한다
    assert "진행하지 못했어요" in res.reply               # 무엇을 안 했는지는 관찰 규칙이 말한다
    assert fresh_session_store.get("f2")["job_posting"]["sourceType"] == "url"
    assert any(q.get("field") == "job_posting" for q in res.followUpQuestions)


def test_drop_posting_consumers_rule():
    """관찰 규칙 ③ 단위 — 공고 전제 단계만 빠지고 나머지는 남는다."""

    from jobis_ai.orchestrator.observe_rules import drop_posting_consumers

    kept, note = drop_posting_consumers(["posting_analysis", "career_chat"], [])
    assert kept == ["career_chat"]
    assert "공고 분석" in note


# ---------------------------------------------------------------------------
# 스킴 없는 주소 — 발화 전체가 도메인/경로 한 토큰일 때만 (실측 2026-07-30: 사람인)
# ---------------------------------------------------------------------------
def test_detect_schemeless_url_when_whole_message_is_address():
    pasted = ("saramin.co.kr/zf_user/jobs/relay/view?view_type=search&rec_idx=54347596"
              "&searchword=ai엔지니어&searchType=search")
    assert detect_posting_url(pasted, {}) == f"https://{pasted}"


def test_detect_schemeless_requires_path_and_single_token():
    assert detect_posting_url("github.com에 포트폴리오 올렸어요", {}) == ""   # 문장 속 도메인
    assert detect_posting_url("saramin.co.kr 여기 공고 봐줘", {}) == ""      # 여러 토큰
    assert detect_posting_url("wanted.co.kr", {}) == ""                      # 경로 없음


def test_detect_schemeless_dedupes_against_registered_posting():
    url = "https://saramin.co.kr/zf_user/jobs/view?rec_idx=1"
    session = {"job_posting": {"sourceType": "url", "value": url}}
    assert detect_posting_url("saramin.co.kr/zf_user/jobs/view?rec_idx=1", session) == ""
