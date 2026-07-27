"""에이전트 플래너 — LLM 이 발화와 사용자 상태를 보고 호출할 에이전트를 직접 고른다.

의도 라벨·대응표를 거치지 않는다. 레지스트리의 capability manifest(설명·필요 자산)와
**지금 실행 가능한지**, 세션 자산 상태, 최근 대화를 함께 주고 판단을 맡긴다
(llm-planner-design.md).

하네스는 유지된다:
- 선택지는 스키마(Literal)로 제한 — 미등록 에이전트 호출(환각)은 구조적으로 불가능.
- 출력에 판단 필드가 없다 — 적합도·조언을 즉석에서 답할 수 없다.
- 실행 가능 여부(전제 삽입·불가 제거)는 router.validate_plan(순수 코드)이 확정한다.
- LLM 미설정·실패면 None — 호출부(chat)가 대화형 에이전트에게 턴을 넘긴다.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from jobis_ai.structured import run_structured

AgentName = Literal[
    "fit_analysis",
    "application_plan",
    "posting_analysis",
    "job_recommend",
    "preference_intake",
    "career_chat",
    "resume_diagnosis",
    "interview_prep",
    "coverletter_draft",
    "roadmap_manager",
]

# 이 값보다 낮으면 에이전트를 실행하지 않고 대화형 에이전트가 턴을 받는다
# (되묻기 고정 문구가 아니라, 사용자의 말에 답하면서 필요한 것을 묻는다).
CONFIDENCE_THRESHOLD = 0.6


class AgentPlan(BaseModel):
    """플래너 출력 — 에이전트 선택·참조·이해 확인 문장뿐, 판단 필드는 없다.

    **필드 description 은 필수다.** 없으면 모델이 값의 뜻을 추측해 채운다(실측: confidence 를
    0.0 으로 채워 자기가 고른 계획이 임계값에서 잘려 나갔다). 스키마가 곧 지시문이다.
    """

    agents: list[AgentName] = Field(default_factory=list, description=(
        "이번 턴에 실행할 에이전트 이름, 실행 순서대로. 목표만 고르면 된다 — 전제 자산을 만드는 "
        "선행 에이전트는 시스템이 알아서 앞에 끼운다. 이 발화에 맞는 에이전트가 없으면 빈 배열."))
    target: str = Field(default="", description=(
        "발화가 가리키는 공고·대상 참조(URL, \"지난번 그 공고\" 등). 없으면 빈 문자열. 추측 금지."))
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description=(
        "**agents 선택에 대한 확신도**(0~1). 발화가 명확해서 이 에이전트가 맞다고 판단했으면 "
        "0.8 이상을 준다. 0.6 미만이면 시스템은 실행하지 않고 대화로 받는다 — 즉 무엇을 원하는지 "
        "정말 모를 때만 낮게 준다. 적합도·합격 가능성에 대한 확신이 아니다."))
    ack: str = Field(default="", description=(
        "요청을 어떻게 이해했고 무엇을 하려는지 사용자에게 보여줄 자연스러운 한 문장. "
        "적합도·합격 가능성 등 판단·예측·조언은 절대 넣지 않는다(금지표현 검증에서 버려진다)."))


_PLANNER_SYSTEM_TEMPLATE = """너는 취업 지원 서비스의 오케스트레이터 플래너다.
사용자 발화와 지금 상태를 함께 보고, 이번 턴에 실행할 에이전트를 실행 순서대로 agents 에 담는다.

에이전트 목록 (지금 실행 가능 여부 포함):
{manifest}

판단 원칙:
- **지금 실행 가능한 에이전트만 고른다.** "실행 불가"로 표시된 것은 고르지 않는다.
- 사용자가 원하는 것을 바로 못 한다면, **지금 가진 자산으로 사용자에게 도움이 되는 일을 먼저
  하는 에이전트**를 고른다. 부족한 자료는 그 에이전트가 결과를 들고 대화로 직접 요청한다.
- 적합도·합격 가능성·조언·추천을 스스로 판단하거나 답하지 않는다 — 그것은 에이전트의 일이다.
- 발화가 짧거나 지시어("그거 해줘", "응", "이어서")면 [최근 대화] 맥락으로 해석한다.
  직전 턴에서 시스템이 물은 것에 대한 답이면 그 흐름을 잇는 에이전트를 고른다.
- 어느 에이전트도 이 발화에 맞지 않으면 agents 를 비우고 confidence 를 낮게 준다 —
  시스템이 대화로 받는다.
