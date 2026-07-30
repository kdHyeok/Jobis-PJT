"""플래너 계층 테스트 — 검증기 전수 + 실행 가능 판정 + 스키마 제한 + LLM 미설정 폴백.

무엇을 할지(추론)는 플래너 LLM 이 정하고, 여기서 검증하는 것은 **하네스**다:
- validate_plan — 전제 자산 확인·생산자 삽입·실행 불가 제거 (순수 결정론, 전수 검증).
- agent_feasibility — 지금 상태에서 무엇이 실행 가능한지(플래너의 그라운딩 입력).
- AgentPlan — 행동 집합 제한(등록된 에이전트 이름만).
플래너 LLM 은 conftest 가 강제 미설정하므로 plan_agents 는 None 을 반환하고,
handle_chat 은 대화형 에이전트에게 턴을 넘긴다.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jobis_ai.orchestrator.planner import AgentPlan, plan_agents
from jobis_ai.orchestrator.router import FALLBACK_AGENT, agent_feasibility, validate_plan

RESUME = {"resume": {"sourceType": "text", "value": "이력서"}}
POSTING = {"job_posting": {"sourceType": "text", "value": "공고"}}
ANALYSIS = {"analysis": {"fitGrade": "중", "gaps": [{"requirementId": "r1"}]}}
ROADMAP = {"roadmap": {"roadmap": []}}


# --- 검증기 전수 — 실행 가능성만 판정한다(대체 규칙 없음) ---------------------
@pytest.mark.parametrize("selected,assets,expected_agents", [
    # 전제 충족 — 고른 대로 실행
    (["fit_analysis"], {**RESUME, **POSTING}, ("fit_analysis",)),
    (["job_recommend"], {**RESUME}, ("job_recommend",)),
    # 공고 추천의 전제는 "이력서 또는 선호" — 선호만 있어도 바로 추천한다
    (["job_recommend"], {"preferences": {"roles": ["백엔드"]}}, ("job_recommend",)),
    # 둘 다 없으면 선호를 만드는 생산자를 앞에 끼운다 (대화로 안 넘기고 목표를 살린다)
    (["job_recommend"], {}, ("preference_intake", "job_recommend")),
    (["resume_diagnosis"], {**RESUME}, ("resume_diagnosis",)),
    (["posting_analysis"], {**POSTING}, ("posting_analysis",)),
    (["interview_prep"], {**ANALYSIS}, ("interview_prep",)),
    (["application_plan"], {**ANALYSIS}, ("application_plan",)),
    (["coverletter_draft"], {**RESUME, **POSTING, **ANALYSIS}, ("coverletter_draft",)),
    (["roadmap_manager"], {**ROADMAP}, ("roadmap_manager",)),
    # 무거운 생산자(fit_analysis)의 자동 삽입은 실행하지 않고 **동의 게이트**로 묻는다 —
    # 아래 test_validate_plan_heavy_producer_asks_consent 에서 검증.
    # 명시 선택된 생산자는 게이트 없이 그대로 실행하고, 중복 삽입하지 않는다
    (["fit_analysis", "coverletter_draft"], {**RESUME, **POSTING},
     ("fit_analysis", "coverletter_draft")),
    # 중복 선택은 1회로 접힌다
    (["fit_analysis", "fit_analysis"], {**RESUME, **POSTING}, ("fit_analysis",)),
    # 실행 가능한 것만 남기고, 못 할 것은 뺀다 — 무엇으로 바꿀지는 검증기가 정하지 않는다
    (["fit_analysis", "posting_analysis"], {**POSTING}, ("posting_analysis",)),
    # 남는 것이 없으면 대화형 에이전트가 턴을 받는다 (고정 문구로 끝내지 않는다)
    (["fit_analysis"], {**RESUME}, (FALLBACK_AGENT,)),
    (["fit_analysis"], {**POSTING}, (FALLBACK_AGENT,)),
    (["fit_analysis"], {}, (FALLBACK_AGENT,)),
    (["coverletter_draft"], {**RESUME}, (FALLBACK_AGENT,)),
    (["roadmap_manager"], {}, (FALLBACK_AGENT,)),   # 로드맵은 조회 전용(생산자 삽입 안 함)
    # 빈 선택 — 무엇을 원하는지 못 읽었어도 대화로 받는다
    ([], {**RESUME, **POSTING}, (FALLBACK_AGENT,)),
])
def test_validate_plan_table(selected, assets, expected_agents):
    assert validate_plan(selected, assets).agents == expected_agents


def test_validate_plan_note_only_when_sequence_changed():
    """가시화 문구는 계획이 달라졌을 때만 — 매 턴 '이해했어요'가 붙으면 기계적으로 읽힌다."""

    assert validate_plan(["fit_analysis"], {**RESUME, **POSTING}).note == ""
    # 자산 결측으로 강등된 실행(공고 정리만 남음)에는 바뀐 이유를 말한다
    assert validate_plan(["fit_analysis", "posting_analysis"], {**POSTING}).note


def test_validate_plan_heavy_producer_asks_consent():
    """무거운 생산자(fit_analysis)가 **자동 삽입**될 때는 말없이 시작하지 않고 먼저 묻는다.

    "자소서 써줘" → 수십 초짜리 판정 파이프라인이 note 한 줄로 시작되던 것을,
    실행 전 동의 게이트(ask)로 바꾼다. 명시 선택이면 게이트 없이 그대로 실행.
    """

    for goal in ("coverletter_draft", "interview_prep", "application_plan"):
        d = validate_plan([goal], {**RESUME, **POSTING})
        assert d.agents == () and d.ask            # 실행하지 않고 묻는다
    # 사용자가(플래너가) fit_analysis 를 명시하면 게이트 없이 실행
    d = validate_plan(["fit_analysis", "coverletter_draft"], {**RESUME, **POSTING})
    assert d.agents == ("fit_analysis", "coverletter_draft") and d.ask == ""


def test_validate_plan_drops_unknown_agent():
    """레지스트리 미등록 이름은 실행하지 않는다 — 스키마가 막지만 검증기도 방어한다."""

    assert validate_plan(["nonexistent_agent"], {**RESUME, **POSTING}).agents == (FALLBACK_AGENT,)


def test_validate_plan_profile_counts_as_resume():
    """profile 자산도 resume 전제로 인정 — 이력서를 이미 파싱해 둔 세션."""

    assert validate_plan(["job_recommend"], {"profile": {"skills": []}}).agents == ("job_recommend",)


def test_validate_plan_partial_insertion_does_not_leak():
    """전제가 둘인데 하나를 못 채우면 **아무것도** 남지 않는다(반쯤 낀 계획 금지)."""

    dispatch = validate_plan(["coverletter_draft"], {**RESUME})
    assert "fit_analysis" not in dispatch.agents


# --- 실행 가능 판정 — 플래너의 그라운딩 입력 ----------------------------------
def test_agent_feasibility_reports_missing_asset():
    """공고만 있는 상태: 공고 분석은 가능, 적합도 분석은 이력서가 없어 불가."""

    feasible = agent_feasibility({**POSTING})
    assert feasible["posting_analysis"] is None
    assert feasible["fit_analysis"] == "resume"
    # 자료가 없어도 대화로 받는 에이전트는 항상 가능해야 한다
    assert feasible["career_chat"] is None and feasible["preference_intake"] is None


def test_agent_feasibility_counts_producer_chain():
    """생산자로 채울 수 있는 전제는 실행 가능으로 센다 — 이력서+공고면 자소서·로드맵까지.

    fit_analysis 가 analysis 와 roadmap 을 함께 만들기 때문이다(선언된 produces).
    """

    feasible = agent_feasibility({**RESUME, **POSTING})
    assert feasible["coverletter_draft"] is None
    assert feasible["roadmap_manager"] is None

    # 자산이 없으면 생산자 체인도 시작할 수 없다. 결측으로 보고되는 것은 **체인의 뿌리**다
    # (로드맵이 없다가 아니라, 로드맵을 만들려면 필요한 이력서가 없다 — 플래너가 읽을 이유).
    empty = agent_feasibility({})
    assert empty["roadmap_manager"] == "resume" and empty["fit_analysis"] == "resume"


# --- 플래너 출력 스키마 — 환각 에이전트는 구조적으로 불가능 --------------------
def test_agent_plan_schema_rejects_unknown_name():
    with pytest.raises(ValidationError):
        AgentPlan(agents=["submit_application"])


def test_agent_plan_requires_confidence():
    """confidence 는 필수다 — default=0.0 이던 시절 모델이 칸을 빼먹으면 조용히 0.0 이 되어
    정확히 고른 계획이 임계값에서 잘려 나갔다(2026-07-29 실측: 자료 제출 턴 3/5 붕괴).
    누락은 검증 오류 → run_structured 재시도로 처리한다."""

    with pytest.raises(ValidationError):
        AgentPlan()


def test_agent_plan_defaults_are_safe():
    plan = AgentPlan(confidence=0.5)
    assert plan.agents == []
    assert plan.requestedAgents == []
    assert plan.target == "" and plan.ack == ""


# --- LLM 미설정 폴백 ----------------------------------------------------------
def test_plan_agents_returns_none_without_llm():
    """LLM 미설정(conftest 강제)이면 None — handle_chat 이 대화형 에이전트로 턴을 넘긴다."""

    plan, _warnings = plan_agents("자소서 써줘", {**RESUME, **POSTING})
    assert plan is None


def test_plan_agents_empty_message_short_circuits():
    plan, warnings = plan_agents("   ", {})
    assert plan is None
    assert warnings == []


# --- 동의 게이트: 통과 조건은 "청했다" 또는 "직전 턴 동의"뿐 (2026-07-29 재설계) --------
def test_gate_fires_for_a_heavy_step_the_user_did_not_ask_for():
    """**사용자가 청하지 않은 무거운 작업은 막는다.** 플래너가 스스로 골랐어도 마찬가지다.

    실측(consistency S5·planner `coverletter-motivation`): 플래너가 `[fit_analysis,
    coverletter_draft]` 를 골라 **수십 초 파이프라인이 말없이 돌았다.**
    """

    dispatch = validate_plan(
        ["fit_analysis", "coverletter_draft"], {**RESUME, **POSTING},
        requested=["coverletter_draft"],        # 사용자는 자소서만 청했다
    )
    assert dispatch.agents == (), "실행하지 않는다"
    assert "진행할까요" in dispatch.ask
    assert "자소서 초안" in dispatch.ask, "사용자의 목표를 문구에 담는다"
    assert dispatch.pending == ("fit_analysis",), "무엇을 물었는지 세션에 적을 수 있게 낸다"


def test_gate_is_fail_closed_when_the_planner_says_nothing():
    """**모르면 묻는다.** 전에는 반대였다 — 플래너가 "내가 끼웠다"고 자기신고하지 않으면
    게이트가 통과였고(fail-open), 모델이 그 칸을 비우면 수십 초 파이프라인이 말없이 돌았다.
    같은 LLM 정보를 쓰면서 실패 방향만 뒤집었다(AGENTS §2-2)."""

    dispatch = validate_plan(["fit_analysis", "coverletter_draft"], {**RESUME, **POSTING},
                             requested=[])
    assert dispatch.agents == () and dispatch.ask


def test_gate_stays_silent_when_the_user_asked_for_the_heavy_step():
    """사용자가 판정을 직접 청했으면 묻지 않고 실행한다."""

    dispatch = validate_plan(
        ["fit_analysis", "interview_prep"], {**RESUME, **POSTING},
        requested=["fit_analysis", "interview_prep"],
    )
    assert dispatch.agents == ("fit_analysis", "interview_prep")
    assert dispatch.ask == ""


def test_gate_passes_after_the_user_consented_last_turn():
    """직전 턴에 게이트가 물었고(`pendingConsent`) 사용자 발화를 거쳐 같은 이름이 다시
    계획에 들어왔다 = 동의다. 전에는 이 통과 경로도 "플래너가 다음 턴에 명시적으로 고를
    것"이라는 **모델에 대한 기대**였고, 동의는 어디에도 기록되지 않았다."""

    session = {**RESUME, **POSTING, "pendingConsent": ["fit_analysis"]}
    dispatch = validate_plan(["fit_analysis", "coverletter_draft"], session, requested=[])
    assert dispatch.agents == ("fit_analysis", "coverletter_draft")
    assert dispatch.ask == ""


