"""에이전트 자기 루프 하네스 — 목표를 받은 에이전트가 **도구를 골라 쓰며 스스로 돈다.**

지금까지 에이전트는 `session dict → AgentResult` 순수 함수였다. 오케스트레이터가 "누가
실행할지"를 정하면 그 안에서는 정해진 일만 한 번 하고 끝났다. 그래서 여러 턴에 걸쳐
상태를 갖고, 결과를 보고 다음 행동을 스스로 정하는 일(면접 꼬리 질문, 자소서 자기비판
루프)을 표현할 수 없었다.

이 하네스가 그 격차를 메운다. 역할 분담은 명확하다:

  · **도구(파이썬 함수)** — 정확해야 하는 것. LLM 없음, 같은 입력이면 같은 출력.
    소재 고르기·근거 찾기·답변 점검처럼 값을 단정해야 하는 일은 전부 여기.
  · **에이전트(LLM)** — 자유도가 필요한 것. 어떤 도구를 쓸지, 무엇을 물을지, 어떻게
    말할지. 판단은 하되 **없는 근거를 만들 수는 없다** — 근거는 도구만 준다.
  · **하네스(이 파일)** — 둘을 잇고 가둔다. 도구 이름은 Literal 로 제한(환각 구조적
    차단), 스텝 상한, 사용자향 문장은 금지표현 검증, 매 스텝 궤적 기록.

LLM 미설정·실패면 루프를 돌리지 않고 (None, warnings) 로 돌려준다 — 호출부가 결정론
폴백을 쓴다. 관찰 가능성은 하네스가 책임진다: 스텝마다 trace + 로그 한 줄.
"""

from __future__ import annotations

import contextvars
import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field, create_model

from jobis_ai import trace
from jobis_ai.structured import run_structured
from jobis_ai.verify_rules import FORBIDDEN_EXPRESSIONS, drop_forbidden_sentences

log = logging.getLogger(__name__)

# 한 턴에 허용하는 도구 호출 수. 넘으면 지금까지 관찰로 답을 만들게 한다.
#
# 3 → 5 (2026-07-29). 3 은 "도구 두 번 쓰면 끝"이라 재선택 동역학이 감긴다 — 자소서 실측에서
# 실제로 `find_evidence → save_draft → check_draft → save_draft(재작성)` 로 4스텝이 필요했고
# (그래서 그쪽은 7 로 올려 뒀다), 상한이 곧 "몇 번 고쳐 쓸 수 있나"를 정한다. 프로토타입은 10.
# 상한 도달은 `loop_no_reply_after_max_steps` 경고와 스텝 로그로 사후에 읽을 수 있다 —
# 실제 도달 빈도를 보고 다시 조정한다.
DEFAULT_MAX_STEPS = 5


@dataclass(frozen=True)
class ToolSpec:
    """에이전트가 쓸 수 있는 도구 하나. **결정론 파이썬 함수여야 한다.**

    run(state, arg) -> (관찰 문자열, 도구가 남길 데이터). 관찰 문자열이 다음 스텝의
    LLM 입력이 되므로, 사실만 담고 판단·권유를 넣지 않는다.
    실패는 예외 대신 관찰 문자열로 알린다(루프를 죽이지 않는다).
    """

    name: str
    description: str
    run: Callable[[dict[str, Any], str], tuple[str, dict[str, Any]]]
    arg_description: str = "필요 없으면 빈 문자열."


@dataclass
class LoopOutcome:
    """루프 결과. reply 가 비어 있으면 **검증을 통과한 문장을 못 만든 것**(호출부가 폴백).

    실패해도 outcome 자체는 돌려준다 — None 을 돌려주면 호출부가 폴백을 만들면서 실패
    이유(warnings)를 잃는다. 실측에서 그 때문에 "왜 폴백됐는지" 로그에 아무것도 없었다.
    """

    reply: str = ""
    steps: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    # 도구들이 남긴 데이터의 누적(마지막 값이 이긴다) — 호출부가 세션 갱신에 쓴다.
    data: dict[str, Any] = field(default_factory=dict)


