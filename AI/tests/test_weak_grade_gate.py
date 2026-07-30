"""판정 등급에 따른 **결정적 강제 전이** (`chat.weak_grade_transition`).

원형은 Agent_Test 프로토타입의 `agent/graph.py::_route_after_tools` 다 — `analyze_gap` 직후
코드가 level 을 읽어 중/하면 대체직군 검색을 강제하고 상이면 그냥 끝낸다. LLM 재량이 아니다.
우리는 같은 성격의 규칙(등급이 낮은데 자소서·면접이 예정돼 있으면 끊는다)을 관찰(LLM)에
맡겨 뒀고 실측에서 한 번도 발동하지 않았다. 그래서 규칙으로 내렸고, 이 파일이 그 규칙을
못 박는다 — 프로토타입의 `tests/checks.py` 가 조건엣지를 LLM 없이 직접 검사한 것과 같다.

계약:
- "하"·"판정불가" 에서만 걸린다. **"중"에서는 걸리지 않는다** (갈리는 판단을 코드로 박지 않는다).
- 미완성 판정(`need_more_info`)은 손대지 않는다 — followUpQuestions 경로가 이미 멈춘다.
- 막는 대상은 판정 근거의 강도에 값이 좌우되는 생성 에이전트뿐(자소서·면접). 로드맵은 안 막는다.
- 대신 `application_plan`(목표 상태·지원 경로)을 세운다.
- **사용자를 가두지 않는다**: 등급을 보고 다음 턴에 다시 요청하면 fit_analysis 가 다시 돌지
  않으므로 규칙도 걸리지 않는다.
"""

from __future__ import annotations

from jobis_ai.agents import AgentResult
from jobis_ai.contracts.api import ChatRequest
from jobis_ai.orchestrator.chat import handle_chat
from jobis_ai.orchestrator.observe_rules import weak_grade_transition
from jobis_ai.orchestrator.planner import AgentPlan

_RESUME = {"sourceType": "text", "value": "Python Django 백엔드 개발 3년"}
_POSTING = {"sourceType": "text", "value": "백엔드 개발자 채용. 자격요건: Rust, Kubernetes 7년 이상"}


def _analysis(grade: str, status: str = "completed") -> dict:
    return {"status": status, "fitGrade": grade, "overallScore": 0.21,
            "summary": "필수 요건 다수가 확인되지 않았습니다."}


def _session(**extra) -> dict:
    session = {"resume": _RESUME, "job_posting": _POSTING, "analysis": _analysis("하")}
    session.update(extra)
    return session


def _stub_planner(monkeypatch, agents, ack: str = ""):
    plan = AgentPlan(agents=list(agents), requestedAgents=list(agents),
                     confidence=0.9, ack=ack)
    monkeypatch.setattr("jobis_ai.orchestrator.chat.plan_agents",
                        lambda message, session: (plan, []))


def _stub_fit(monkeypatch, grade: str, status: str = "completed"):
    """fit_analysis 를 원하는 등급으로 고정한다. 판정 파이프라인은 이 테스트의 대상이 아니다."""

    data = _analysis(grade, status)

    def run(session):
        updates = {"analysis": data} if status == "completed" else {}
        return AgentResult(reply="", data=data, sessionUpdates=updates)

    monkeypatch.setattr("jobis_ai.agents.fit_analysis.run", run)


def _stub_agent(monkeypatch, module: str, marker: list[str]):
    def run(session):
        marker.append(module)
        return AgentResult(reply=f"{module} 결과")

    monkeypatch.setattr(f"jobis_ai.agents.{module}.run", run)


# --- 규칙 자체 (순수 함수, LLM 0원) ------------------------------------------------
def test_high_grade_does_not_intervene():
    """상 — 예정대로 둔다. 프로토타입의 "상 → 검색 안 함"에 대응한다."""

    queue, note = weak_grade_transition(
        _analysis("상"), ["coverletter_draft"], [], _session())
    assert (queue, note) == (["coverletter_draft"], "")


