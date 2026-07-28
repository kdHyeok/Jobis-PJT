"""단계 실행 러너 (관찰 UI 전용) — 버튼 한 번에 한 분기씩 실행한다.

전체 파이프라인을 한 번에 돌리는 대신:
  ① 시작: 플래너(또는 폴백) + 검증기까지만 실행 → 실행 계획을 보여주고 멈춤
  ② 다음: 에이전트 하나 실행. 단 fit_analysis 는 그래프 stream 제너레이터를 붙잡아 두고
     **판정 엔진 노드를 한 번에 하나씩** 전진시킨다
  ③ 완료: 최종 응답 조립 + SQLite 저장

운영 코드가 아니다 — 오케스트레이터의 실행 루프(chat.handle_chat)를 관찰 목적으로
단계별로 풀어놓은 것. 판단 로직은 전부 기존 모듈(planner/router/agents/graph)을 재사용한다.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any

from jobis_ai import trace
from jobis_ai.agents import get_agent_registry
from jobis_ai.agents.fit_analysis import DEFAULT_HOURS, DEFAULT_WEEKS
from jobis_ai.contracts.api import AnalyzeOptions, AnalyzeRequest, ChatRequest, JobPostingInput
from jobis_ai.orchestrator.chat import store_attachments
from jobis_ai.orchestrator.planner import CONFIDENCE_THRESHOLD, plan_agents, safe_ack
from jobis_ai.orchestrator.router import FALLBACK_AGENT, Dispatch, validate_plan
from jobis_ai.orchestrator.session import append_history, get_session_store
from jobis_ai.service import _get_app, request_to_state


class StepRun:
    """진행 중인 단계 실행 1건의 상태."""

    def __init__(self, request: ChatRequest) -> None:
        self.run_id = str(uuid.uuid4())
        self.session_id = request.sessionId
        self.message = request.message
        self.events: list[dict] = []
        self._seq = 0
        self.replies: list[str] = []
        self.results: dict[str, dict] = {}
        self.warnings: list[dict] = []
        self.follow_up: list[dict] = []
        self.pending: list[str] = []          # 남은 에이전트 이름들
        self.done = False
        self.label = ""                       # 방금 실행한 단계 설명
        self.intent_label = "unclear"
        self.confidence = 0.0
        # fit_analysis 노드 스테핑 상태
        self._graph_gen = None
        self._graph_final: dict = {}
        self._request = request
        self._history_recorded = False

    # -- 트레이스 수집: 단계마다 레코더를 열고 이벤트를 이어 붙인다 -----------
    def _collect(self, fn):
        with trace.recording() as rec:
            result = fn()
        step_events = []
        for e in rec.events:
            self._seq += 1
            e["seq"] = self._seq
            step_events.append(e)
        self.events.extend(step_events)
        return result, step_events

    # -- ① 시작: 첨부 저장 + 플래너/폴백 + 검증기 ------------------------------
    def start(self) -> dict:
        acks = store_attachments(self._request, self.session_id)
        if acks:
            self.replies.extend(acks)
        # 발화 원문을 세션에 실어 대화형 에이전트가 읽게 한다 (chat.handle_chat 과 동일).
        get_session_store().update(self.session_id, {"last_message": self.message})
        session = get_session_store().get(self.session_id)

        def _plan() -> Dispatch:
            plan, warnings = plan_agents(self.message, session)
            self.warnings.extend(warnings)
            self._ack = safe_ack(plan)   # 이해 확인 문장 — 검증 통과 시 note 대신
            if plan is not None:
                self.intent_label = plan.agents[0] if plan.agents else "unclear"
                self.confidence = plan.confidence
                if not plan.agents or plan.confidence < CONFIDENCE_THRESHOLD:
                    dispatch = Dispatch((FALLBACK_AGENT,))
                else:
                    dispatch = validate_plan(plan.agents, session)
            else:
                # 플래너 불가 — 대응표로 흐름을 대신 정하지 않고 대화형 에이전트가 턴을 받는다
                # (chat.handle_chat 과 동일).
                self.intent_label, self.confidence = FALLBACK_AGENT, 0.0
                dispatch = Dispatch((FALLBACK_AGENT,))
            trace.emit("dispatch", "검증기 확정 실행 시퀀스", {
                "agents": list(dispatch.agents), "note": dispatch.note,
            })
            return dispatch

        dispatch, step_events = self._collect(_plan)
        self.label = "플래너 + 검증기 (실행 계획 확정)"

        note = getattr(self, "_ack", "") or dispatch.note
        if note:
            self.replies.append(note)
        self.pending = list(dispatch.agents)
        return self._snapshot(step_events)

    # -- ② 다음: 한 분기 실행 ---------------------------------------------------
    def next_step(self) -> dict:
        if self.done:
            return self._snapshot([])

        name = self.pending[0]
        if name == "fit_analysis":
            return self._step_fit_analysis()

        registry = get_agent_registry()
        spec = registry.get(name)
        session = get_session_store().get(self.session_id)

        if spec is None:
            self.replies.append(f"'{name}' 기능은 아직 준비 중이에요.")
            self.pending.pop(0)
            self.label = f"{name} — 미구현, 건너뜀"
            if not self.pending:
                self.done = True
            return self._snapshot([])

        def _run_agent():
            trace.emit("agent_start", f"{name} 실행 시작", {
                "agent": name, "description": spec.description,
                "preconditions": list(spec.preconditions),
                "sessionAssets": sorted(k for k in session if session.get(k)),
            })
            outcome = spec.entry(session)
            trace.emit("agent_end", f"{name} 실행 종료", {
                "agent": name, "reply": outcome.reply, "data": outcome.data,
                "warnings": outcome.warnings,
                "followUpQuestions": outcome.followUpQuestions,
                "sessionUpdates": sorted(outcome.sessionUpdates.keys()),
            })
            return outcome

        outcome, step_events = self._collect(_run_agent)
        self._absorb_outcome(name, outcome)
        self.label = f"에이전트 실행: {name}"
        return self._snapshot(step_events)

    # -- fit_analysis: 그래프 노드를 한 번에 하나씩 -----------------------------
    def _step_fit_analysis(self) -> dict:
        session = get_session_store().get(self.session_id)

        if self._graph_gen is None:
            request = AnalyzeRequest(
                userId=int(session.get("userId") or 0),
                jobPostingInput=JobPostingInput(**session["job_posting"]),
                preparationPeriodWeeks=int(session.get("preparationPeriodWeeks") or DEFAULT_WEEKS),
                availableHoursPerWeek=int(session.get("availableHoursPerWeek") or DEFAULT_HOURS),
                options=AnalyzeOptions(includeAlternatives=True),
            )
            state = request_to_state(request, str(uuid.uuid4()))
            if session.get("resume"):
                state["resumeInput"] = session["resume"]
            self._graph_gen = _get_app().stream(state, stream_mode=["updates", "values"])

        def _advance():
            """updates 청크(=노드 1개 완료) 하나를 소비할 때까지 전진. 끝나면 None."""
            for mode, chunk in self._graph_gen:
                if mode == "values":
                    self._graph_final = chunk
                    continue
                for node_name, update in (chunk or {}).items():
                    trace.emit("node", f"판정 엔진 노드: {node_name}", {
                        "node": node_name,
                        "status": (update or {}).get("status"),
                        "update": update or {},
                    })
                    return node_name
            return None

        node_name, step_events = self._collect(_advance)

        if node_name is not None:
            self.label = f"판정 엔진 노드: {node_name}"
            return self._snapshot(step_events)

        # 제너레이터 소진 — fit_analysis 마무리 (agents/fit_analysis.run 과 동일 규칙)
        from jobis_ai.contracts.api import AnalyzeResponse

        response = AnalyzeResponse(**(self._graph_final.get("analysisResult") or {}))
        result = response.model_dump()
        if response.status == "need_more_info":
            reply = "분석에 필요한 정보가 부족합니다. 아래 질문에 답해 주시면 이어서 분석할게요."
        else:
            grade = response.fitGrade or "판정불가"
            reply = response.summary or f"적합도 판정 결과: {grade} 등급입니다."
            if not session.get("preparationPeriodWeeks"):
                reply += f" (준비 기간은 {DEFAULT_WEEKS}주·주 {DEFAULT_HOURS}시간을 가정했습니다.)"
        session_updates: dict = {}
        if response.status == "completed":
            session_updates["analysis"] = result
            if response.roadmap:
                session_updates["roadmap"] = result["roadmap"]

        from jobis_ai.agents import AgentResult

        outcome = AgentResult(
            reply=reply, data=result, warnings=list(response.warnings),
            followUpQuestions=list(response.followUpQuestions),
            sessionUpdates=session_updates,
        )
        self._graph_gen = None
        self._absorb_outcome("fit_analysis", outcome)
        self.label = "fit_analysis 완료 (결과를 세션에 승격)"
        return self._snapshot(step_events)

    # -- 공통: 에이전트 결과 반영 ------------------------------------------------
    def _absorb_outcome(self, name: str, outcome) -> None:
        self.pending.pop(0)
        self.results[name] = outcome.data
        self.warnings.extend(outcome.warnings)
        self.follow_up.extend(outcome.followUpQuestions)
        if outcome.sessionUpdates:
            get_session_store().update(self.session_id, outcome.sessionUpdates)
        if outcome.reply:
            self.replies.append(outcome.reply)
        # 추가 정보가 필요해지면 뒤 에이전트를 실행하지 않는다 (chat.handle_chat 과 동일)
        if outcome.followUpQuestions:
            self.pending.clear()
        if not self.pending:
            self.done = True

    # -- 응답 스냅샷 --------------------------------------------------------------
    def next_label(self) -> str:
        if self.done:
            return ""
        name = self.pending[0]
        if name == "fit_analysis" and self._graph_gen is not None:
            return "판정 엔진 — 다음 노드 실행"
        if name == "fit_analysis":
            return "fit_analysis 시작 (판정 엔진 노드 단위 진행)"
        return f"에이전트 실행: {name}"

    def _record_history(self) -> None:
        """완료 시 1회만 대화 이력 기록 (chat.handle_chat 의 턴 종료 규약과 동일)."""

        if self._history_recorded:
            return
        self._history_recorded = True
        append_history(self.session_id, "user", self.message)
        append_history(self.session_id, "assistant",
                       " ".join(r for r in self.replies if r).strip())

    def _snapshot(self, step_events: list[dict]) -> dict:
        if self.done:
            self._record_history()
        return {
            "runId": self.run_id,
            "sessionId": self.session_id,
            "label": self.label,
            "events": step_events,
            "reply": " ".join(r for r in self.replies if r).strip(),
            "done": self.done,
            "nextLabel": self.next_label(),
            "intent": self.intent_label,
            "confidence": self.confidence,
            "dispatchedPending": list(self.pending),
            "followUpQuestions": self.follow_up,
        }


# --- 러너 레지스트리 (프로세스 메모리) -------------------------------------------
_RUNS: dict[str, StepRun] = {}
_LOCK = threading.Lock()


def start_step_run(request: ChatRequest) -> dict:
    run = StepRun(request)
    snapshot = run.start()
    with _LOCK:
        _RUNS[run.run_id] = run
    return snapshot


def advance_step_run(run_id: str) -> dict | None:
    with _LOCK:
        run = _RUNS.get(run_id)
    if run is None:
        return None
    return run.next_step()


def get_step_run(run_id: str) -> StepRun | None:
    with _LOCK:
        return _RUNS.get(run_id)