# 도구가 돌려주는 데이터 dict 에 이 키로 경고를 담으면 하네스가 LoopOutcome.warnings 로 옮긴다.
# 도구는 (관찰, 데이터) 만 내므로 경고를 낼 자리가 없었는데, 다른 에이전트를 부르는 도구는
# 그 에이전트의 경고를 삼키면 안 된다(폴백 이유를 잃는 것과 같은 실수).
TOOL_WARNINGS_KEY = "__warnings__"

# 위임 깊이 — 위임 안에서 또 위임하는 것을 막는다(재귀 폭주 방어).
_delegating: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "jobis_agent_delegating", default=False
)


@dataclass
class DelegateOutcome:
    """위임 한 번의 결과. `refusal` 이 비어 있지 않으면 **상대를 실행하지 않았다.**

    거부를 예외나 None 으로 표현하지 않는 이유는 분모 때문이다 — 성공만 남기면
    "몇 % 성공하나"에 영구히 답할 수 없다(평가 리포트 §1-1).
    """

    result: Any | None = None       # AgentResult (성공했을 때만)
    refusal: str = ""               # 거부 사유 **코드** — 문장이 바뀌어도 집계가 안 깨지게
    message: str = ""               # 사람이 읽는 거부/관찰 문구
    warnings: list[dict[str, Any]] = field(default_factory=list)


def call_agent_readonly(
    session: dict[str, Any],
    target: str,
    *,
    caller: str = "",
    allowed: tuple[str, ...] | None = None,
    render_reply: bool = False,
) -> DelegateOutcome:
    """**에이전트 간 읽기 전용 호출의 단일 관문.** 가드는 여기에만 있다.

    전에는 같은 가드가 두 벌이었다 — `delegate_tool`(자기 루프용)과
    `application_plan._related_postings`(단발 호출이라 도구를 못 쓰는 자리에서 손으로
    재현한 것). 그리고 **어긋나 있었다**: 후자에는 `heavy` 검사도, 중첩 위임 차단도
    없었다. `job_recommend` 가 언젠가 heavy 로 바뀌면 그쪽 경로만 조용히 동의
    게이트(§2-7)를 우회한다. 가드를 두 벌 두면 언젠가 한 벌이 낡는다.

    가드(순서대로): 선언 화이트리스트 → 중첩 금지(깊이 1) → 등록 여부 → heavy 금지
    → 전제 자산. 통과하면 **세션 사본**으로 실행하고 스테이징을 비운다 — 상태 전이는
    오케스트레이터 독점이다(§2-4). 거부도 실패도 trace 에 남긴다.
    """

    from jobis_ai.agents import get_agent_registry
    from jobis_ai.orchestrator.router import runnable_now, session_assets

    def refused(reason: str, message: str) -> DelegateOutcome:
        trace.emit("delegate_refused", f"위임 거부: {target or '(빈 이름)'} — {reason}",
                   {"target": target, "from": caller, "reason": reason})
        return DelegateOutcome(refusal=reason, message=message)

    if allowed is not None and target not in allowed:
        return refused("not_declared",
                       f"'{target or '(빈 이름)'}' 에게는 물어볼 수 없습니다. "
                       f"물어볼 수 있는 상대: {', '.join(allowed)}")
    if _delegating.get():
        return refused("nested", "위임 안에서 또 위임할 수 없습니다.")

    spec = get_agent_registry().get(target)
    if spec is None:
        return refused("unregistered", f"'{target}' 는 등록돼 있지 않습니다.")
    if spec.heavy:
        return refused("heavy",
                       f"'{target}' 는 무거운 파이프라인이라 여기서 부를 수 없습니다 "
                       "(사용자 동의를 받아 오케스트레이터가 실행합니다).")
    if not runnable_now(spec, session_assets(session)):
        return refused("preconditions_missing",
                       f"'{target}' 는 지금 실행할 수 없습니다 — 필요한 자산: "
                       f"{', '.join(spec.preconditions) or '없음'}")

    copy = dict(session)
    copy["_stagedUpdates"] = {}      # 읽기 전용 — 위임의 캐시·상태가 본 턴에 남지 않는다
    token = _delegating.set(True)
    try:
        outcome = spec.entry(copy)
        # 상대가 **도구**면 entry 는 말하지 않는다 — 문장은 표현 계층이 만든다.
        # 이걸 빼면 도구로 내려간 상대(resume_diagnosis 등)를 부를 때마다 관찰이
        # "문장을 내지 않았습니다"가 되어 위임이 조용히 쓸모없어진다.
        # **문장이 필요한 호출자만 켠다**(render_reply) — 산출 데이터만 쓰는 호출자에게는
        # 표현 계층을 도는 것이 순비용이고, 렌더가 실패하면 멀쩡한 데이터까지 잃는다.
        if render_reply and spec.kind == "tool" and spec.render is not None and not outcome.reply:
            outcome.reply, render_warnings = spec.render(outcome.data, dict(session))
            outcome.warnings.extend(render_warnings)
    except Exception as exc:      # noqa: BLE001 — 위임 실패가 호출자를 죽이지 않는다
        return refused("entry_failed", f"'{target}' 실행이 실패했습니다: {exc}")
    finally:
        _delegating.reset(token)

    trace.emit("delegate", f"에이전트 위임 호출: {target}", {
        "target": target, "from": caller, "reply": (outcome.reply or "")[:200],
        "dataKeys": sorted(outcome.data.keys()),
    })
    log.info("delegate → %s (%d자, data=%s)", target, len(outcome.reply or ""),
             sorted(outcome.data.keys()))
    return DelegateOutcome(
        result=outcome,
        warnings=[{"code": "delegated_warning", "message": f"{target}: {w.get('message', '')}"}
                  for w in outcome.warnings],
    )