def test_middle_grade_does_not_intervene():
    """중 — **걸리지 않는다.** 0.4~0.7 은 사람마다 갈리는 구간이고, 갈리는 판단은 코드로 박지 않는다."""

    queue, note = weak_grade_transition(
        _analysis("중"), ["coverletter_draft"], [], _session())
    assert (queue, note) == (["coverletter_draft"], "")


def test_low_grade_replaces_generation_with_application_plan():
    """하 — 자소서를 빼고 지원 경로 설계를 앞에 넣는다."""

    queue, note = weak_grade_transition(
        _analysis("하"), ["coverletter_draft"], [], _session())
    assert queue == ["application_plan"]
    assert "하" in note and "미뤘" in note


def test_undecidable_grade_also_replaces():
    """판정불가 — 계산된 근거가 하나도 없으므로 생성의 근거로 쓸 수 없다."""

    queue, note = weak_grade_transition(
        _analysis("판정불가"), ["interview_prep"], [], _session())
    assert queue == ["application_plan"]
    assert note


def test_need_more_info_is_left_alone():
    """미완성 판정은 손대지 않는다 — followUpQuestions 경로가 이미 뒤 단계를 멈춘다."""

    queue, note = weak_grade_transition(
        _analysis("하", status="need_more_info"), ["coverletter_draft"], [], _session())
    assert (queue, note) == (["coverletter_draft"], "")


def test_roadmap_is_not_blocked():
    """로드맵은 막지 않는다 — 등급이 낮을 때야말로 필요한 것이다. 막을 것이 없으면 규칙도 안 건다."""

    queue, note = weak_grade_transition(
        _analysis("하"), ["roadmap_manager"], [], _session())
    assert (queue, note) == (["roadmap_manager"], "")


def test_other_planned_steps_keep_their_order():
    """막는 것만 빼고 나머지 예정은 순서를 지킨다."""

    queue, _ = weak_grade_transition(
        _analysis("하"), ["coverletter_draft", "roadmap_manager"], [], _session())
    assert queue == ["application_plan", "roadmap_manager"]


def test_fallback_not_inserted_twice_when_already_run():
    """지원 경로 설계가 이미 돌았으면 다시 넣지 않는다 — 빼기는 하고, 그 사실은 말한다."""

    queue, note = weak_grade_transition(
        _analysis("하"), ["coverletter_draft"], ["application_plan"], _session())
    assert queue == []
    assert "진행하지 않았" in note


def test_fallback_not_inserted_when_not_runnable():
    """전제(analysis)가 없으면 대체도 끼우지 않는다 — 빈 근거 위에서 돌리지 않는다."""

    session = {"resume": _RESUME, "job_posting": _POSTING}   # analysis 없음
    queue, note = weak_grade_transition(_analysis("하"), ["coverletter_draft"], [], session)
    assert queue == []
    assert note


# --- 실행 루프에 실제로 걸리는가 ---------------------------------------------------
def test_low_grade_turn_with_assets(monkeypatch):
    """플래너가 [판정 → 자소서]를 계획해도, 등급이 하면 자소서는 돌지 않는다.

    dispatched 가 [판정 → 지원 경로]로 바뀐다.
    """

    from jobis_ai.orchestrator.session import get_session_store

    get_session_store().update("weak-2", {"resume": _RESUME, "job_posting": _POSTING})

    ran: list[str] = []
    _stub_planner(monkeypatch, ["fit_analysis", "coverletter_draft"])
    _stub_fit(monkeypatch, "하")
    _stub_agent(monkeypatch, "coverletter_draft", ran)
    _stub_agent(monkeypatch, "application_plan", ran)

    res = handle_chat(ChatRequest(sessionId="weak-2", message="분석하고 자소서 써줘",
                                  attachments=[]))

    assert res.dispatched == ["fit_analysis", "application_plan"]
    assert ran == ["application_plan"]               # 자소서는 돌지 않았다
    assert "coverletter_draft" not in res.results
    assert "미뤘" in res.reply                        # 왜 바뀌었는지 사용자에게 말한다


