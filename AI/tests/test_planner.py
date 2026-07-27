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
    (["resume_diagnosis"], {**RESUME}, ("resume_diagnosis",)),
    (["posting_analysis"], {**POSTING}, ("posting_analysis",)),
    (["interview_prep"], {**ANALYSIS}, ("interview_prep",)),
    (["application_plan"], {**ANALYSIS}, ("application_plan",)),
    (["coverletter_draft"], {**RESUME, **POSTING, **ANALYSIS}, ("coverletter_draft",)),
    (["roadmap_manager"], {**ROADMAP}, ("roadmap_manager",)),
    # 전제 자동 삽입 — 결측 자산의 생산자를 앞에 끼운다(선언된 produces 로부터 유도)
    (["coverletter_draft"], {**RESUME, **POSTING}, ("fit_analysis", "coverletter_draft")),
    (["interview_prep"], {**RESUME, **POSTING}, ("fit_analysis", "interview_prep")),
    (["application_plan"], {**RESUME, **POSTING}, ("fit_analysis", "application_plan")),
    # 이미 선택된 생산자는 중복 삽입하지 않는다
    (["fit_analysis", "coverletter_draft"], {**RESUME, **POSTING},
     ("fit_analysis", "coverletter_draft")),
    # 두 목표가 같은 전제를 공유해도 생산자는 1회만
    (["coverletter_draft", "interview_prep"], {**RESUME, **POSTING},
     ("fit_analysis", "coverletter_draft", "interview_prep")),
    # 중복 선택은 1회로 접힌다
    (["fit_analysis", "fit_analysis"], {**RESUME, **POSTING}, ("fit_analysis",)),
    # 실행 가능한 것만 남기고, 못 할 것은 뺀다 — 무엇으로 바꿀지는 검증기가 정하지 않는다
    (["fit_analysis", "posting_analysis"], {**POSTING}, ("posting_analysis",)),
    # 남는 것이 없으면 대화형 에이전트가 턴을 받는다 (고정 문구로 끝내지 않는다)
    (["fit_analysis"], {**RESUME}, (FALLBACK_AGENT,)),
    (["fit_analysis"], {**POSTING}, (FALLBACK_AGENT,)),
    (["fit_analysis"], {}, (FALLBACK_AGENT,)),
    (["job_recommend"], {}, (FALLBACK_AGENT,)),
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
    assert validate_plan(["coverletter_draft"], {**RESUME, **POSTING}).note


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


def test_agent_plan_defaults_are_safe():
    plan = AgentPlan()
    assert plan.agents == []
    assert plan.confidence == 0.0


# --- LLM 미설정 폴백 ----------------------------------------------------------
def test_plan_agents_returns_none_without_llm():
    """LLM 미설정(conftest 강제)이면 None — handle_chat 이 대화형 에이전트로 턴을 넘긴다."""

    plan, _warnings = plan_agents("자소서 써줘", {**RESUME, **POSTING})
    assert plan is None


def test_plan_agents_empty_message_short_circuits():
    plan, warnings = plan_agents("   ", {})
    assert plan is None
    assert warnings == []
