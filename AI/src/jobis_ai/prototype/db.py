"""프로토타입 UI 의 실행 기록 저장소 — SQLite 단일 테이블.

한 행 = 대화 한 턴(run): 입력(메시지·이력서·공고) + 최종 응답 + 트레이스 전체.
개발 관찰용이라 스키마를 단순하게 유지한다. 운영 저장소가 아니다.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_DB = Path(__file__).resolve().parents[3] / "prototype_runs.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id            TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    session_id    TEXT NOT NULL,
    message       TEXT NOT NULL,
    resume_text   TEXT,
    posting_text  TEXT,
    response_json TEXT NOT NULL,
    trace_json    TEXT NOT NULL
);
"""


class RunStore:
    """실행 기록 CRUD. 커넥션은 호출마다 열고 닫는다(개발용 단순성 우선)."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def save_run(
        self,
        *,
        session_id: str,
        message: str,
        resume_text: str | None,
        posting_text: str | None,
        response: dict[str, Any],
        trace_events: list[dict[str, Any]],
    ) -> str:
        run_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO runs (id, created_at, session_id, message, resume_text, "
                "posting_text, response_json, trace_json) VALUES (?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    datetime.now(timezone.utc).isoformat(),
                    session_id,
                    message,
                    resume_text,
                    posting_text,
                    json.dumps(response, ensure_ascii=False, default=str),
                    json.dumps(trace_events, ensure_ascii=False, default=str),
                ),
            )
        return run_id

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        """최신순 목록 — 상세(트레이스)는 빼고 요약만."""

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, created_at, session_id, message FROM runs "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        record = dict(row)
        record["response"] = json.loads(record.pop("response_json"))
        record["trace"] = json.loads(record.pop("trace_json"))
        return record
