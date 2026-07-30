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


class AgentArg(BaseModel):
    """에이전트 하나에 넘길 인자 한 개.

    에이전트별로 다른 인자 스키마를 만들면 구조화 출력이 동적 스키마가 되어(공급자별로
    지원이 갈린다) 하네스가 약해진다. 그래서 **평평한 목록**으로 받고, 이름 검증은
    검증기(router)가 레지스트리 선언과 대조해 결정론으로 한다.
    """

    agent: AgentName = Field(description="인자를 받을 에이전트 이름.")
    name: str = Field(description="인자 이름. 에이전트 목록에 적힌 이름만.")
    value: str = Field(description="발화에서 읽어낸 값. 추측·확장 금지.")


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
    agentArgs: list["AgentArg"] = Field(default_factory=list, description=(
        "에이전트에 넘길 인자. 에이전트 목록에 '인자'가 적힌 것만, 발화에 값이 **실제로 있을 때만** "
        "채운다. 없으면 빈 배열 — 추측해서 채우지 않는다(빈 값이면 시스템이 세션 정보로 처리한다)."))
    # **필수 필드다(기본값 없음).** default=0.0 이던 시절, 모델이 이 칸을 빼먹으면 조용히
    # 0.0 이 되어 **정확히 고른 계획이 임계값(0.6)에서 잘려 나갔다** — 실측(2026-07-29,
    # gpt-4.1-mini): 자료 제출 턴 5회 중 3회가 agents 는 맞는데 confidence 0.00 → 전부
    # career_chat 후퇴(풀턴 일관성 S3·S4·S7 붕괴). 누락은 "확신 없음"이 아니라 "모름"이다
    # (AGENTS §2-1 모른다 ≠ 아니다) — 기본값으로 답을 지어내지 않고, 필수로 만들어 누락을
    # 검증 오류 → 재시도로 처리한다(금지를 프롬프트가 아니라 스키마로 — §2-2와 같은 원리).
    confidence: float = Field(ge=0.0, le=1.0, description=(
        "**agents 선택에 대한 확신도**(0~1). 반드시 채운다. 발화가 명확해서 이 에이전트가 "
        "맞다고 판단했으면 0.8 이상을 준다. 0.6 미만이면 시스템은 실행하지 않고 대화로 받는다 "
        "— 즉 무엇을 원하는지 정말 모를 때만 낮게 준다. 적합도·합격 가능성에 대한 확신이 아니다."))
    requestedAgents: list[AgentName] = Field(default_factory=list, description=(
        "agents 중 **사용자가 이번 발화에서 직접 청한** 것만. 요청을 수행하려면 전제로 필요해서 "
        "네가 판단해 넣은 것은 넣지 않는다. "
        "**이것은 agents 의 부분집합을 표시하는 칸이다 — 여기 적을 것이 하나뿐이라고 agents 를 "
        "줄이지 않는다.** "
        "예: \"자소서 써줘\" 에 agents=[\"fit_analysis\",\"coverletter_draft\"] 를 냈다면 "
        "→ [\"coverletter_draft\"] (사용자는 자소서만 청했다). "
        "\"분석하고 면접 질문도\" 라면 → 둘 다. 직전 턴에 시스템이 \"진행할까요?\" 로 물은 것에 "
        "사용자가 동의했다면 그 항목도 청한 것이다."))
    ack: str = Field(default="", description=(
        "요청을 어떻게 이해했고 무엇을 하려는지 사용자에게 보여줄 자연스러운 한 문장. "
        "적합도·합격 가능성 등 판단·예측·조언은 절대 넣지 않는다(금지표현 검증에서 버려진다)."))


