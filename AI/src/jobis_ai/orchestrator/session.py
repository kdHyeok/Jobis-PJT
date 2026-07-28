"""세션 자산 저장소 (개선방안 Phase 2-3).

대화에 걸쳐 쌓이는 자산(이력서·공고·프로필·분석 결과·추천)을 세션 키로 격리해 보관한다.
LangGraph checkpointer(그래프 실행 중단점)와는 별개 — 이건 "세션 자산" 저장이다.

구현이 둘이고 같은 인터페이스(get/update/clear)를 쓴다:

  · SqliteSessionStore (기본) — 파일 하나에 영속. 프로세스를 재시작해도 맥락이 남는다.
    웹에서 분석을 끝낸 뒤 "자소서 써줘"로 이어가는 흐름이 서버 재시작에 끊기지 않으려면
    영속이 필요하다. 웹 DB(MySQL/PostgreSQL)에 붙이지 않는 이유는 이 패키지가 웹 인프라에
    의존하지 않게 하려는 것 — 저장 위치를 바꿔야 하면 이 파일의 구현만 갈아끼운다.
  · MemorySessionStore — 테스트·일회성 실행용. 파일을 남기지 않는다.

선택은 환경변수 SESSION_STORE=sqlite|memory (기본 sqlite), 경로는 SESSION_DB_PATH.

**반환 규약**: get() 은 **복사본**을 준다. 반환된 dict 를 고쳐도 저장되지 않는다 —
저장은 반드시 update() 로 한다. 두 구현의 동작을 같게 유지하려면 이 규약이 필요하다
(예전 in-memory 구현은 살아 있는 dict 를 줘서, 받은 쪽이 직접 고쳐도 저장됐다).
"""

from __future__ import annotations

import copy
import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

# 세션이 가질 수 있는 자산 키. 이 밖의 키는 저장하지 않는다(오염 방지).
ASSET_KEYS = frozenset({
    "resume",            # {sourceType, value} — 이력서 원천
    "job_posting",       # {sourceType, value} — 목표 공고 원천
    "profile",           # NormalizedUserProfile dict (빌드 캐시)
    "analysis",          # AnalyzeResponse dict (fit_analysis 산출)
    "recommendations",   # job_recommend 산출
    "roadmap",           # 준비 로드맵 (fit_analysis 산출 → roadmap_manager 조회)
    "coverletter",       # 자소서 초안 (항상 draft_pending_review 상태)
    "application_plan",  # {decision, routes} — application_plan 산출 (목표 상태·지원 경로)
    "posting_summary",   # NormalizedJobPosting dict — 화면(우측 패널) 항목화용 파싱 결과 캐시
    "judgment_summary",  # {matches, score} — 판정 근거(요건별 매칭·점수 산출) 화면 표시용 캐시
    "userId",
    "preparationPeriodWeeks",
    "availableHoursPerWeek",
    "preferences",       # {roles, companies, domains} — 대화로 수집한 공고 선호 (누적)
    "last_message",      # 이번 턴 발화 원문 — 대화형 에이전트(preference_intake)의 입력
    "history",           # [{role: user|assistant, content}] — 턴 간 대화 맥락 (append_history 로만 기록)
})

# 대화 이력 보관 상한 — 오래된 턴부터 버린다 (무한 성장 방지).
HISTORY_MAX_ITEMS = 30

_DEFAULT_DB = Path(__file__).resolve().parents[3] / "sessions.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    assets     TEXT NOT NULL,          -- 자산 dict 전체를 JSON 으로
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def _reject_unknown(updates: dict[str, Any]) -> None:
    """허용되지 않은 키는 조용히 버리지 않고 에러로 낸다(오타로 자산이 사라지는 것을 막는다)."""

    unknown = set(updates) - ASSET_KEYS
    if unknown:
        raise KeyError(f"허용되지 않은 세션 자산 키: {sorted(unknown)}")