def test_a_light_prerequisite_does_not_trigger_the_gate():
    """게이트는 **무거운** 것에만 걸린다 — 가벼운 전제는 말없이 끼워도 된다."""

    dispatch = validate_plan(
        ["preference_intake", "job_recommend"], {}, requested=["job_recommend"],
    )
    assert dispatch.ask == ""
    assert "job_recommend" in dispatch.agents


def test_requested_names_outside_the_plan_are_harmless():
    """`requested` 에 계획 밖 이름이 섞여도 판정이 흔들리지 않는다(환각 방어)."""

    dispatch = validate_plan(["fit_analysis"], {**RESUME, **POSTING},
                             requested=["fit_analysis", "roadmap_manager"])
    assert dispatch.agents == ("fit_analysis",) and dispatch.ask == ""


def test_unrequested_prerequisite_for_an_existing_asset_is_dropped_not_asked():
    """이미 있는 자산을 만드는 전제는 **묻지 않고 뺀다.**

    게이트는 "필요한데 무거운 것"에만 의미가 있다. 실측(2026-07-29): analysis 를 이미 가진
    세션에서 "자소서 다시 써줘" 에 플래너가 fit_analysis 를 넣어 게이트가 걸리고,
    **이미 있는 분석을 다시 하겠냐고 묻는** 답이 나갔다.
    """

    session = {**RESUME, **POSTING, "analysis": {"fitGrade": "중", "gaps": []}}
    dispatch = validate_plan(["fit_analysis", "coverletter_draft"], session,
                             requested=["coverletter_draft"])
    assert dispatch.ask == "", "이미 있는 분석을 다시 하겠냐고 묻지 않는다"
    assert dispatch.agents == ("coverletter_draft",)


def test_user_requested_reanalysis_is_not_dropped():
    """사용자가 직접 재분석을 청했으면 이미 analysis 가 있어도 빼지 않는다."""

    session = {**RESUME, **POSTING, "analysis": {"fitGrade": "중", "gaps": []}}
    dispatch = validate_plan(["fit_analysis", "coverletter_draft"], session,
                             requested=["fit_analysis", "coverletter_draft"])
    assert dispatch.agents == ("fit_analysis", "coverletter_draft")


def test_unknown_requested_keeps_the_plan_when_the_planner_says_nothing():
    """모름(빈 `requested`)이면 **드롭은 하지 않는다** — 게이트와 반대 방향으로 기운다.
    게이트가 틀리면 "묻지 않고 비싼 일을 함", 드롭이 틀리면 "청한 일을 안 함"이다."""

    session = {**RESUME, **POSTING, "analysis": {"fitGrade": "중", "gaps": []},
               "pendingConsent": ["fit_analysis"]}
    dispatch = validate_plan(["fit_analysis", "coverletter_draft"], session, requested=[])
    assert dispatch.agents == ("fit_analysis", "coverletter_draft")