# 시스템 프롬프트는 **완전 정적**이다 — 실행 가능 여부(동적)는 [세션 자산 상태]로 옮겼다.
# 매 턴 동일한 접두부여야 provider 프롬프트 캐싱(OpenAI prefix cache / Anthropic
# cache_control)이 걸려 지연·비용이 준다. 여기에 세션 의존 값을 넣지 말 것.
_PLANNER_SYSTEM_TEMPLATE = """너는 취업 지원 서비스의 오케스트레이터 플래너다.
사용자 발화와 지금 상태를 함께 보고, 이번 턴에 실행할 에이전트를 실행 순서대로 agents 에 담는다.

에이전트 목록:
{manifest}

판단 원칙:
- **지금 실행 가능한 에이전트만 고른다.** 실행 가능 여부는 [세션 자산 상태]에 있다.
- **무엇을 고를지는 이 순서로 정한다** — 위에서 아래로 내려가며 **처음 맞는 항목**을 택한다.
  이 순서가 곧 우선순위다(한 발화에 둘이 맞으면 위가 이긴다).

  1. **판정·적합도를 명시적으로 요청**했고 전제(이력서·공고)가 있다 → fit_analysis.
     정리를 거치지 않는다 — 물어본 것을 주지 않고 요약만 돌려주면 요청을 무시하는 셈이다.
     예: "이 공고 나 되나?" · "지원하면 승산 있을까?" · "내 이력서랑 매칭 봐줘" ·
     "요구사항 중 내가 못 채우는 게 뭐야?" · "분석해줘".
     이어서 할 것을 함께 말했으면 뒤에 붙인다("분석하고 면접 질문도" → ["fit_analysis", "interview_prep"]).

  2. **직전 턴에 시스템이 물은 것에 대한 답·동의**다 → 그 흐름을 잇는다.
     "진단해볼까요?" 에 동의 → fit_analysis (정리를 다시 하지 않는다 — 이미 보여줬다).
     "~에는 먼저 적합도 분석이 필요해요, 진행할까요?" 에 동의 → ["fit_analysis", 원래 요청한 것].

  3. [세션 자산 상태]에 **"이번 턴 제출 자료"** 가 있다 → 그 자료를 정리해 보여주는 에이전트
     (공고 → posting_analysis, 이력서 → resume_diagnosis). 앞 턴에 무엇을 물었든 자료가 새로
     제출된 턴에는 정리부터 하고, 정리 에이전트가 결과를 보여주며 다음을 다시 묻는다.

  4. **특정 기능을 요청**했다 → 그 기능의 에이전트.
     전제가 부족하면 **가진 자산으로 지금 할 수 있는 일**을 대신 고른다 — 부족한 자료는 그
     에이전트가 결과를 들고 대화로 청한다. 대화로 넘기지 않는다.

  5. **요청이 없다**(인사·감사·하소연·잡담) → career_chat.
     자료가 있다는 이유로 사용자가 요청하지 않은 작업을 시작하지 않는다.

  6. 어느 것도 아니다 → agents 를 비우고 confidence 를 낮게 준다. 시스템이 대화로 받는다.

- **전제는 시스템이 채운다.** 목표만 고르면 되고, 전제 자산을 만드는 선행 에이전트는 검증기가
  앞에 끼운다. 그리고 **사용자가 직접 청한 것만 `requestedAgents` 에 적는다** — 사용자가
  청하지 않은 무거운 작업은 시스템이 실행 전에 먼저 묻는다(적지 않으면 묻고 넘어간다).
- 적합도·합격 가능성·조언·추천을 스스로 판단하거나 답하지 않는다 — 그것은 에이전트의 일이다.
- 발화가 짧거나 지시어("그거 해줘", "응", "이어서")면 [최근 대화] 맥락으로 해석한다(사다리 2).
- confidence 는 선택 확신도(0~1). 애매하면 낮게 준다.
- target 에는 발화가 가리키는 공고/대상 참조가 있으면 그대로 옮겨 적는다(추측 금지).
- ack 에는 요청을 어떻게 이해했고 무엇을 하려는지 자연스러운 한 문장을 쓴다.
  적합도·합격 가능성 등 판단·예측·조언은 절대 넣지 않는다."""


def _build_manifest() -> str:
    """레지스트리에서 **정적** 에이전트 목록을 만든다 (설명만, 실행 가능 여부 없음).

    실행 가능 여부(동적)는 _asset_state() 가 사용자 메시지 쪽에 싣는다 — 시스템 프롬프트를
    매 턴 동일하게 유지해 provider 프롬프트 캐싱이 걸리게 하기 위해서다. 에이전트 추가 시
    이 함수는 그대로다.
    """

    from jobis_ai.agents import get_agent_registry

    lines = []
    for spec in get_agent_registry().values():
        if spec.internal:
            continue    # 오케스트레이터 전용 단계 — 플래너 어휘에 넣지 않는다(재측정 회피)
        lines.append(f"- {spec.name}: {spec.description}")
        # 인자를 받는 에이전트는 무엇을 넘길 수 있는지 함께 보여준다 — 안 보여주면 LLM 은
        # 값을 넘길 수 있다는 것 자체를 모른다(스키마가 곧 지시문).
        for pname, pdesc in spec.params:
            lines.append(f"    · 인자 {pname}: {pdesc}")
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
    submitted = session.get("_submittedThisTurn") or []
    if submitted:
        kind_ko = {"resume": "이력서", "job_posting": "공고", "resume_extra": "이력서 추가 정보"}
        parts.append("이번 턴 제출 자료: " + ", ".join(kind_ko.get(k, k) for k in submitted))
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

    # 실행 가능/불가를 여기(동적 블록)에 싣는다 — 시스템 프롬프트는 정적으로 유지(캐싱).
    # 가능한 이름을 명시 나열하는 이유: 상태 서술만으로는 모델이 못 할 일을 고르는 사례가
    # 실측됐다(그때는 검증기가 막고 대화로 돌아간다).
    from jobis_ai.orchestrator.router import asset_label

    feasibility = agent_feasibility(session)
    feasible = [name for name, missing in feasibility.items() if missing is None]
    blocked = [f"{name}({asset_label(missing)} 없음)"
               for name, missing in feasibility.items() if missing is not None]
    lines = [" / ".join(parts), f"지금 실행 가능한 에이전트: {', '.join(feasible)}"]
    if blocked:
        lines.append(f"실행 불가: {', '.join(blocked)}")
    return "\n".join(lines)


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

    # 시스템 프롬프트는 세션과 무관하게 매 턴 동일하다(정적) — provider 프롬프트 캐싱 대상.
    system = _PLANNER_SYSTEM_TEMPLATE.format(manifest=_build_manifest())
    user_content = (
        f"[최근 대화]\n{_history_block(session)}\n\n"
        f"[세션 자산 상태]\n{_asset_state(session)}\n\n[사용자 발화]\n{message}"
    )
    # 에이전트 선택은 고급 모델 유지 — 경량(gpt-5-nano) 실측에서 정확도 100%→48.8%로
    # 붕괴(과잉 선택·오되묻기). 스키마 제한·검증기로도 못 막는 판단 품질 차이다 (0724 실측).
    return run_structured(AgentPlan, system, user_content, node="agent_planner")
