"""dispatch 검증기 — 플래너가 고른 실행 시퀀스를 **실행 가능하게만** 보정한다.

여기에 "어떤 발화면 어떤 에이전트" 대응표는 없다. 무엇을 할지는 발화와 사용자 상태를 함께
본 플래너(LLM)가 정하고, 이 파일은 레지스트리의 capability manifest(전제·산출)로 **확인만**
한다:

- 전제 자산이 없으면 그 자산을 만드는 에이전트를 앞에 끼워 채운다(선언된 produces 로부터 유도).
- 그래도 못 채우면 그 에이전트를 실행 목록에서 뺀다 — 대신 무엇을 할지는 정하지 않는다.
- 실행할 것이 남지 않으면 대화형 에이전트에게 턴을 넘긴다. 사용자가 방금 한 말에 답하면서
  필요한 자료를 직접 요청하게 한다 — **고정 문구로 대화를 끝내지 않는다.**

플래너가 애초에 못 할 일을 고르지 않도록, 지금 실행 가능한지는 `agent_feasibility()` 로
플래너 프롬프트에 함께 실린다. 판단은 플래너, 확인은 여기(코드)다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# 자료가 없어도 대화로 이어받는 에이전트 — 실행할 것이 없을 때 턴을 넘길 곳.
FALLBACK_AGENT = "career_chat"


@dataclass(frozen=True)
class Dispatch:
    """검증기가 확정한 실행 시퀀스."""

    # 순서대로 실행할 에이전트 이름들 (레지스트리 키).
    agents: tuple[str, ...] = ()
    # 실행 시퀀스가 플래너의 선택과 달라졌을 때만 쓰는 가시화 문구.
    note: str = ""
    # 동의 게이트 — 비어 있지 않으면 이번 턴에는 실행하지 않고 이 질문만 한다.
    # 무거운 생산자(fit_analysis 등)가 **자동 삽입**될 때, 수십 초·LLM 여러 회짜리
    # 파이프라인을 말없이 시작하는 대신 먼저 묻는다. 사용자가 동의하면 다음 턴에
    # 플래너가 그 생산자를 명시적으로 고르므로 게이트에 다시 걸리지 않는다.
    ask: str = ""


_AGENT_LABEL = {
    "fit_analysis": "적합도 분석",
    "posting_analysis": "공고 분석",
    "application_plan": "지원 경로 설계",
    "preference_intake": "선호 파악",
    "career_chat": "진로 대화",
    "job_recommend": "공고 추천",
    "resume_diagnosis": "이력서 진단",
    "interview_prep": "면접 준비",
    "coverletter_draft": "자소서 초안",
    "roadmap_manager": "로드맵 조회",
}

_ASSET_LABEL = {
    "resume": "이력서",
    "job_posting": "공고",
    "analysis": "적합도 분석 결과",
    "roadmap": "준비 로드맵",
    "recommendations": "추천 공고",
    "coverletter": "자소서 초안",
}

# 전제 자동 삽입의 재귀 깊이 상한 — 생산자 체인 순환 방어.
_MAX_INSERT_DEPTH = 2


def agent_label(name: str) -> str:
    """에이전트 키 → 사람이 읽는 라벨. 이름의 단일 출처(웹 브릿지도 이걸 쓴다)."""

    return _AGENT_LABEL.get(name, name)


def asset_label(name: str) -> str:
    """자산 키 → 사람이 읽는 라벨."""

    return _ASSET_LABEL.get(name, name)


def _session_assets(session: dict[str, Any]) -> set[str]:
    """세션에서 보유 자산 이름 집합을 뽑는다. profile 은 resume 으로 인정."""

    assets = {
        key
        for key in ("resume", "job_posting", "analysis", "roadmap", "recommendations", "coverletter")
        if session.get(key)
    }
    if session.get("profile"):
        assets.add("resume")
    return assets


def _plan_agent(spec: Any, assets: set[str], plan: list[str],
                registry: dict[str, Any], depth: int = 0) -> str | None:
    """spec 을 실행 가능하게 plan 에 넣는다. 못 채우는 결측이면 그 자산 이름을 반환.

    결측 자산을 다른 에이전트의 produces 로 채울 수 있으면 그 생산자를 먼저(재귀) 삽입한다 —
    순서를 어딘가에 적어 두는 대신 선언된 capability 로부터 유도한다.

    **전부-또는-전무다.** 사본에 쌓고 성공할 때만 반영한다. 그러지 않으면 전제가 둘인
    에이전트에서 앞의 생산자만 끼워진 채 목표가 빠진 계획이 남는다.
    """

    if depth > _MAX_INSERT_DEPTH:
        return "recursion"

    trial_assets = set(assets)
    trial_plan = list(plan)

    for asset in spec.preconditions:
        if asset in trial_assets:
            continue
        # 같은 자산의 생산자가 둘 이상 등록되면 **레지스트리 등록 순서가 곧 선택 정책**이 된다.
        # 현재는 자산마다 생산자가 유일해 문제가 없지만, 두 번째 생산자를 등록할 때는
        # 여기 선택 규칙(우선순위 필드 등)을 함께 정해야 한다.
        producer = next((s for s in registry.values() if asset in s.produces), None)
        if producer is None or producer.name in trial_plan:
            return asset
        missing = _plan_agent(producer, trial_assets, trial_plan, registry, depth + 1)
        if missing:
            return missing

    if spec.name not in trial_plan:
        trial_plan.append(spec.name)
        trial_assets.update(spec.produces)

    plan[:] = trial_plan
    assets.clear()
    assets.update(trial_assets)
    return None


def agent_feasibility(session: dict[str, Any]) -> dict[str, str | None]:
    """지금 상태에서 각 에이전트가 실행 가능한지 — 가능하면 None, 아니면 결측 자산 이름.

    플래너 프롬프트가 이걸 실어 보낸다. 플래너가 상태를 알고 고르므로, "이 상황이면 저 에이전트"
    같은 대체 규칙을 코드에 둘 필요가 없다.
    """

    from jobis_ai.agents import get_agent_registry

    registry = get_agent_registry()
    have = _session_assets(session)
    out: dict[str, str | None] = {}
    for name, spec in registry.items():
        # 에이전트마다 독립 판정 — 같은 턴의 다른 에이전트가 만들 자산은 가정하지 않는다.
        out[name] = _plan_agent(spec, set(have), [], registry)
    return out


def validate_plan(agents: tuple[str, ...] | list[str], session: dict[str, Any]) -> Dispatch:
    """플래너가 고른 시퀀스를 실행 가능하게 보정한다. 순수 결정론 — LLM 없음.

    미등록 이름·전제 결측 에이전트는 뺀다(무엇으로 바꿀지는 정하지 않는다).
    남는 것이 없으면 대화형 에이전트에게 턴을 넘긴다.
    """

    from jobis_ai.agents import get_agent_registry

    registry = get_agent_registry()
    assets = _session_assets(session)

    plan: list[str] = []
    dropped: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name in agents:
        if name in seen:
            continue
        seen.add(name)
        spec = registry.get(name)
        if spec is None:
            dropped.append((name, "unknown"))
            continue
        missing = _plan_agent(spec, assets, plan, registry)
        if missing:
            dropped.append((name, missing))

    if not plan:
        return Dispatch((FALLBACK_AGENT,))

    # 동의 게이트 — 플래너가 고르지 않은 **무거운** 생산자가 자동 삽입됐으면 실행하지 않고
    # 먼저 묻는다. note 로 알리고 이미 도는 것과, 시작 전에 묻는 것은 UX·비용이 다르다.
    requested = set(agents)
    inserted_heavy = [n for n in plan
                      if n not in requested and getattr(registry[n], "heavy", False)]
    if inserted_heavy:
        goals = [n for n in plan if n in requested]
        goal_label = " · ".join(agent_label(n) for n in goals) or "요청하신 작업"
        heavy_label = " · ".join(agent_label(n) for n in inserted_heavy)
        return Dispatch((), ask=(
            f"{goal_label}에는 먼저 {heavy_label}이 필요해요. "
            f"시간이 조금 걸리는 작업인데(수십 초), 바로 진행할까요?"))

    labels = " → ".join(agent_label(n) for n in plan)
    if dropped:
        lack = ", ".join(asset_label(a) for _, a in dropped if a not in ("unknown", "recursion"))
        note = (f"{lack}이 아직 없어서 {labels}부터 할게요." if lack
                else f"{labels}(으)로 이어서 진행할게요.")
    else:
        note = f"{labels}(으)로 이해했어요. 순서대로 실행할게요." if len(plan) > 1 else ""
    return Dispatch(tuple(plan), note=note)
