"""대화 오케스트레이터 테스트 — 하네스와 에이전트 동작.

**추론은 자율, 행동과 상태 전이는 하네스로 좁힌다.** 무엇을 할지 고르는 것은 플래너 LLM 의
일이라 (발화 × 자산) 대응표가 코드에 없다 — 그 판단 품질은 evals/planner_dataset.json +
eval/planner_harness.py 가 측정한다. 여기서는 플래너의 선택을 주입해 두고
**그 뒤 하네스가 무엇을 하는지**를 결정적으로 검증한다.

LLM 은 conftest 가 강제 미설정하므로 에이전트들은 결정론 폴백 문구로 답한다.
"""

from __future__ import annotations

import pytest

from jobis_ai.contracts.api import ChatAttachment, ChatRequest, SourceType
from jobis_ai.orchestrator import session as session_mod
from jobis_ai.orchestrator.chat import handle_chat
from jobis_ai.orchestrator.planner import AgentPlan
from jobis_ai.orchestrator.session import SessionStore


@pytest.fixture(autouse=True)
def fresh_session_store(monkeypatch):
    """테스트 간 세션 격리 — 전역 스토어를 매 테스트 새로 만든다."""

    store = SessionStore()
    monkeypatch.setattr(session_mod, "_STORE", store)
    return store


def stub_planner(monkeypatch, agents, ack: str = ""):
    """플래너의 선택을 주입한다 — LLM 추론을 대신하되 뒤 단계는 실제 코드가 돈다."""

    # requestedAgents=agents — 이 스텁은 "사용자가 이 기능을 청했다"는 뜻이다(게이트 동작은
    # test_planner.py 가 따로 본다).
    plan = AgentPlan(agents=list(agents), requestedAgents=list(agents),
                     confidence=0.9, ack=ack)
    monkeypatch.setattr("jobis_ai.orchestrator.chat.plan_agents",
                        lambda message, session: (plan, []))


def _resume_attachment() -> ChatAttachment:
    return ChatAttachment(kind="resume", sourceType=SourceType.text,
                          value="Python Django 백엔드 개발 3년")


def _posting_attachment(value: str = "백엔드 개발자 모집. 필수: Python, Django 3년.") -> ChatAttachment:
    return ChatAttachment(kind="job_posting", sourceType=SourceType.text, value=value)


# --- 세션 스토어 --------------------------------------------------------------
def test_session_isolation_and_key_guard(fresh_session_store):
    fresh_session_store.update("a", {"resume": {"v": 1}})
    assert fresh_session_store.get("b") == {}          # 세션 격리
    with pytest.raises(KeyError):
        fresh_session_store.update("a", {"hacked": True})  # 미허용 키 차단


# --- 대화 왕복 ----------------------------------------------------------------
def test_chat_without_planner_opens_conversation():
    """플래너가 없어도(LLM 미설정) **대화로 받는다** — 기능 목록만 읽어주고 끝내지 않는다."""

    res = handle_chat(ChatRequest(sessionId="s1", message="안녕하세요"))
    assert res.dispatched == ["career_chat"]
    assert res.reply.strip()


def test_chat_preference_intake_opens_dialog(monkeypatch):
    """이력서 없는 추천 요청에 플래너가 선호 파악을 고르면 → 닫힌 되묻기 없이 대화가 열린다."""

    stub_planner(monkeypatch, ["preference_intake"])
    res = handle_chat(ChatRequest(sessionId="s2", message="공고 추천해줘"))
    assert res.dispatched == ["preference_intake"]
    assert "직군" in res.reply            # 어떤 공고를 원하는지 묻는다
    assert res.followUpQuestions          # 대화가 이어질 신호


def test_chat_attachment_only_continues():
    """자료만 준 턴도 **멈추지 않는다** — 접수 확인 + 실행까지 이어진다."""

    res = handle_chat(ChatRequest(sessionId="s3", attachments=[_resume_attachment()]))
    assert "이력서를 받았어요" in res.reply   # 접수 확인은 유지
    assert res.dispatched                    # 그리고 실행까지 이어진다


