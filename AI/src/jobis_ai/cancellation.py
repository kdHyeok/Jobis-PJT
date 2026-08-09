"""실행 중인 AI 요청을 협력적으로 중단하는 요청 범위 컨텍스트.

HTTP 취소 엔드포인트는 요청 ID에 연결된 Event를 세운다. 오케스트레이터가 만드는 병렬
스레드는 이미 ``contextvars.copy_context()`` 로 부모 컨텍스트를 복사하므로, LLM 호출
경계에서도 같은 취소 신호를 볼 수 있다.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import threading
from uuid import UUID


class RequestCancelled(RuntimeError):
    """사용자가 진행 중인 AI 요청을 취소했다."""


_current: ContextVar[threading.Event | None] = ContextVar(
    "jobis_ai_cancellation_event", default=None
)
_active: dict[UUID, threading.Event] = {}
_lock = threading.Lock()


def register(request_id: UUID | None) -> threading.Event:
    event = threading.Event()
    if request_id is not None:
        with _lock:
            event = _active.setdefault(request_id, event)
    return event


def unregister(request_id: UUID | None, event: threading.Event) -> None:
    if request_id is None:
        return
    with _lock:
        if _active.get(request_id) is event:
            _active.pop(request_id, None)


def cancel(request_id: UUID) -> bool:
    with _lock:
        active = request_id in _active
        # 백엔드가 RUNNING으로 바꾼 직후, AI 요청이 register 하기 직전에 취소가 도착할 수
        # 있다. 이 짧은 경합에서 신호를 버리지 않고 tombstone Event를 남겨 다음 register가
        # 이미 취소된 실행으로 시작하게 한다.
        event = _active.setdefault(request_id, threading.Event())
        event.set()
    return active


@contextmanager
def scope(event: threading.Event):
    token = _current.set(event)
    try:
        yield
    finally:
        _current.reset(token)


def raise_if_cancelled(event: threading.Event | None = None) -> None:
    current = event if event is not None else _current.get()
    if current is not None and current.is_set():
        raise RequestCancelled("AI 답변 생성이 사용자 요청으로 중단되었습니다.")
