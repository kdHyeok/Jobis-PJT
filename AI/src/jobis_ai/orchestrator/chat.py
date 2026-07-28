"""대화 진입점 — handle_chat (llm-planner-design.md).

**추론은 자율, 행동과 상태 전이는 하네스로 좁힌다.**

- 그라운딩: 첨부·세션 자산·최근 대화·에이전트 실행 가능 여부를 플래너의 입력으로 강제한다.
- 액션 스페이스 제한: 플래너가 낼 수 있는 것은 레지스트리에 등록된 에이전트 이름뿐이다
  (스키마 Literal). 실행은 그 에이전트만 하고, 상태 전이는 outcome.sessionUpdates 로만 일어난다.
- 검증: 고른 시퀀스의 실행 가능성은 validate_plan(순수 코드)이, 사용자에게 나가는 문장은
  금지표현 검증(safe_ack)이 사후에 확인한다.
- 재계획 루프: 다중 에이전트 시퀀스에서는 하나가 끝날 때마다 결과 요약을 경량 플래너에
  되물어 계속/중단/수정을 정한다(상한 2회) — "결과를 보고 다음을 다시 정하는" 오케스트레이션.

이 모듈은 판단하지 않고, 흐름 순서도 정해 두지 않는다. 무엇을 할지는 플래너가 매 턴 새로
정한다. LLM 이 없거나 확신이 낮으면 대화형 에이전트가 턴을 받는다 — 고정 문구로 대화를
끝내지 않는다.

세션 I/O 는 **write-back** 이다: 턴 시작에 한 번 읽고(작업 사본), 턴 중의 모든 변경은
사본+pending 에만 쌓고, 턴 끝에 한 번 저장한다. 에이전트가 중간에 남기는 캐시
(_common.ensure_profile)도 사본의 _stagedUpdates(=pending) 로 들어온다.
"""

from __future__ import annotations

from typing import Any

from jobis_ai import trace
from jobis_ai.agents import get_agent_registry
from jobis_ai.contracts.api import ChatRequest, ChatResponse
from jobis_ai.orchestrator.attachment_kind import resolve_kind
from jobis_ai.orchestrator.planner import (
    CONFIDENCE_THRESHOLD,
    plan_agents,
    replan_after,
    safe_ack,
)
from jobis_ai.orchestrator.router import FALLBACK_AGENT, Dispatch, validate_plan
from jobis_ai.orchestrator.session import HISTORY_MAX_ITEMS, get_session_store

_ATTACHMENT_ACK = {
    "resume": "이력서를 받았어요.",
    "job_posting": "공고를 받았어요.",
    "resume_extra": "추가 정보를 이력서에 반영했어요.",
}

# 프론트의 kind 를 내용으로 바로잡았을 때 — 무엇이 왜 바뀌었는지 사용자에게 말한다.
_ATTACHMENT_ACK_CORRECTED = {
    "resume": "붙여주신 내용이 공고가 아니라 이력서로 보여서, 이력서로 등록했어요.",
    "job_posting": "붙여주신 내용이 이력서가 아니라 채용 공고로 보여서, 공고로 등록했어요.",
}

# 턴당 재계획 상한 — 재계획이 재계획을 부르는 폭주 방지 (기존 하네스 철학 그대로).
_MAX_REPLANS = 2