def test_chat_recommend_flow_without_rag_is_honest(monkeypatch):
    """이력서 첨부 + 추천 실행 → RAG 미연결이면 허구 추천 없이 정직한 응답."""

    stub_planner(monkeypatch, ["job_recommend"])
    res = handle_chat(ChatRequest(
        sessionId="s4", message="내 이력서로 갈 수 있는 곳 추천해줘",
        attachments=[_resume_attachment()],
    ))
    assert res.dispatched == ["job_recommend"]
    assert res.intent == "job_recommend"
    assert "추천" in res.reply
    # NullRagAdapter 환경 — 추천을 지어내지 않는다
    assert res.results["job_recommend"]["recommendations"] == []


def test_chat_posting_only_runs_posting_analysis(monkeypatch):
    """공고만 있는 상태 — 공고 정리 결과를 주고 이력서를 자연스럽게 요청한다."""

    stub_planner(monkeypatch, ["posting_analysis"])
    res = handle_chat(ChatRequest(
        sessionId="s6", message="이 공고 나 되나?", attachments=[_posting_attachment()],
    ))
    assert res.dispatched == ["posting_analysis"]
    assert "이력서" in res.reply                      # 결과를 주고 자연스럽게 요청
    assert res.followUpQuestions                      # 다음 입력 유도
    assert res.results["posting_analysis"]["postingAnalysis"]


def test_chat_infeasible_choice_falls_back_to_conversation(monkeypatch):
    """플래너가 지금 못 할 일을 골라도 실행하지 않는다 — 대화형 에이전트가 턴을 받는다.

    액션 스페이스 제한의 사후 검증: 상태 전이는 실행 가능한 것만 일으킨다.
    """

    stub_planner(monkeypatch, ["fit_analysis"])   # 이력서 없음 → 실행 불가
    res = handle_chat(ChatRequest(
        sessionId="s8", message="이 공고 나 되나?", attachments=[_posting_attachment()],
    ))
    assert res.dispatched == ["career_chat"]
    assert res.reply.strip()


def test_chat_heavy_precondition_asks_consent(monkeypatch):
    """무거운 생산자(fit_analysis)가 자동 삽입될 상황 — 말없이 시작하지 않고 먼저 묻는다.

    수십 초·LLM 여러 회짜리 파이프라인은 note 로 알리며 시작하는 게 아니라,
    실행 전에 동의를 받는다(동의 게이트). 동의하면 다음 턴 플래너가 명시적으로 고른다.
    """

    stub_planner(monkeypatch, ["coverletter_draft"])
    res = handle_chat(ChatRequest(
        sessionId="s9", message="자소서 써줘",
        attachments=[_resume_attachment(), _posting_attachment()],
    ))
    assert res.dispatched == []                       # 아직 아무것도 실행하지 않았다
    assert "진행할까요" in res.reply                   # 먼저 묻는다
    assert any(q.get("field") == "confirm_pipeline" for q in res.followUpQuestions)


def test_chat_explicit_heavy_producer_runs_without_gate(monkeypatch):
    """플래너가 fit_analysis 를 명시적으로 골랐으면(동의 턴) 게이트 없이 그대로 실행한다."""

    stub_planner(monkeypatch, ["fit_analysis", "coverletter_draft"])
    res = handle_chat(ChatRequest(
        sessionId="s9b", message="응 진행해줘",
        attachments=[_resume_attachment(), _posting_attachment()],
    ))
    assert res.dispatched[0] == "fit_analysis"


def test_chat_planner_ack_is_visible_when_it_explains_a_plan(monkeypatch):
    """ack 는 **계획을 설명할 때** 실린다 — 여러 에이전트를 돌면 순서를 알려야 한다."""

    stub_planner(monkeypatch, ["posting_analysis", "resume_diagnosis"],
                 ack="공고를 먼저 정리하고 이력서를 진단할게요.")
    res = handle_chat(ChatRequest(
        sessionId="s5b", message="공고랑 이력서 다 봐줘",
        attachments=[_resume_attachment(), _posting_attachment()],
    ))
    assert len(res.dispatched) > 1
    assert "공고를 먼저 정리하고 이력서를 진단할게요." in res.reply


