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
from pathlib import Path
from typing import Any, Callable, Iterator

_REPO_ROOT = Path(__file__).resolve().parents[2]

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
    """활성 레코더가 있으면 기록, 없으면 no-op. **감사 대상 이벤트는 별도로 영속한다.**"""

    if kind == "token" and _mute_tokens.get():
        return
    _audit(kind, label, detail)
    rec = _current.get()
    if rec is not None:
        rec.emit(kind, label, detail)


# ── 감사 로그 ────────────────────────────────────────────────────────────────
#
# **승인·거부·차단은 턴이 끝나도 남아야 한다.** 이 저장소가 가장 비싸게 배운 두 사고가 전부
# "기록이 없어서"였다 — 위임 거부가 관찰 문자열로만 사라져 hand-off 성공률의 **분모가 없었고**,
# 자기 루프가 통째로 꺼진 채 폴백이 정상처럼 답하고 있었다(평가 리포트 §1-1·§3-3).
#
# `_persist`(JOBIS_TRACE_DIR) 와 다른 층이다: 저쪽은 **턴 하나 전체**를 파일 하나로 남기는
# 디버깅용 opt-in 이고, 이쪽은 **정책 결정만** 골라 한 줄씩 잇는 append-only 다. 줄 단위라
# `grep`·`jq` 로 세어지고, 그래서 "동의를 몇 번 물었고 몇 번 승인됐나"에 답할 수 있다.
#
# 기본 켜짐이다 — 끄려면 `JOBIS_AUDIT_LOG=off`, 경로를 옮기려면 같은 변수에 파일 경로를 준다.
# 쓰기 실패는 삼킨다(관찰이 실행을 막지 않는다 — sink·_persist 와 같은 규약).
AUDIT_KINDS = frozenset({
    "consent_gate",         # 무거운 작업 — 실행 전 동의 요청
    "consent_granted",      # 그 동의가 소진되어 실제로 실행됨
    "resume_confirm_gate",  # 판정 전 이력서 확인 되묻기 (공고당 1회)
    "delegate",             # 에이전트 간 위임 성공
    "delegate_refused",     # 위임이 가드에 걸림 (사유 코드 6종) — 성공률의 분모
    "limit",                # 상한 도달 (스텝·깊이)
})


def _audit_path() -> str | None:
    setting = (os.getenv("JOBIS_AUDIT_LOG") or "").strip()
    if setting.lower() in {"off", "0", "false"}:
        return None
    return setting or str(_REPO_ROOT / "logs" / "audit.jsonl")


_AUDIT_MAX_CHARS = 200


def _audit_trim(detail: dict[str, Any]) -> dict[str, Any]:
    """긴 문자열은 자른다 — 감사 줄은 **세는 것**이지 읽는 것이 아니다.

    위임 성공 이벤트는 상대의 답변 전문을 싣는다(관찰 UI 용). 그대로 append 하면 파일이
    답변 로그가 되고, 정작 세려던 사유 코드가 그 안에 묻힌다. 전문이 필요하면 그 턴의
    trace(`JOBIS_TRACE_DIR`)를 본다 — 층이 다르다.
    """

    return {k: (v[:_AUDIT_MAX_CHARS] + "…" if isinstance(v, str) and len(v) > _AUDIT_MAX_CHARS
                else v)
            for k, v in detail.items()}


def _audit(kind: str, label: str, detail: dict[str, Any] | None) -> None:
    """감사 대상이면 JSONL 한 줄로 잇는다. 대상이 아니면 즉시 반환(핫 패스)."""

    if kind not in AUDIT_KINDS:
        return
    # LLM 호출 실패는 kind 가 llm_call 이라 위 집합에 없다 — 그쪽은 `structured.py` 가 이미
    # WARNING/ERROR 로그를 남기고 있으므로(D56) 여기서 두 번 세지 않는다.
    path = _audit_path()
    if path is None:
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        line = json.dumps({
            "at": datetime.now().isoformat(timespec="seconds"),
            "sessionId": _audit_session.get(),
            "kind": kind,
            "label": label,
            "detail": _audit_trim(detail or {}),
        }, ensure_ascii=False)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:   # noqa: BLE001
        pass


_audit_session: contextvars.ContextVar[str] = contextvars.ContextVar(
    "jobis_audit_session", default=""
)


@contextmanager
def audit_session(session_id: str) -> Iterator[None]:
    """이 블록의 감사 줄에 세션 id 를 붙인다. **누구의 턴이었는지 없으면 감사가 아니다.**"""

    token = _audit_session.set(str(session_id or ""))
    try:
        yield
    finally:
        _audit_session.reset(token)


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