- confidence 는 선택 확신도(0~1). 애매하면 낮게 준다.
- target 에는 발화가 가리키는 공고/대상 참조가 있으면 그대로 옮겨 적는다(추측 금지).
- ack 에는 요청을 어떻게 이해했고 무엇을 하려는지 자연스러운 한 문장을 쓴다.
  적합도·합격 가능성 등 판단·예측·조언은 절대 넣지 않는다."""


def _build_manifest(session: dict[str, Any]) -> str:
    """레지스트리 + 지금 실행 가능 여부로 플래너용 목록을 만든다.

    실행 가능 여부를 프롬프트에 실으므로, "이 상황이면 저 에이전트" 같은 대체 규칙을 코드에
    둘 필요가 없다 — 플래너가 상태를 알고 고른다. 에이전트 추가 시 이 함수는 그대로다.
    """

    from jobis_ai.agents import get_agent_registry
    from jobis_ai.orchestrator.router import agent_feasibility, asset_label

    feasibility = agent_feasibility(session)
    lines = []
    for spec in get_agent_registry().values():
        missing = feasibility.get(spec.name)
        state = "실행 가능" if missing is None else f"실행 불가 — {asset_label(missing)} 없음"
        lines.append(f"- {spec.name}: {spec.description} [{state}]")
    return "\n".join(lines)


_ASSET_LABEL = {
    "resume": "이력서",
    "job_posting": "공고",
    "analysis": "적합도 분석 결과",
    "roadmap": "준비 로드맵",
}


def _asset_state(session: dict[str, Any]) -> str:
    """사용자 상태 — 세션 자산의 있고 없음을 문장으로. 플래너의 맥락 입력."""

    parts = []
    has_resume = bool(session.get("resume") or session.get("profile"))
    parts.append(f"이력서: {'있음' if has_resume else '없음'}")
    for key in ("job_posting", "analysis", "roadmap"):
        parts.append(f"{_ASSET_LABEL[key]}: {'있음' if session.get(key) else '없음'}")
    from jobis_ai.orchestrator.router import agent_feasibility

    prefs = session.get("preferences") or {}
    known = [v for k in ("roles", "domains", "companies", "regions", "techStack")
             for v in (prefs.get(k) or [])]
    if known:
        parts.append(f"수집된 공고 선호: {', '.join(known[:5])} (선호 수집 대화 진행 중)")
    else:
        parts.append("수집된 공고 선호: 없음")

    # 실행 가능한 이름을 **다시 한 번 나열**한다 — 목록 안의 [실행 불가] 표시만으로는
    # 모델이 못 할 일을 고르는 사례가 실측됐다(그때는 검증기가 막고 대화로 돌아간다).
    feasible = [name for name, missing in agent_feasibility(session).items() if missing is None]
    return " / ".join(parts) + f"\n지금 실행 가능한 에이전트: {', '.join(feasible)}"


def _history_block(session: dict[str, Any]) -> str:
    """최근 대화를 플래너 프롬프트용 텍스트로 — 지시어·후속 답변 해석의 근거."""

    from jobis_ai.orchestrator.session import recent_history

    items = recent_history(session)
    if not items:
        return "(첫 대화)"
    role_ko = {"user": "사용자", "assistant": "시스템"}
    return "\n".join(f"{role_ko.get(h['role'], h['role'])}: {h['content']}" for h in items)


def safe_ack(plan: AgentPlan | None) -> str:
    """플래너의 이해 확인 문장 — 금지표현이 섞이면 버린다(호출부가 결정론 문구로 폴백).

    표현 계층도 검증을 면제받지 않는다 (nl_render 와 동일 원칙).
    """

    if plan is None:
        return ""
    text = (plan.ack or "").strip()
    if not text:
        return ""
    from jobis_ai.verify_rules import FORBIDDEN_EXPRESSIONS

    if any(expr in text for expr in FORBIDDEN_EXPRESSIONS):
        return ""
    return text


def plan_agents(message: str, session: dict[str, Any]) -> tuple[AgentPlan | None, list[dict]]:
    """발화 + 자산 상태 → AgentPlan. LLM 실패·미설정이면 (None, warnings) — 폴백은 호출부가."""

    if not (message or "").strip():
        return None, []

    system = _PLANNER_SYSTEM_TEMPLATE.format(manifest=_build_manifest(session))
    user_content = (
        f"[최근 대화]\n{_history_block(session)}\n\n"
        f"[세션 자산 상태]\n{_asset_state(session)}\n\n[사용자 발화]\n{message}"
    )
    # 에이전트 선택은 고급 모델 유지 — 경량(gpt-5-nano) 실측에서 정확도 100%→48.8%로
    # 붕괴(과잉 선택·오되묻기). 스키마 제한·검증기로도 못 막는 판단 품질 차이다 (0724 실측).
    return run_structured(AgentPlan, system, user_content, node="agent_planner")