def _apply_attachments(request: ChatRequest, session: dict,
                       stage) -> tuple[list[str], list[str], list[dict]]:
    """첨부를 세션 사본에 반영하고 (확인 문구, 저장된 kind, 경고) 를 돌려준다.

    프론트는 "직전에 요청한 자료"의 슬롯으로 다음 붙여넣기를 그대로 보내므로,
    공고를 기다리는 중에 이력서를 붙여넣으면 job_posting 으로 온다. 저장 전에
    내용을 보고(resolve_kind) 명백히 반대 종류면 바로잡는다.
    """

    acks: list[str] = []
    kinds: list[str] = []
    warnings: list[dict] = []
    for att in request.attachments:
        kind = att.kind
        # URL 은 내용이 아니라 주소라 판정이 성립하지 않는다 — 텍스트만 검증.
        if kind in ("resume", "job_posting") and att.sourceType.value == "text":
            kind, kind_warnings = resolve_kind(kind, att.value)
            warnings.extend(kind_warnings)
            if kind != att.kind:
                trace.emit("attachment_kind", "첨부 종류를 내용으로 바로잡음", {
                    "claimed": att.kind, "resolved": kind, "chars": len(att.value),
                })
        payload = {"sourceType": att.sourceType.value, "value": att.value}
        if kind == "resume":
            # 이력서가 갱신되면 이전 이력서로 만든 파생 자산은 무효다.
            stage({"resume": payload, "profile": None, "analysis": None})
        elif kind == "resume_extra":
            # 추가 정보는 기존 이력서에 **덧붙인다** — 교체하면 몇 줄이 전체를 지운다.
            # 정보가 늘었으니 프로필·분석 파생 자산은 다시 만든다.
            existing = (session.get("resume") or {}).get("value", "")
            merged = (existing + "\n\n[추가 입력]\n" + att.value).strip()
            stage({
                "resume": {"sourceType": "text", "value": merged},
                "profile": None, "analysis": None,
            })
        else:
            stage({"job_posting": payload, "analysis": None})
        acks.append(_ATTACHMENT_ACK[kind] if kind == att.kind
                    else _ATTACHMENT_ACK_CORRECTED[kind])
        kinds.append(kind)
    return acks, kinds, warnings


def store_attachments(request: ChatRequest, session_id: str) -> list[str]:
    """write-back 루프 밖(관찰 UI 스텝퍼 등)에서 첨부만 즉시 저장할 때 쓰는 헬퍼.

    handle_chat 은 이걸 쓰지 않는다 — 턴 전체를 pending 으로 모아 한 번에 저장한다.
    """

    store = get_session_store()
    session = store.get(session_id)
    pending: dict[str, Any] = {}

    def _stage(updates: dict[str, Any]) -> None:
        pending.update(updates)
        session.update(updates)

    acks, _, _ = _apply_attachments(request, session, _stage)
    if pending:
        store.update(session_id, pending)
    return acks


def _visible_assets(session: dict) -> list[str]:
    """트레이스용 자산 목록 — _sessionId 같은 턴 내부 표식은 자산이 아니므로 뺀다."""

    return sorted(k for k in session if session.get(k) and not k.startswith("_"))


def _outcome_summary(outcome) -> dict:
    """재계획 입력용 실행 결과 요약 — 전문 대신 신호만 (경량 모델 입력)."""

    return {
        "reply": (outcome.reply or "")[:300],
        "dataKeys": sorted(outcome.data.keys()),
        "warningCodes": [str(w.get("code") or "") for w in outcome.warnings],
        "producedAssets": sorted(outcome.sessionUpdates.keys()),
        "askedUser": bool(outcome.followUpQuestions),
    }


