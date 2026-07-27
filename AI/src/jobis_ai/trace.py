"""실행 트레이스 레코더 — 관찰용 계측 (프로토타입 UI 가 사용).

활성 레코더가 없으면 emit 은 전부 no-op 이라 운영 경로의 동작·성능에 영향이 없다.
판단하지 않고 기록만 한다 — 트레이스는 하네스가 아니라 창문이다.

    with trace.recording() as rec:
        handle_chat(request)
    rec.events  # [{seq, elapsedMs, kind, label, detail}, ...]

kind 종류:
    planner        플래너 LLM 의 에이전트 선택 (자율 판단이 무엇을 골랐는지)
    fallback       플래너 불가(LLM 미설정·실패) → 대화형 에이전트가 턴을 받음
    dispatch       검증기 통과 후 최종 실행 시퀀스
    agent_start    전담 에이전트 실행 시작
    agent_end      전담 에이전트 실행 종료 (산출물·경고·세션 갱신 포함)
    node           판정 엔진(graph) 노드 1개 완료 — 노드가 갱신한 상태 키·값
"""

from __future__ import annotations

import contextvars
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator

_current: contextvars.ContextVar["TraceRecorder | None"] = contextvars.ContextVar(
    "jobis_trace_recorder", default=None
)


class TraceRecorder:
    """이벤트 누적기. 이벤트는 JSON 직렬화 가능한 dict 로만 담는다.

    sink 를 주면 이벤트가 생길 때마다 그대로 넘긴다 — 실행이 끝난 뒤 events 를 읽는 관찰 UI 와 달리,
    진행을 **실시간으로** 중계해야 하는 쪽(웹 브릿지의 PROGRESS 신호)이 쓴다.
    sink 에서 난 예외는 무시한다 — 관찰이 실행을 망가뜨리지 않게.
    """

    def __init__(self, sink: "Callable[[dict[str, Any]], None] | None" = None) -> None:
        self.events: list[dict[str, Any]] = []
        self._t0 = time.perf_counter()
        self._seq = 0
        self._sink = sink

    def emit(self, kind: str, label: str, detail: dict[str, Any] | None = None) -> None:
        self._seq += 1
        event = {
            "seq": self._seq,
            "elapsedMs": round((time.perf_counter() - self._t0) * 1000),
            "kind": kind,
            "label": label,
            "detail": detail or {},
        }
        self.events.append(event)
        if self._sink is not None:
            try:
                self._sink(event)
            except Exception:   # noqa: BLE001 — 관찰이 실행을 막지 않는다
                pass


def emit(kind: str, label: str, detail: dict[str, Any] | None = None) -> None:
    """활성 레코더가 있으면 기록, 없으면 no-op."""

    rec = _current.get()
    if rec is not None:
        rec.emit(kind, label, detail)


def active() -> bool:
    return _current.get() is not None


@contextmanager
def recording(sink: "Callable[[dict[str, Any]], None] | None" = None) -> Iterator[TraceRecorder]:
    """이 블록 안의 emit 을 모두 담는 레코더를 활성화한다.

    sink 를 주면 이벤트를 실시간으로도 흘려보낸다(웹 브릿지의 진행 중계용).
    """

    rec = TraceRecorder(sink)
    token = _current.set(rec)
    try:
        yield rec
    finally:
        _current.reset(token)