def delegate_tool(allowed: tuple[str, ...], *, name: str = "ask_agent") -> ToolSpec:
    """**에이전트가 다른 에이전트를 부르는 통로.** 세션(blackboard) 말고 직접 물어본다.

    지금까지 에이전트는 서로에게 아무것도 요청할 수 없었다(평가 문서 §2-2). 자기 루프가
    생기면서 "이건 저쪽이 이미 계산한다"는 상황이 실제로 생긴다 — 예: 자소서가 쓸 근거가
    빈약할 때, 무엇이 왜 빈약한지는 이력서 진단이 이미 세는 일이다. 같은 계산을 두 번
    구현하는 대신 물어본다.

    **읽기 전용 호출이다.** 상대의 산출은 관찰로만 쓰고 `sessionUpdates` 는 적용하지 않는다 —
    턴의 상태 전이는 오케스트레이터만 한다(chat.py 규약). 그 밖의 가드:

      · 호출 대상은 **선언된 화이트리스트**만. 등록돼 있어도 선언 안 했으면 못 부른다.
      · `heavy`(수십 초 파이프라인)는 금지 — 동의 게이트를 에이전트가 우회하게 된다.
      · 전제 자산이 없으면 실행하지 않고 그 사실을 관찰로 돌려준다.
      · 위임 안에서 또 위임은 금지(깊이 1).

    **거부도 trace 에 남긴다**(`delegate_refused`). 성공만 남기면 hand-off 성공률의 **분모가
    없어** "몇 % 성공하나"에 영구히 답할 수 없다(평가 리포트 §1-1 이 지적한 구멍).
    """

    labels = ", ".join(allowed)

    def run(state: dict[str, Any], arg: str) -> tuple[str, dict[str, Any]]:
        target = (arg or "").strip()
        call = call_agent_readonly(
            state.get("_session") or {}, target, caller="agent_loop", allowed=allowed,
            render_reply=True,      # 루프의 관찰은 문장이다
        )
        if call.refusal:
            return call.message, {}      # 거부 사유는 call_agent_readonly 가 trace 에 남겼다

        outcome = call.result
        said = (outcome.reply or "").strip()
        observation = (f"{target} 의 답: {said[:600]}" if said
                       else f"{target} 는 문장을 내지 않았습니다(데이터: {sorted(outcome.data.keys())}).")
        return observation, {TOOL_WARNINGS_KEY: call.warnings} if call.warnings else {}

    return ToolSpec(
        name=name,
        description=("다른 담당에게 물어본다(읽기 전용 — 그 결과는 참고용이고 저장되지 않는다). "
                     f"물어볼 수 있는 상대: {labels}"),
        run=run,
        arg_description=f"물어볼 상대 이름. {labels} 중 하나.",
    )