def handle_chat(request: ChatRequest) -> ChatResponse:
    """대화 한 턴을 처리한다."""

    session_id = request.sessionId
    store = get_session_store()

    # 세션은 턴에 한 번 읽는다(작업 사본). 변경은 pending 에 쌓고 턴 끝에 한 번 저장한다.
    session = store.get(session_id)
    session["_sessionId"] = session_id
    pending: dict[str, Any] = {}
    # 에이전트 내부 캐시(ensure_profile)도 같은 pending 으로 들어오게 하는 통로.
    session["_stagedUpdates"] = pending

    def _stage(updates: dict[str, Any]) -> None:
        pending.update(updates)
        session.update(updates)

    def _finish(reply_text: str) -> None:
        """턴 종료 규약: user → assistant 순으로 이력 기록 후 **한 번에** 저장."""

        history = list(session.get("history") or [])
        for role, content in (("user", request.message), ("assistant", reply_text)):
            content = (content or "").strip()
            if content:
                history.append({"role": role, "content": content})
        pending["history"] = history[-HISTORY_MAX_ITEMS:]
        store.update(session_id, pending)

    acks, stored_kinds, attach_warnings = _apply_attachments(request, session, _stage)

    # 메시지 없이 첨부만 온 턴 — **멈추지 않는다.** 자료를 준 것 자체가 "이걸로 이어가 달라"는
    # 요청이므로, 발화를 합성해 플래너가 다음 단계를 고르게 한다. 첨부도 발화도 없으면
    # 플래너가 None 을 주고 대화형 에이전트가 턴을 받는다.
    message = (request.message or "").strip()
    if not message and acks:
        message = "방금 드린 자료로 이어서 진행해 주세요."

    request = request.model_copy(update={"message": message})

    # 발화 원문을 세션에 실어 대화형 에이전트(preference_intake 등)가 읽게 한다.
    _stage({"last_message": request.message})
    # 이번 턴에 무엇이 제출됐는지 — 플래너의 그라운딩 입력(자산이 아니라 사본에만 붙는 표식).
    # 이게 없으면 첨부만 온 턴의 합성 발화("자료로 이어서…")만 보고 플래너가 이력서 제출과
    # 공고 제출을 구분하지 못한다. 프론트의 kind 가 아니라 **바로잡힌 kind** 를 준다.
    session["_submittedThisTurn"] = stored_kinds

    # 1) 플래너 — LLM 이 발화·상태를 보고 에이전트를 직접 고른다(자율 추론).
    plan, warnings = plan_agents(request.message, session)
    warnings = attach_warnings + warnings

    ack = safe_ack(plan)   # 플래너의 이해 확인 문장 — 검증 통과 시 결정론 note 대신 쓴다
    if plan is not None:
        trace.emit("planner", "플래너(LLM)가 에이전트를 선택", {
            "selectedAgents": list(plan.agents), "confidence": plan.confidence,
            "target": plan.target, "ack": plan.ack,
            "sessionAssets": _visible_assets(session),
        })
        label = plan.agents[0] if plan.agents else "unclear"
        confidence = plan.confidence
        if not plan.agents or plan.confidence < CONFIDENCE_THRESHOLD:
            # 무엇을 원하는지 확신이 낮으면 대화로 받는다 — 기능 목록만 읽어주고 끝내지 않는다.
            dispatch = Dispatch((FALLBACK_AGENT,))
        else:
            # 2) 검증기(순수 코드) — 전제 자산 확인·생산자 삽입·실행 불가 제거.
            dispatch = validate_plan(plan.agents, session)
    else:
        # 플래너 불가(LLM 미설정·실패) — 대응표로 흐름을 대신 정하지 않는다. 대화형 에이전트가
        # 턴을 받아 사용자의 말에 답하고 필요한 자료를 요청한다.
        trace.emit("fallback", "플래너 불가 → 대화형 에이전트가 턴을 받음", {"agent": FALLBACK_AGENT})
        label, confidence = FALLBACK_AGENT, 0.0
        dispatch = Dispatch((FALLBACK_AGENT,))

    # 동의 게이트 — 무거운 생산자(fit_analysis)가 자동 삽입됐으면 실행하지 않고 먼저 묻는다.
    # 동의하면 다음 턴 플래너가 그 생산자를 명시적으로 고른다(플래너 프롬프트 규칙).
    if dispatch.ask:
        trace.emit("consent_gate", "무거운 파이프라인 자동 삽입 — 실행 전 동의 요청", {
            "ask": dispatch.ask, "plannedAgents": list(plan.agents) if plan else [],
        })
        final_reply = " ".join(r for r in acks + [dispatch.ask] if r).strip()
        _finish(final_reply)
        return ChatResponse(
            sessionId=session_id, reply=final_reply, intent=label,
            confidence=confidence, dispatched=[], results={},
            followUpQuestions=[{"field": "confirm_pipeline", "question": dispatch.ask}],
            warnings=warnings,
        )

    # 가시화 라벨은 **실제 실행 시퀀스**의 첫 에이전트 — 검증기가 생산자를 삽입/강등하면
    # 플래너 원안과 달라지므로, 프론트에 나가는 intent 는 dispatched 와 맞춘다 (§4 결함 수정).
    if dispatch.agents:
        label = dispatch.agents[0]

    trace.emit("dispatch", "검증기 확정 실행 시퀀스", {
        "agents": list(dispatch.agents), "note": dispatch.note,
    })

    # 4) 에이전트 실행 — 레지스트리에 있는 것만, 순서대로. 결과는 그대로 전달.
    # 대화형 에이전트 단독 실행이면 ack 를 생략한다 — 에이전트의 말이 이미 대화라
    # "이해했다" 문장이 겹치면 상담원 멘트 두 번 듣는 느낌이 된다.
    registry = get_agent_registry()
    solo_conversational = dispatch.agents in (("preference_intake",), ("career_chat",))
    # 검증기가 계획을 바꿨으면(전제 부족으로 강등·전제 삽입) **바뀐 이유**를 말한다.
    # 플래너의 ack 는 원래 계획을 설명하는 문장이라, 강등된 실행 앞에 붙으면 사실과 어긋난다
    # (예: 이력서가 없어 공고 정리만 하는데 "적합도 분석을 진행하겠습니다"로 시작).
    plan_changed = plan is not None and tuple(plan.agents) != tuple(dispatch.agents)
    lead = dispatch.note if (plan_changed and dispatch.note) else (ack or dispatch.note)
    replies: list[str] = acks + [("" if solo_conversational else lead)]
    dispatched: list[str] = []
    results: dict[str, dict] = {}
    follow_up: list[dict] = []

    # 실행 큐 — 재계획(replace)이 남은 시퀀스를 갈아끼울 수 있어 튜플 대신 큐로 돈다.
    queue: list[str] = list(dispatch.agents)
    # 재계획은 다중 에이전트 시퀀스에서만 — 단일 에이전트 턴의 지연을 늘리지 않는다.
    replan_budget = _MAX_REPLANS if len(queue) > 1 else 0

    while queue:
        name = queue.pop(0)
        spec = registry.get(name)
        if spec is None:
            replies.append(
                f"'{name}' 기능은 아직 준비 중이에요. 다른 기능(적합도 분석·공고 추천·이력서 진단·면접 준비)을 이용해 주세요."
            )
            warnings.append({"code": "agent_not_implemented",
                             "message": f"orchestrator: 미구현 에이전트 dispatch — {name}"})
            break

        trace.emit("agent_start", f"{name} 실행 시작", {
            "agent": name, "description": spec.description,
            "preconditions": list(spec.preconditions),
            "sessionAssets": _visible_assets(session),
        })
        outcome = spec.entry(session)
        dispatched.append(name)
        results[name] = outcome.data
        warnings.extend(outcome.warnings)
        follow_up.extend(outcome.followUpQuestions)
        trace.emit("agent_end", f"{name} 실행 종료", {
            "agent": name, "reply": outcome.reply, "data": outcome.data,
            "warnings": outcome.warnings,
            "followUpQuestions": outcome.followUpQuestions,
            "sessionUpdates": sorted(outcome.sessionUpdates.keys()),
        })
        if outcome.sessionUpdates:
            _stage(outcome.sessionUpdates)
        if outcome.reply:
            replies.append(outcome.reply)

        # 파이프 중간에 추가 정보가 필요해지면(need_more_info) 뒤 에이전트를 실행하지 않는다.
        if outcome.followUpQuestions:
            break

        # 5) 경량 재계획 — 방금 결과를 보고 남은 시퀀스를 이어갈지 다시 정한다 (§2-1).
        # LLM 미설정·실패면 None → 예정대로 계속(기존 동작 그대로).
        if queue and replan_budget > 0:
            replan_budget -= 1
            decision = replan_after(name, _outcome_summary(outcome), list(queue), session)
            if decision is None or decision.action == "continue":
                continue
            trace.emit("replan", f"재계획: {decision.action}", {
                "afterAgent": name, "action": decision.action,
                "agents": list(decision.agents), "reason": decision.reason,
            })
            if decision.action == "stop":
                break
            # replace — 교체 시퀀스도 검증기를 다시 통과시킨다(전제·중복·동의 게이트 동일 적용).
            replacement = validate_plan(decision.agents, session)
            if replacement.ask or not replacement.agents:
                break
            queue = [n for n in replacement.agents if n not in dispatched]

    final_reply = " ".join(r for r in replies if r).strip()
    _finish(final_reply)

    return ChatResponse(
        sessionId=session_id,
        reply=final_reply,
        intent=label,
        confidence=confidence,
        dispatched=dispatched,
        results=results,
        followUpQuestions=follow_up,
        warnings=warnings,
    )