def test_chat_ack_dropped_when_single_agent_speaks_for_itself(monkeypatch):
    """에이전트 하나가 스스로 말하면 ack 를 싣지 않는다 — 같은 말을 두 번 하게 된다.

    실측(2026-07-29): 면접 턴이 "면접 연습을 시작하겠습니다. 면접 연습을 시작하겠습니다.
    첫 질문입니다: …" 로 나갔다. ack(플래너)와 에이전트 첫 문장이 같은 말이었다.
    라우팅 가시화는 ack 가 아니라 `intent` 가 맡는다(프론트가 에이전트 이름을 표시한다).
    """

    stub_planner(monkeypatch, ["resume_diagnosis"], ack="이력서 진단으로 이해했어요.")
    res = handle_chat(ChatRequest(
        sessionId="s5", message="이력서 진단해줘", attachments=[_resume_attachment()],
    ))
    assert res.dispatched == ["resume_diagnosis"]
    assert "이력서 진단으로 이해했어요." not in res.reply
    assert res.reply.strip(), "에이전트의 말은 그대로 남는다"
    assert res.intent == "resume_diagnosis", "라우팅 가시화는 intent 로 유지된다"


def test_chat_forbidden_ack_is_dropped(monkeypatch):
    """표현 계층도 검증을 면제받지 않는다 — 금지표현이 섞인 ack 는 버린다."""

    stub_planner(monkeypatch, ["resume_diagnosis"], ack="합격 가능성이 낮습니다. 진단할게요.")
    res = handle_chat(ChatRequest(
        sessionId="s10", message="이력서 진단해줘", attachments=[_resume_attachment()],
    ))
    assert "합격 가능성" not in res.reply


def test_posting_analysis_seniority_shows_posting_wording():
    """연차 표기는 공고가 한 말(yearsEvidence)을 그대로 — 사다리 라벨("주니어 신입")은
    공고에 없는 단어("신입")를 만들 수 있어 숫자 근거가 있으면 쓰지 않는다."""

    from jobis_ai.agents.tool_render import _seniority_line

    line = _seniority_line({
        "jobTitle": "백엔드 개발자",
        "seniority": "junior",
        "minYears": 2,
        "yearsEvidence": "경력 2년 이상",
    })
    assert "경력 2년 이상" in line
    assert "junior" not in line and "신입" not in line


def test_posting_analysis_seniority_evidence_fallback_from_text():
    """옛 캐시(yearsEvidence 없음)면 원문 항목에서 표기를 찾아 쓴다."""

    from jobis_ai.agents.tool_render import _seniority_line

    line = _seniority_line({
        "jobTitle": "백엔드 개발자",
        "seniority": "junior",
        "requiredRequirements": [{"text": "Python 실무 경험 2년 이상"}],
    })
    assert "2년 이상" in line and "신입" not in line


def test_posting_analysis_seniority_without_evidence():
    """숫자 근거가 아예 없으면(키워드만) 사다리 라벨을 키워드 기준으로 표기한다."""

    from jobis_ai.agents.tool_render import _seniority_line

    line = _seniority_line({"jobTitle": "백엔드", "seniority": "senior",
                            "requiredRequirements": [{"text": "Kubernetes 운영"}]})
    assert "시니어" in line and "키워드 기준" in line


def test_preference_intake_conversation_loop():
    """선호 수집 대화 — 열린 질문 → 직군 인지·되묻기 → 분기점 후 이력서 자연 요청.

    LLM 미설정(conftest)이라 직군은 role_taxonomy 룰로만 잡힌다. 분기점은 결정론:
    차원 2개 이상 또는 (차원 1개 이상 AND 되묻기 2턴 소진).
    """

    from jobis_ai.agents.preference_intake import run

    session: dict = {"last_message": "이력서는 없는데 공고 추천받고 싶어"}
    r1 = run(session)
    assert "직군" in r1.reply                              # 열린 질문 — 원하는 공고부터 묻는다
    assert r1.followUpQuestions[0]["field"] == "preferences"
    session.update(r1.sessionUpdates)

    session["last_message"] = "백엔드 개발자 쪽으로 가고 싶어요"
    r2 = run(session)
    assert "백엔드" in r2.reply            # 들은 것을 받아준다
    assert r2.sessionUpdates["preferences"]["roles"] == ["백엔드"]
    session.update(r2.sessionUpdates)

    session["last_message"] = "음 잘 모르겠어요"
    r3 = run(session)                      # 되묻기 예산 소진 → 분기점 통과
    assert "관심이 있으시군요" in r3.reply
    assert "이력서" in r3.reply            # 자연스러운 이력서 요청으로 전환
    assert r3.followUpQuestions[0]["field"] == "resume"