@lru_cache(maxsize=16)
def _decision_schema(tool_names: tuple[str, ...]) -> type[BaseModel]:
    """도구 이름을 Literal 로 묶은 결정 스키마를 만든다(도구 집합마다 1회, 캐시).

    플래너가 에이전트 이름을 Literal 로 제한한 것과 같은 이유다 — 등록되지 않은 도구를
    부르는 환각을 프롬프트 부탁이 아니라 **스키마로** 막는다.
    """

    # action 자리에 **도구 이름**을 바로 쓰는 것도 받는다. 실측(2026-07-29, 자소서 루프):
    # 모델이 `action="save_draft"` 를 내 3회 재시도 끝에 턴이 통째로 실패했다. 두 칸(action·
    # tool)에 나눠 담는 것은 우리 사정이지 모델이 자연스럽게 하는 표기가 아니다. 허용값은
    # 여전히 등록된 도구 이름뿐이므로 환각 차단은 그대로다 — 막을 것은 없는 도구지 표기가 아니다.
    return create_model(
        "LoopDecision",
        action=(Literal[("use_tool", "reply") + tool_names], Field(description=(  # type: ignore[valid-type]
            "다음에 할 일. use_tool = 도구를 하나 부른다(tool 에 이름). "
            "reply = 지금까지 관찰로 사용자에게 답한다. 도구 이름을 여기에 바로 써도 같은 뜻이다."))),
        tool=(Literal[tool_names] | None, Field(default=None, description=(  # type: ignore[valid-type]
            "action=use_tool 일 때 부를 도구 이름. reply 면 비운다."))),
        arg=(str, Field(default="", description="도구 인자. 필요 없으면 빈 문자열.")),
        reply=(str, Field(default="", description=(
            "action=reply 일 때 사용자에게 보낼 말. 관찰로 확인된 근거만 쓴다 — "
            "도구가 주지 않은 사실·수치·회사명을 지어내지 않는다."))),
        __base__=BaseModel,
    )


def _tool_manifest(tools: dict[str, ToolSpec]) -> str:
    return "\n".join(
        f"- {t.name}: {t.description}\n    · 인자: {t.arg_description}"
        for t in tools.values()
    )


