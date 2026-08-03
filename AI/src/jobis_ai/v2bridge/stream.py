"""trace 이벤트 → 분석 진행 스트림 이벤트 (`docs/분석-진행-스트리밍-설계.md` §4).

백엔드·프론트는 이미 완성돼 있다. 우리가 보내는 JSON 이 **가공 없이** 프론트까지 간다
(`AnalysisWorker.recordProgress` → `progressEvents` → `AnalysisProgressWheel.vue`).
그래서 이 모듈은 새 판단을 만들지 않고 **옮겨 적기만** 한다 — 계측은 `trace.py` 가 이미
다 갖고 있다.

지켜야 하는 불변식(백엔드가 검증하고, 어기면 그 job 이 FAILED 로 끝난다):
  · `runId == request.analysisJobId`
  · `sequence` 1부터 엄격 증가·중복 없음 (단일 카운터로만 올린다)
  · 첫 줄은 항상 `RUN_STARTED`, 마지막 줄은 항상 `RESULT` **또는** `ERROR`
  · `RESULT` 는 정확히 1건

**2단 발행**(설계 결정 ③): 플래너가 돌기 전에는 어떤 에이전트가 실행될지 모른다. 그래서
백본 계획을 먼저 내고, dispatch 가 확정되면 에이전트별 스테이지로 `RUN_STARTED` 를 다시
낸다. 프론트가 "마지막 RUN_STARTED"를 쓰기 때문에 성립한다(설계 §1-④).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from jobis_ai.v2bridge.models import (
    AnalysisResponse,
    AnalysisStageDefinition,
    AnalysisStageUpdate,
    AnalysisStreamEvent,
)

# 프론트 아이콘도 6종 순환이라 index 가 맞물린다(설계 결정 ⑤).
_PALETTE = ("#1cb0f6", "#ce82ff", "#ff9600", "#2b70c9", "#58cc02", "#ffc800")

# 백본 — 플래너 전에도 화면에 보일 뼈대. 백엔드 워커가 쓰는 stage 값
# (CONTEXT·AI_ANALYSIS·VALIDATING·SHARED_REUSE)과 겹치지 않는 id 를 쓴다.
_BACKBONE: tuple[tuple[str, str, str, str], ...] = (
    ("CONTEXT_ASSEMBLY", "맥락 조립", "대화 오케스트레이터",
     "공고와 커리어 근거를 분석 입력으로 조립하고 있어요."),
    ("PLANNING", "실행 계획", "플래너", "어떤 담당을 쓸지 고르고 있어요."),
    ("CONTRACT_VALIDATION", "결과 검증", "결정론 검증기",
     "스키마와 참조 무결성을 코드로 확인하고 있어요."),
    ("RESULT_ASSEMBLY", "결과 조립", "경로 조립기", "지도 생성에 쓸 데이터를 준비하고 있어요."),
)

_MAX_STAGES = 12
_LABEL_MAX, _ROLE_MAX, _MESSAGE_MAX, _STAGE_MESSAGE_MAX = 80, 120, 500, 1_000

# 한 분석이 낼 이벤트 예산(설계 결정 ⑥). **이벤트 1건 = 백엔드 DB 쓰기 1건**이므로
# (`AnalysisWorker.recordProgress`) 상한이 없으면 긴 턴이 DB 를 두드린다. 넘치면
# 진행 갱신만 멈추고 계획·결과·오류는 계속 낸다 — 화면이 멈추는 것보다 안 보이는 게 낫다.
_EVENT_BUDGET = 60


def agent_stage_id(agent: str) -> str:
    """`fit_analysis` → `AGENT_FIT_ANALYSIS`. id 패턴을 만족하고 백본과 안 겹친다."""

    cleaned = "".join(ch if ch.isalnum() else "_" for ch in str(agent or "")).strip("_")
    if not cleaned:
        # 이름 없는 담당으로 스테이지를 만들면 화면에 "AGENT_" 라는 빈 칸이 생긴다.
        return "AGENT_UNKNOWN"
    return f"AGENT_{cleaned.upper()}"[:80]


def _clip(text: Any, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit]


class StreamBuilder:
    """단일 sequence 카운터로 이벤트를 찍어 내는 조립기. **판단하지 않는다.**

    호출부(`service.analyze_events`)가 trace 이벤트를 넘기면 해당하는 스트림 이벤트를
    돌려주고, 해당 없으면 None 을 돌려준다. 상태는 sequence 와 "어떤 스테이지를 이미
    선언했는가" 뿐이다.
    """

    def __init__(self, run_id: UUID):
        self._run_id = run_id
        self._sequence = 0
        self._declared: list[AnalysisStageDefinition] = []
        self._known_ids: set[str] = set()
        self._suppressed = 0

    @property
    def suppressed(self) -> int:
        """예산을 넘겨 못 보낸 진행 갱신 수. 호출부가 로그로 남긴다."""

        return self._suppressed

    # -- 저수준 -------------------------------------------------------------
    def _event(self, type_: str, **payload: Any) -> AnalysisStreamEvent:
        self._sequence += 1
        return AnalysisStreamEvent(
            type=type_, run_id=self._run_id, sequence=self._sequence,
            occurred_at=datetime.now(UTC), **payload,
        )

    def _stage(self, stage_id: str, status: str, message: str) -> AnalysisStreamEvent | None:
        """선언되지 않은 스테이지로는 갱신을 보내지 않는다 — 프론트가 무시할 이벤트다."""

        if stage_id not in self._known_ids:
            return None
        if self._sequence >= _EVENT_BUDGET:
            # 예산 소진 — 진행 갱신은 멈춘다. 계획(RUN_STARTED)·결과·오류는 예산과 무관하게
            # 계속 나간다(그게 없으면 화면이 영영 완료로 안 바뀐다). **삼키지 않는다**:
            # 몇 건을 못 보냈는지 마지막에 세어 로그로 남긴다(§2-6).
            self._suppressed += 1
            return None
        return self._event("STAGE_UPDATED", stage=AnalysisStageUpdate(
            id=stage_id, status=status, message=_clip(message, _STAGE_MESSAGE_MAX)))

    # -- 계획 ---------------------------------------------------------------
    def backbone(self) -> AnalysisStreamEvent:
        """첫 줄. 플래너 결과를 모르는 시점의 뼈대."""

        self._declared = [
            AnalysisStageDefinition(
                id=sid, label=_clip(label, _LABEL_MAX), role=_clip(role, _ROLE_MAX),
                message=_clip(msg, _MESSAGE_MAX), color=_PALETTE[i % len(_PALETTE)])
            for i, (sid, label, role, msg) in enumerate(_BACKBONE)
        ]
        self._known_ids = {s.id for s in self._declared}
        return self._event("RUN_STARTED", stages=list(self._declared))

    def replan(self, agents: list[str]) -> AnalysisStreamEvent | None:
        """dispatch 확정 → 에이전트별 스테이지를 끼운 완전한 계획으로 재발행.

        상한 12를 코드로 지킨다(설계 결정 ④): 앞에서부터 채우고 **마지막 한 칸은
        `RESULT_ASSEMBLY` 로 남긴다.** 잘린 담당은 그 칸 message 로 표기한다 — 계획을
        잘랐다는 사실을 삼키지 않는다(§2-6).
        """

        from jobis_ai.orchestrator.router import agent_label

        names = [a for a in (agents or []) if a]
        if not names:
            return None
        head = [s for s in self._declared if s.id in ("CONTEXT_ASSEMBLY", "PLANNING")]
        tail = [s for s in self._declared if s.id in ("CONTRACT_VALIDATION", "RESULT_ASSEMBLY")]
        room = _MAX_STAGES - len(head) - len(tail)
        shown, dropped = names[:room], names[room:]

        # 눈썹(label)은 **무엇을 하는 단계인가**, 제목(role)은 **누가 하는가**.
        # 둘에 같은 문자열을 넣으면 원 위에 같은 글자가 두 번 뜬다 — 백본이 이미
        # (맥락 조립 / 대화 오케스트레이터)로 그 규약을 쓰고 있다.
        middle = [
            AnalysisStageDefinition(
                id=agent_stage_id(name),
                label=_clip(agent_label(name), _LABEL_MAX),
                role=_clip(f"{agent_label(name)} 담당", _ROLE_MAX),
                message=_clip(f"{agent_label(name)} 을(를) 진행합니다.", _MESSAGE_MAX),
                color=_PALETTE[(len(head) + i) % len(_PALETTE)])
            for i, name in enumerate(shown)
        ]
        if dropped:
            tail[-1] = tail[-1].model_copy(update={"message": _clip(
                f"화면에 담지 못한 담당 {len(dropped)}건: "
                + ", ".join(agent_label(n) for n in dropped), _MESSAGE_MAX)})
        self._declared = head + middle + tail
        self._known_ids = {s.id for s in self._declared}
        return self._event("RUN_STARTED", stages=list(self._declared))

    # -- trace → 이벤트 ------------------------------------------------------
    def from_trace(self, ev: dict[str, Any]) -> list[AnalysisStreamEvent]:
        """trace 이벤트 하나 → 스트림 이벤트 0~2건 (설계 §4 매핑표)."""

        kind = str(ev.get("kind") or "")
        detail = ev.get("detail") or {}
        summary = str(ev.get("summary") or "")
        out: list[AnalysisStreamEvent] = []

        if kind == "planner":
            agents = list(detail.get("selectedAgents") or detail.get("agents") or [])
            confidence = detail.get("confidence")
            text = "선택: " + (", ".join(agents) if agents else "없음")
            if isinstance(confidence, (int, float)):
                text += f" · 확신 {float(confidence):.2f}"
            out.append(self._stage("PLANNING", "RUNNING", text))
        elif kind == "fallback":
            out.append(self._stage("PLANNING", "RUNNING",
                                   "플래너 불가 — 대화형 담당이 턴을 받았어요."))
        elif kind == "dispatch":
            agents = list(detail.get("agents") or detail.get("queue") or [])
            replanned = self.replan(agents)
            if replanned is not None:
                out.append(replanned)
            out.append(self._stage("PLANNING", "COMPLETED", "실행할 담당을 확정했어요."))
        elif kind in ("url_intake", "resume_intake"):
            out.append(self._stage("CONTEXT_ASSEMBLY", "RUNNING", f"자료 접수 — {summary}"))
        elif kind == "consent_gate":
            out.append(self._stage(agent_stage_id(detail.get("agent", "")), "WAITING",
                                   f"실행 전 확인: {detail.get('ask') or summary}"))
        elif kind == "agent_start":
            out.append(self._stage(agent_stage_id(detail.get("agent", "")), "RUNNING",
                                   summary or "실행 중"))
        elif kind == "agent_step":
            out.append(self._agent_step(detail, summary))
        elif kind in ("delegate", "delegate_refused"):
            out.append(self._stage(agent_stage_id(detail.get("from", "")), "RUNNING", summary))
        elif kind == "observe":
            if str(detail.get("rule") or "none") != "none":
                out.append(self._stage(agent_stage_id(detail.get("afterAgent", "")),
                                       "RUNNING", f"실행 후 재점검: {detail.get('reason') or ''}"))
        elif kind == "agent_end":
            out.append(self._stage(agent_stage_id(detail.get("agent", "")), "COMPLETED",
                                   summary or "완료"))
        elif kind == "agent_crashed":
            out.append(self._stage(agent_stage_id(detail.get("agent", "")), "FAILED", summary))

        return [e for e in out if e is not None]

    def _agent_step(self, detail: dict, summary: str) -> AnalysisStreamEvent | None:
        stage_id = agent_stage_id(detail.get("agent", ""))
        action = str(detail.get("action") or "")
        if action == "use_tool":
            # 설계 결정 ②: 툴 호출은 여기로 흐른다. **에이전트가 부르지 않은 툴 이름을
            # 만들지 않는다** — 이름·인자·관찰 모두 trace 기록 그대로다.
            tool = str(detail.get("tool") or "")
            arg = _clip(detail.get("arg"), 40)
            observation = _clip(detail.get("observation"), 80)
            called = f"도구 {tool}" + (f"({arg})" if arg else "") + " 호출"
            text = called + (f" — {observation}" if observation else "")
        elif action == "reply":
            text = f"스텝 {detail.get('step') or ''} · 답변 작성".strip()
        elif action == "limit":
            text = "도구 사용 상한 도달 — 지금까지 관찰로 답을 만듭니다."
        elif action == "unavailable":
            text = "중단(판단 불가)"
        else:
            text = summary
        return self._stage(stage_id, "RUNNING", text)

    # -- 종결 ---------------------------------------------------------------
    def validated(self) -> AnalysisStreamEvent | None:
        return self._stage("CONTRACT_VALIDATION", "COMPLETED", "스키마·참조 무결성을 확인했어요.")

    def assembled(self) -> AnalysisStreamEvent | None:
        return self._stage("RESULT_ASSEMBLY", "COMPLETED", "지도에 쓸 데이터를 준비했어요.")

    def result(self, response: AnalysisResponse) -> AnalysisStreamEvent:
        return self._event("RESULT", result=response)

    def error(self, code: str, message: str) -> AnalysisStreamEvent:
        """스트림이 시작된 뒤의 실패는 HTTP 상태로 못 알린다 — 반드시 이 이벤트로."""

        return self._event("ERROR", error_code=_clip(code, 80) or "AI_PROVIDER_UNAVAILABLE",
                           error_message=_clip(message, 2_000))