def test_lead_is_dropped_when_rule_fires(monkeypatch):
    """규칙이 걸리면 계획 설명(플래너 ack)을 싣지 않는다.

    ack 는 *원래 계획*을 설명하는 문장이다. 실측(2026-07-29)에서 등급 하로 자소서를 미뤘는데
    답변 첫 문장이 "자기소개서 초안을 작성하겠습니다"로 나갔다 — 하지 않은 일을 하겠다고
    말한 것이다. `plan_changed` 는 dispatch 시점만 보므로 실행 중 전이를 잡지 못한다.
    """

    from jobis_ai.orchestrator.session import get_session_store

    get_session_store().update("weak-5", {"resume": _RESUME, "job_posting": _POSTING})

    _stub_planner(monkeypatch, ["fit_analysis", "coverletter_draft"],
                  ack="적합도를 분석하고 자기소개서 초안을 작성하겠습니다.")
    _stub_fit(monkeypatch, "하")
    _stub_agent(monkeypatch, "coverletter_draft", [])
    _stub_agent(monkeypatch, "application_plan", [])

    res = handle_chat(ChatRequest(sessionId="weak-5", message="분석하고 자소서 써줘",
                                  attachments=[]))

    assert "자기소개서 초안을 작성하겠습니다" not in res.reply
    assert "미뤘" in res.reply


def test_note_does_not_attach_particles_to_agent_labels(monkeypatch):
    """라벨에 조사를 붙이지 않는다 — 받침에 따라 갈려서 조용히 틀린다(실측: "설계**으로**")."""

    _, note = weak_grade_transition(
        _analysis("하"), ["coverletter_draft"], [], _session())
    assert "설계으로" not in note and "설계로" not in note


def test_high_grade_turn_still_writes_coverletter(monkeypatch):
    """상이면 규칙이 걸리지 않는다 — 계획대로 자소서를 쓴다(규칙이 기능을 막지 않는다는 증거)."""

    from jobis_ai.orchestrator.session import get_session_store

    get_session_store().update("weak-3", {"resume": _RESUME, "job_posting": _POSTING})

    ran: list[str] = []
    _stub_planner(monkeypatch, ["fit_analysis", "coverletter_draft"])
    _stub_fit(monkeypatch, "상")
    _stub_agent(monkeypatch, "coverletter_draft", ran)
    _stub_agent(monkeypatch, "application_plan", ran)

    res = handle_chat(ChatRequest(sessionId="weak-3", message="분석하고 자소서 써줘",
                                  attachments=[]))

    assert res.dispatched == ["fit_analysis", "coverletter_draft"]
    assert ran == ["coverletter_draft"]


def test_user_can_proceed_anyway_next_turn(monkeypatch):
    """**규칙이 사용자를 가두지 않는다.**

    등급을 본 뒤 다음 턴에 다시 요청하면 fit_analysis 가 다시 돌지 않으므로(세션에 analysis 가
    이미 있다) 규칙도 걸리지 않고 자소서가 실행된다. 우리가 막는 것은 *말없이 빈 근거 위에서
    도는 것*이지, 사용자가 판정을 알고 내리는 결정이 아니다.
    """

    from jobis_ai.orchestrator.session import get_session_store

    get_session_store().update("weak-4", {
        "resume": _RESUME, "job_posting": _POSTING, "analysis": _analysis("하"),
    })

    ran: list[str] = []
    _stub_planner(monkeypatch, ["coverletter_draft"])      # 사용자가 그래도 써 달라고 했다
    _stub_agent(monkeypatch, "coverletter_draft", ran)

    res = handle_chat(ChatRequest(sessionId="weak-4", message="알아, 그래도 자소서 써줘",
                                  attachments=[]))

    assert res.dispatched == ["coverletter_draft"]
    assert ran == ["coverletter_draft"]