def test_preference_intake_two_dimensions_transitions_immediately():
    """직군+도메인을 한 번에 말하면 바로 분기점 — 불필요한 되묻기가 없다."""

    from jobis_ai.agents.preference_intake import run

    result = run({
        "last_message": "백엔드요",
        "preferences": {"roles": [], "companies": [], "domains": ["커머스"], "turns": 0},
    })
    assert "관심이 있으시군요" in result.reply and "이력서" in result.reply


def test_career_chat_falls_back_honestly_without_llm():
    """진로 대화 — LLM 미설정이면 지어내지 않고 기능 안내 폴백."""

    from jobis_ai.agents.career_chat import run

    result = run({"last_message": "취업 너무 어렵다"})
    assert "도와드릴 수 있어요" in result.reply     # 결정론 폴백
    assert "적합도 분석" in result.reply




# --- 발화 소유자 하나 (compose_reply) — show_lead 4중 불리언 대체 (2026-07-29) --------
def test_compose_reply_lead_is_silent_when_an_agent_already_spoke():
    """계획 하나를 에이전트가 스스로 말했으면 계획 설명은 침묵한다(같은 말 두 번 금지)."""

    from jobis_ai.orchestrator.chat import compose_reply

    out = compose_reply([], ["진단 결과입니다."], ack="이력서 진단할게요.", steps=1)
    assert out == "진단 결과입니다."


def test_compose_reply_lead_explains_multi_step_and_silence():
    """알려 줄 순서가 있거나(둘 이상) 아무도 말하지 않았으면 계획 설명이 실린다."""

    from jobis_ai.orchestrator.chat import compose_reply

    assert compose_reply([], ["A", "B"], ack="둘 다 볼게요.", steps=2).startswith("둘 다 볼게요.")
    assert compose_reply([], [], ack="둘 다 볼게요.", steps=1) == "둘 다 볼게요."


def test_compose_reply_validator_change_speaks_the_reason_not_the_plan():
    """검증기가 계획을 바꿨으면 원안 설명(ack)이 아니라 **바뀐 이유**(note)를 말한다."""

    from jobis_ai.orchestrator.chat import compose_reply

    out = compose_reply(["이력서를 받았어요."], ["공고 정리 결과"],
                        ack="적합도 분석을 진행하겠습니다.", note="공고가 없어서 이력서 진단부터 할게요.",
                        steps=1, changed_by="validator")
    assert "적합도 분석" not in out, "하지 않은 일을 하겠다고 말하지 않는다"
    assert out.startswith("이력서를 받았어요. 공고가 없어서")


def test_compose_reply_rule_change_stays_silent_because_the_rule_explained():
    """실행 중 규칙이 바꿨으면 이유는 규칙이 이미 said 에 말했다 — 계획 설명은 침묵."""

    from jobis_ai.orchestrator.chat import compose_reply

    out = compose_reply([], ["등급이 하라서 자소서는 미뤘어요."],
                        ack="자기소개서 초안을 작성하겠습니다.", note="무시됨",
                        steps=2, changed_by="rule")
    assert out == "등급이 하라서 자소서는 미뤘어요."