class MemorySessionStore:
    """프로세스 안에만 있는 저장소. 테스트·일회성 실행용."""

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def get(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            # 깊은 복사 — 얕은 복사는 중첩 dict/list 를 공유해 "복사본 규약"(받은 dict 를
            # 고쳐도 저장되지 않는다)이 사실상 깨지고, SQLite 구현(JSON 왕복)과 동작이 달라진다.
            return copy.deepcopy(self._sessions.get(session_id) or {})

    def update(self, session_id: str, updates: dict[str, Any]) -> None:
        _reject_unknown(updates)
        with self._lock:
            # 쓰기도 깊은 복사 — 호출자가 넘긴 dict 를 이후에 고쳐도 저장분이 안 바뀐다(SQLite 와 동일).
            self._sessions.setdefault(session_id, {}).update(copy.deepcopy(updates))

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)


class SqliteSessionStore:
    """SQLite 파일 하나에 영속. 커넥션은 호출마다 열고 닫는다(스레드 안전).

    브릿지는 워커 스레드에서 세션을 읽고 쓴다. sqlite3 커넥션은 스레드 간 공유가 안 되므로
    호출마다 새로 연다 — 세션 접근은 대화 턴 단위라 빈도가 낮아 이 단순함이 이득이다.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            # WAL: 브릿지와 관찰 UI 처럼 여러 프로세스가 같은 파일을 볼 때 읽기가 쓰기에 막히지 않는다.
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _decode(raw: Any) -> dict[str, Any]:
        try:
            return json.loads(raw) or {}
        except (ValueError, TypeError):
            # 저장이 깨졌으면 빈 세션으로 시작한다 — 깨진 값으로 판정하는 것보다 낫다.
            return {}

    def get(self, session_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT assets FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        return {} if row is None else self._decode(row["assets"])

    def update(self, session_id: str, updates: dict[str, Any]) -> None:
        _reject_unknown(updates)
        # 읽고 병합해 쓰는 사이에 다른 턴이 끼어들지 않게 트랜잭션 하나로 묶는다.
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT assets FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            assets = {} if row is None else self._decode(row["assets"])
            assets.update(updates)
            conn.execute(
                "INSERT INTO sessions (session_id, assets, updated_at) "
                "VALUES (?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "assets = excluded.assets, updated_at = CURRENT_TIMESTAMP",
                (session_id, json.dumps(assets, ensure_ascii=False)),
            )

    def clear(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))


# 예전 이름 호환 — 외부에서 SessionStore 를 참조하던 곳이 있다.
SessionStore = MemorySessionStore

_STORE: MemorySessionStore | SqliteSessionStore | None = None


def get_session_store() -> MemorySessionStore | SqliteSessionStore:
    """설정에 맞는 저장소 하나를 만들어 재사용한다.

    SESSION_STORE=memory 면 프로세스 내 저장(테스트). 그 밖이면 SQLite 영속.
    """

    global _STORE
    if _STORE is None:
        kind = (os.getenv("SESSION_STORE") or "sqlite").strip().lower()
        if kind == "memory":
            _STORE = MemorySessionStore()
        else:
            _STORE = SqliteSessionStore(os.getenv("SESSION_DB_PATH") or None)
    return _STORE


def reset_session_store() -> None:
    """저장소 인스턴스를 버린다(테스트에서 구현·경로를 바꿔 끼울 때 사용)."""

    global _STORE
    _STORE = None


def append_history(session_id: str, role: str, content: str) -> None:
    """대화 이력에 한 항목을 추가한다. 빈 내용은 무시, 상한 초과분은 오래된 것부터 버린다.

    기록 시점 규약: 턴이 **끝날 때** user → assistant 순으로 기록한다.
    따라서 턴 진행 중에 읽는 history 는 항상 '이전 턴까지'의 대화다
    (이번 발화는 last_message 로 별도 전달 — 프롬프트 중복 방지).
    """

    content = (content or "").strip()
    if not content:
        return
    store = get_session_store()
    history = list(store.get(session_id).get("history") or [])
    history.append({"role": role, "content": content})
    store.update(session_id, {"history": history[-HISTORY_MAX_ITEMS:]})


def recent_history(session: dict[str, Any], max_items: int = 6, max_chars: int = 300) -> list[dict]:
    """LLM 프롬프트용 최근 대화 — 최근 max_items 개, 항목당 max_chars 자로 자른다."""

    items = list(session.get("history") or [])[-max_items:]
    return [
        {"role": str(h.get("role") or ""), "content": str(h.get("content") or "")[:max_chars]}
        for h in items
    ]