# --- 강제 전이의 착지점이 실제로 값을 주는가 ----------------------------------------
def test_application_plan_reply_carries_routes():
    """`application_plan` 답변이 **지원 경로를 실제로 싣는다.**

    전에는 `label — headline` 한 줄이라 이 에이전트의 산출물(경로 2~3개)이 대화 채널에
    도달하지 않았다. 등급이 낮을 때 여기로 강제 전이하기로 한 뒤에는 그게 곧 규칙의 값이
    되므로, 아무것도 말하지 않는 착지점은 규칙을 손해로 만든다.
    """

    from jobis_ai.agents.application_plan import render_plan_reply

    reply = render_plan_reply(
        {"label": "중기 목표", "headline": "지금은 준비 난도가 높아요.",
         "reasons": ["필수 요건 4건 미충족"], "recheckCondition": "Rust 프로젝트 1건 완료 후"},
        [{"id": "as_is", "effort": "low", "hardRisk": True, "title": "지금 그대로 지원",
          "summary": "합격 가능성은 낮지만 경험은 남는다"},
         {"id": "reinforce", "effort": "mid", "hardRisk": False, "title": "보강 후 지원",
          "summary": "Rust 프로젝트 1건을 만들고 지원"}],
    )

    assert "지원 경로:" in reply
    assert "지금 그대로 지원" in reply and "보강 후 지원" in reply
    assert "부담 낮음" in reply and "부담 중간" in reply
    assert "필수 조건 충돌" in reply          # 대체 불가 조건은 감추지 않는다
    assert "다시 판정해 볼 시점" in reply


def test_application_plan_reply_drops_tautological_headline():
    """headline 이 label 을 되풀이하면 싣지 않는다 (실측: "중기 목표 — 이 목표는 중기 목표로…")."""

    from jobis_ai.agents.application_plan import render_plan_reply

    reply = render_plan_reply(
        {"label": "중기 목표", "headline": "이 목표는 중기 목표로 설정되었습니다."}, [])

    assert reply == "**중기 목표**"


# --- 등급 경계의 단일 출처 (D16) ------------------------------------------------
def test_application_plan_status_follows_the_grade_boundaries():
    """목표 상태 판정은 `gap_matcher` 의 등급 경계를 **그대로** 쓴다.

    전에는 70/40 을 리터럴로 다시 적고 주석으로만 묶어 뒀다 — 한쪽만 고쳐도 아무도 못 잡는
    형태였다. 이 테스트는 경계를 gap_matcher 에서 읽어 비교하므로 값이 갈라지면 깨진다.
    """

    from jobis_ai.agents.application_plan import _decide_status
    from jobis_ai.gap_matcher import GRADE_HIGH, GRADE_MID

    def status(score: float, unmet: list[str] = []) -> str:
        return _decide_status({"status": "completed", "overallScore": score}, unmet, [])

    assert status(GRADE_HIGH) == "APPLY_NOW"
    assert status(GRADE_HIGH, ["Kafka"]) == "APPLY_WITH_POLISH"
    assert status(round(GRADE_HIGH - 0.01, 2)) == "REINFORCE_FIRST"
    assert status(GRADE_MID) == "REINFORCE_FIRST"
    assert status(round(GRADE_MID - 0.01, 2)) == "MID_TERM_TARGET"


def test_application_plan_hard_constraint_beats_score():
    """구조적 제약(연차·학위)이 있으면 점수가 아무리 높아도 중기 목표다."""

    from jobis_ai.agents.application_plan import _decide_status

    assert _decide_status({"status": "completed", "overallScore": 0.95}, [],
                          [{"requirement": "경력 5년 이상"}]) == "MID_TERM_TARGET"
