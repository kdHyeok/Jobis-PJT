"""실행 트레이스 레코더 — 관찰용 계측 (프로토타입 UI 가 사용).

활성 레코더가 없으면 emit 은 전부 no-op 이라 운영 경로의 동작·성능에 영향이 없다.
판단하지 않고 기록만 한다 — 트레이스는 하네스가 아니라 창문이다.

    with trace.recording() as rec:
        handle_chat(request)
    rec.events  # [{seq, elapsedMs, kind, label, detail}, ...]

kind 종류:
    planner        플래너 LLM 의 에이전트 선택 (자율 판단이 무엇을 골랐는지)
    fallback       플래너 불가(LLM 미설정·실패) → 대화형 에이전트가 턴을 받음
    dispatch       검증기 통과 후 최종 실행 시퀀스 (플래너 원안과 다를 수 있다 — 생산자 자동 삽입)
    agent_start    전담 에이전트 실행 시작
    agent_end      전담 에이전트 실행 종료 (산출물·경고·세션 갱신 포함)
    observe        에이전트 하나가 끝난 뒤의 재선택 판단 (ReAct 관찰 루프).
                   action = continue | finish | call | skipped | unavailable.
                   **아무것도 바꾸지 않은 continue 도 남긴다** — 남기지 않으면 "결과를 보고
                   다시 정했다"를 사후에 증명할 수 없다(그게 이 구조의 핵심 주장이다).
    node           판정 엔진(graph) 노드 1개 완료 — 노드가 갱신한 상태 키·값
    delegate           에이전트 간 직접 위임이 **성공**했다 (target·상대 답·데이터 키)
    delegate_refused   위임이 가드에 걸렸다 (target·reason 코드).
                       **거부를 남기지 않으면 hand-off 성공률의 분모가 없다** — 성공만 세면
                       "시도했는데 안 됐다"가 관찰 문자열로 사라진다(평가 리포트 §1-1).
    llm_usage      턴 종료 시 LLM 사용량 요약(콜·토큰·재시도) — 집계 자체는 llm_usage.py
                   (trace 는 소멸하므로 세는 곳이 아니다), 이 이벤트는 관찰 UI 용 사본이다
    token          표현 계층 스트리밍 델타 — sink 로만 흘리고 events 에는 쌓지 않는다
"""

from __future__ import annotations

import contextvars
import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Callable, Iterator

_current: contextvars.ContextVar["TraceRecorder | None"] = contextvars.ContextVar(
    "jobis_trace_recorder", default=None
)

# 토큰 델타 음소거 — 에이전트를 병렬로 돌리는 구간에서 켠다. 프론트는 델타를 **한 버퍼에**
# 이어 붙이므로(ask.html: streamed += ev.text) 두 에이전트의 토큰이 동시에 흐르면 화면에
# 섞인 글이 보인다. 진행 이벤트(agent_start/node)는 그대로 흘린다 — 끄는 것은 토큰뿐이다.
_mute_tokens: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "jobis_trace_mute_tokens", default=False
)


@contextmanager
def muted_tokens() -> Iterator[None]:
    """이 블록 안에서 생긴 token 델타는 중계하지 않는다(최종 답변은 그대로 나간다)."""

    token = _mute_tokens.set(True)
    try:
        yield
    finally:
        _mute_tokens.reset(token)


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
        # 병렬 실행 구간에서는 여러 스레드가 같은 레코더에 쓴다 — seq 가 겹치지 않게 잠근다.
        self._lock = threading.Lock()
        # 중첩 recording 시 바깥 레코더. 안쪽이 이벤트를 독점하면 바깥 sink(진행 스트리밍)가
        # 눈이 멀기 때문에, 이벤트를 부모에게도 전달한다 (recording() 이 설정).
        self._parent: "TraceRecorder | None" = None

    def emit(self, kind: str, label: str, detail: dict[str, Any] | None = None) -> None:
        with self._lock:
            self._seq += 1
            event = {
                "seq": self._seq,
                "elapsedMs": round((time.perf_counter() - self._t0) * 1000),
                "kind": kind,
                "label": label,
                "detail": detail or {},
            }
        # token(스트리밍 델타)은 실시간 중계 전용 — 이벤트 목록에 쌓으면 답변 하나에
        # 수십~수백 건이 남아 관찰 UI 를 덮는다. sink 로만 흘리고 기록하지 않는다.
        if kind != "token":
            self.events.append(event)
        if self._sink is not None:
            try:
                self._sink(event)
            except Exception:   # noqa: BLE001 — 관찰이 실행을 막지 않는다
                pass
        if self._parent is not None:
            self._parent.emit(kind, label, detail)


def emit(kind: str, label: str, detail: dict[str, Any] | None = None) -> None:
    """활성 레코더가 있으면 기록, 없으면 no-op."""

    if kind == "token" and _mute_tokens.get():
        return
    rec = _current.get()
    if rec is not None:
        rec.emit(kind, label, detail)


def active() -> bool:
    return _current.get() is not None


def _persist(rec: TraceRecorder) -> None:
    """턴 하나의 이벤트를 JSON 파일로 남긴다 — 프로토타입 2.0.0 의 런별 trace 이식(D127).

    opt-in: 환경변수 `JOBIS_TRACE_DIR` 이 설정된 경우에만 쓴다. trace 는 턴이 끝나면
    소멸하고 SSE 중계도 화면을 닫으면 사라진다 — "어제 그 턴에 왜 이 에이전트가 돌았나"에
    답할 물증이 파일뿐이다. 쓰기 실패는 삼킨다(관찰이 실행을 막지 않는다 — sink 와 같은 규약).
    """

    directory = (os.getenv("JOBIS_TRACE_DIR") or "").strip()
    if not directory or not rec.events:
        return
    try:
        os.makedirs(directory, exist_ok=True)
        name = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}.json"
        with open(os.path.join(directory, name), "w", encoding="utf-8") as f:
            json.dump({"events": rec.events}, f, ensure_ascii=False, indent=2)
    except Exception:   # noqa: BLE001
        pass


@contextmanager
def recording(sink: "Callable[[dict[str, Any]], None] | None" = None) -> Iterator[TraceRecorder]:
    """이 블록 안의 emit 을 모두 담는 레코더를 활성화한다.

    sink 를 주면 이벤트를 실시간으로도 흘려보낸다(웹 브릿지의 진행 중계용).
    """

    rec = TraceRecorder(sink)
    rec._parent = _current.get()   # 중첩이면 바깥 레코더로도 이벤트를 흘린다
    token = _current.set(rec)
    try:
        yield rec
    finally:
        _current.reset(token)
        if rec._parent is None:    # 중첩 레코더는 부모가 이벤트를 다 받았다 — 한 번만 쓴다
            _persist(rec)