def run_agent_loop(
    *,
    goal_system: str,
    facts: dict[str, Any],
    tools: dict[str, ToolSpec],
    state: dict[str, Any],
    node: str,
    max_steps: int = DEFAULT_MAX_STEPS,
    session_id: str = "",
) -> LoopOutcome:
    """도구를 쓰는 자기 루프를 돌린다. **reply 가 비면 실패**(호출부가 결정론 폴백).

    goal_system : 에이전트의 목표·규율. 도구 목록은 하네스가 덧붙인다.
    facts       : 이번 턴의 사실(발화·상태 요약). LLM 입력.
    state       : 도구가 읽고 고치는 작업 상태(여러 턴에 걸쳐 세션에 보존되는 그 dict).
    """

    schema = _decision_schema(tuple(tools))
    system = (
        f"{goal_system.rstrip()}\n\n"
        f"쓸 수 있는 도구:\n{_tool_manifest(tools)}\n\n"
        "규율:\n"
        "- 근거는 도구만 준다. 도구가 주지 않은 사실·수치·회사명을 지어내지 않는다.\n"
        "- userFacts 는 사용자가 이전 대화에서 직접 말한 사실이다 — 기억으로 존중해 반영하되,"
        " 거기 없는 개인 사실을 지어내지 않는다.\n"
        "- 필요한 도구를 다 쓴 뒤 action=reply 로 답한다. 쓸 도구가 없으면 바로 reply.\n"
        "- 적합도·합격 가능성을 단정하지 않는다."
    )

    outcome = LoopOutcome()
    observations: list[dict[str, str]] = []

    # **직전까지의 대화를 매 스텝 함께 싣는다.** 프로토타입(Agent_Test)의 루프가 전체 메시지
    # 히스토리를 들고 도는 것과 같은 자리다 — 우리 루프는 `facts`(이번 턴 요약)와 이번 턴의
    # 관찰만 봐서, 여러 턴에 걸친 에이전트(면접·자소서)가 "앞서 무슨 얘기를 했는지"를 몰랐다.
    # 출처는 `state["_session"]` — 이 하네스가 이미 쓰는 규약이다(delegate_tool 도 같은 키를 읽는다).
    session = state.get("_session") or {}
    if session:
        from jobis_ai.orchestrator.session import recent_history

        history = recent_history(session)
    else:
        history = []
    # 사용자가 이전에 직접 말한 지속 사실(D82) — 모든 자기 루프 에이전트(자소서·면접·선호)가
    # 같은 화이트보드 기억을 본다(D84). "내가 했던 말을 에이전트가 기억 못하는 일이 없도록".
    user_facts = [str(f) for f in (session.get("user_facts") or []) if str(f).strip()]

    for step in range(1, max_steps + 1):
        payload = json.dumps(
            {"facts": facts, "recentHistory": history, "userFacts": user_facts,
             "observations": observations},
            ensure_ascii=False)
        decision, warnings = run_structured(schema, system, payload, node=node)
        outcome.warnings.extend(warnings)
        if decision is None:
            # LLM 미설정·실패 — 여기까지의 관찰이 있어도 사용자향 문장을 만들 수 없다.
            trace.emit("agent_step", f"{node} 루프 중단: 판단 불가", {
                "agent": node, "step": step, "action": "unavailable",
            })
            log.info("[%s] %s loop step%d: unavailable", session_id, node, step)
            outcome.steps = list(observations)
            return outcome      # reply 가 빈 채로 — 호출부가 폴백하되 이유(warnings)는 남는다

        # 도구 이름을 action 에 쓴 경우를 정규화한다(위 스키마 주석).
        action, chosen = decision.action, decision.tool
        if action not in ("use_tool", "reply"):
            action, chosen = "use_tool", action

        if action == "reply" or not chosen:
            reply = (decision.reply or "").strip()
            trace.emit("agent_step", f"{node} 루프 종료: 답변 작성", {
                "agent": node, "step": step, "action": "reply",
            })
            log.info("[%s] %s loop step%d: reply (%d자)", session_id, node, step, len(reply))
            # 사용자향 문장은 검증을 면제받지 않는다(표현 계층 공통 규율). 다만 **한 번은
            # 다시 쓰게 한다** — 금지표현 목록에는 '반드시'·'무조건' 처럼 코칭 문장에서
            # 자연스럽게 나오는 낱말이 있어서, 한 번 걸렸다고 기능을 폴백시키면 LLM 이
            # 만든 맥락 있는 답변을 통째로 버리게 된다(실측: 답변 점검 턴이 매번 폴백됐다).
            hit = next((e for e in FORBIDDEN_EXPRESSIONS if e in reply), "")
            if hit:
                observations.append({
                    "tool": "(검증)", "arg": hit,
                    "observation": (f"방금 쓴 문장에 금지표현 '{hit}' 이 있어 사용할 수 없습니다. "
                                    "그 표현을 빼고 같은 내용을 다시 쓰세요."),
                })
                outcome.warnings.append({
                    "code": "loop_reply_rewritten",
                    "message": f"{node}: 답변에 금지표현 '{hit}' → 재작성 요청.",
                })
                log.info("[%s] %s loop step%d: 금지표현 %r → 재작성", session_id, node, step, hit)
                continue
            outcome.reply = reply
            outcome.steps = list(observations)
            return outcome

        tool = tools.get(chosen)
        if tool is None:      # Literal 이 막지만 방어적으로
            observation = f"알 수 없는 도구: {chosen}"
            tool_data: dict[str, Any] = {}
        else:
            try:
                observation, tool_data = tool.run(state, (decision.arg or "").strip())
            except Exception as exc:      # 도구 실패가 턴을 죽이지 않는다
                observation = f"도구 실행 실패: {exc}"
                tool_data = {}
                outcome.warnings.append({
                    "code": "loop_tool_failed",
                    "message": f"{node}.{chosen}: {exc}",
                })
        # 도구가 표준 키로 낸 경고는 outcome 으로 올린다(데이터에 남겨두면 세션에 섞인다).
        tool_warnings = tool_data.pop(TOOL_WARNINGS_KEY, None)
        if tool_warnings:
            outcome.warnings.extend(tool_warnings)
        outcome.data.update(tool_data)
        observations.append({"tool": chosen, "arg": decision.arg or "",
                             "observation": observation})
        trace.emit("agent_step", f"{node} 도구 호출: {chosen}", {
            "agent": node, "step": step, "action": "use_tool",
            "tool": chosen, "arg": decision.arg, "observation": observation[:200],
        })
        log.info("[%s] %s loop step%d: tool=%s arg=%r → %s", session_id, node, step,
                 chosen, decision.arg, observation[:80])

    # 상한 도달 — 마지막으로 답만 만들게 한다(도구 없이).
    # 도달 자체를 trace 로 남긴다: DEFAULT_MAX_STEPS 주석의 "실제 도달 빈도를 보고 다시
    # 조정한다"를 하려면 세는 곳이 있어야 한다(평가 리포트 §3-2 감점). 경고가 아니라 trace 인
    # 이유 — 상한 도달 자체는 오동작이 아니고(답을 만들면 정상 종료), 빈도만 궁금한 것이다.
    # loop_consistency 가 이 이벤트(action="limit")를 집계한다.
    trace.emit("agent_step", f"{node} 도구 상한({max_steps}) 도달 → 답변만 작성", {
        "agent": node, "step": max_steps, "action": "limit",
    })
    payload = json.dumps({"facts": facts, "recentHistory": history,
                          "observations": observations,
                          "note": "도구 사용 상한에 도달했다. 지금까지 관찰로 답만 작성한다."},
                         ensure_ascii=False)
    decision, warnings = run_structured(schema, system, payload, node=f"{node}_final")
    outcome.warnings.extend(warnings)
    outcome.steps = list(observations)
    log.info("[%s] %s loop: max_steps(%d) 도달 → 답변만 작성", session_id, node, max_steps)
    if decision is None or not (decision.reply or "").strip():
        outcome.warnings.append({
            "code": "loop_no_reply_after_max_steps",
            "message": f"{node}: 도구 상한({max_steps}) 뒤에도 답변을 만들지 못했습니다.",
        })
        return outcome
    # 상한 도달 뒤에는 재작성 기회가 없으므로 **문장 단위로만** 버린다(D123) — 전량 폐기는
    # 상한까지 쌓은 관찰로 만든 답을 '반드시' 한 단어로 지우고 결정론 폴백을 내보냈다.
    reply, hits = drop_forbidden_sentences(decision.reply.strip())
    if hits:
        outcome.warnings.append({
            "code": "loop_reply_softened",
            "message": f"{node}: 마지막 답변에서 금지표현 {hits} 이 든 문장을 제거.",
        })
    if not reply:
        outcome.warnings.append({
            "code": "loop_reply_forbidden_expression",
            "message": f"{node}: 마지막 답변이 금지표현 제거 후 비어 버렸습니다.",
        })
        return outcome
    outcome.reply = reply
    return outcome