# --- 동의 게이트 왕복: 물어본 것을 세션에 적고, 다음 턴에 통과시킨다 --------------------
def test_consent_gate_records_what_it_asked_and_passes_next_turn(monkeypatch, fresh_session_store):
    """게이트가 물은 이름을 `pendingConsent` 에 적고, 다음 턴 계획에 다시 들어오면 실행한다.

    전에는 이 통과 경로가 "동의하면 다음 턴 플래너가 명시적으로 고를 것"이라는 **모델에 대한
    기대**였고 동의는 어디에도 기록되지 않았다.
    """

    plan = AgentPlan(agents=["fit_analysis", "coverletter_draft"],
                     requestedAgents=["coverletter_draft"], confidence=0.9)
    monkeypatch.setattr("jobis_ai.orchestrator.chat.plan_agents",
                        lambda message, session: (plan, []))

    first = handle_chat(ChatRequest(
        sessionId="consent-1", message="자소서 써줘",
        attachments=[_resume_attachment(), _posting_attachment()]))
    assert first.dispatched == [], "청하지 않은 무거운 작업은 먼저 묻는다"
    assert "진행할까요" in first.reply
    assert fresh_session_store.get("consent-1")["pendingConsent"] == ["fit_analysis"]

    # 다음 턴 — 사용자가 "응"이라 하고 플래너가 같은 계획을 낸다(requested 는 여전히 자소서뿐).
    second = handle_chat(ChatRequest(sessionId="consent-1", message="응 진행해줘"))
    assert second.dispatched[0] == "fit_analysis", "동의했으므로 게이트를 통과한다"
    assert fresh_session_store.get("consent-1")["pendingConsent"] == [], "동의는 한 번 쓰면 소진된다"


# ---------------------------------------------------------------------------
# 확신 문턱 면제 — 이번 턴 제출물이 계획 첫 에이전트의 전제를 채우면 강등하지 않는다 (D66)
# ---------------------------------------------------------------------------
def stub_planner_unrequested(monkeypatch, agents, confidence):
    """청함 없는 낮은 확신 계획 — 말없이 자료만 붙여넣은 턴의 플래너 출력을 재현한다."""

    plan = AgentPlan(agents=list(agents), requestedAgents=[], confidence=confidence)
    monkeypatch.setattr("jobis_ai.orchestrator.chat.plan_agents",
                        lambda message, session: (plan, []))


def test_low_confidence_with_posting_submission_is_exempt(monkeypatch):
    """공고를 방금 제출한 턴 — 확신 0.55 여도 posting_analysis 가 강등되지 않는다.

    실측(2026-07-30): 말없이 공고만 붙여넣으면 합성 발화 탓에 확신이 문턱(0.6) 아래로
    나와 career_chat 으로 강등됐고, 사용자는 항목화를 기대했다.
    """

    stub_planner_unrequested(monkeypatch, ["posting_analysis"], 0.55)
    response = handle_chat(ChatRequest(sessionId="s-conf-exempt", message="",
                                       attachments=[_posting_attachment()]))
    assert "posting_analysis" in response.dispatched


def test_low_confidence_without_submission_still_falls_back(monkeypatch):
    """제출물이 없는 낮은 확신 턴은 기존대로 대화가 받는다 — 면제는 제출 턴에만."""

    from jobis_ai.orchestrator.session import get_session_store

    # 세션에 공고가 *이미* 있어도(지난 턴 제출) 이번 턴 제출이 아니면 면제가 아니다.
    get_session_store().update("s-conf-fallback", {
        "job_posting": {"sourceType": "text", "value": "백엔드 모집. 필수: Python."}})
    stub_planner_unrequested(monkeypatch, ["posting_analysis"], 0.55)
    response = handle_chat(ChatRequest(sessionId="s-conf-fallback", message="음 글쎄요"))
    assert response.dispatched == ["career_chat"]


def test_submission_grounds_plan_matrix():
    from jobis_ai.orchestrator.chat import _submission_grounds_plan

    assert _submission_grounds_plan(("posting_analysis",), ["job_posting"])
    assert _submission_grounds_plan(("resume_diagnosis",), ["resume_extra"])
    assert not _submission_grounds_plan(("career_chat",), ["job_posting"])   # 전제 무관
    assert not _submission_grounds_plan(("posting_analysis",), [])           # 제출 없음
    assert not _submission_grounds_plan((), ["job_posting"])                 # 계획 없음
