"""통합 채용공고(exports/all_job_postings.json)를 PostgreSQL 적재용 SQL 파일로 내보낸다.

사용법:
    python3 merge_job_postings.py      # 먼저 최신 통합본 생성
    python3 export_postgres.py         # → exports/all_job_postings_postgres.sql

만들어진 SQL은 psql로 한 번에 적재한다:
    psql -h <호스트> -U <유저> -d <DB명> -f all_job_postings_postgres.sql

- 같은 파일을 여러 번 부어도 안전하다(PK 충돌 시 건너뜀: ON CONFLICT DO NOTHING).
- 원본 값은 그대로 두고, 날짜 비교용으로 파싱한 deadline_date(DATE) 컬럼만 추가한다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from merge_job_postings import parse_deadline_date

IN_JSON = Path("exports/all_job_postings.json")
OUT_SQL = Path("exports/all_job_postings_postgres.sql")
BATCH = 500  # multi-row INSERT 단위

DDL = """\
-- Jobis 통합 채용공고 적재 스크립트 (자동 생성: export_postgres.py)
-- 같은 파일을 여러 번 실행해도 안전합니다 (이미 있는 공고는 건너뜀).
-- 기존 테이블을 갈아엎고 새로 넣으려면 아래 한 줄의 주석을 풀고 실행하세요.
-- DROP TABLE IF EXISTS job_postings;

CREATE TABLE IF NOT EXISTS job_postings (
    source          TEXT NOT NULL,          -- 잡코리아/사람인/원티드/인크루트/고용24
    posting_id      TEXT NOT NULL,          -- 사이트별 공고 ID (사이트 내 고유)
    company         TEXT,
    title           TEXT,
    url             TEXT,
    employment_type TEXT,
    experience      TEXT,
    education       TEXT,
    location        TEXT,
    posted_date     TEXT,                   -- 원본 표기 그대로 (사이트별 형식 다름, null 많음)
    deadline        TEXT,                   -- 원본 표기 그대로 ('상시채용' 등 포함)
    deadline_date   DATE,                   -- deadline에서 파싱한 날짜 (비교용, 파싱 불가면 NULL)
    detail_text     TEXT,                   -- 본문 (need_ocr='O'면 비어 있음: OCR 대기)
    text_source     TEXT NOT NULL,          -- 본문 출처: original=사이트 원문 / ocr=이미지 OCR 추출(정확도 ~90%, 조사 오탈자 감안) / none=본문 없음
    image_urls      JSONB NOT NULL DEFAULT '[]'::jsonb,
    need_ocr        CHAR(1) NOT NULL,       -- 'X'=본문 있음 / 'O'=이미지형(OCR 대기)
    collected_at    TIMESTAMPTZ,            -- 수집 시각(UTC)
    PRIMARY KEY (source, posting_id)
);

CREATE INDEX IF NOT EXISTS idx_job_postings_need_ocr ON job_postings (need_ocr);
CREATE INDEX IF NOT EXISTS idx_job_postings_deadline_date ON job_postings (deadline_date);
"""

COLUMNS = (
    "source", "posting_id", "company", "title", "url", "employment_type",
    "experience", "education", "location", "posted_date", "deadline",
    "deadline_date", "detail_text", "text_source", "image_urls", "need_ocr", "collected_at",
)


def text_source_of(row: dict) -> str:
    """본문의 출처를 판정한다. OCR로 채운 공고는 image_urls가 남아 있는 것으로 구분한다."""
    if row.get("need_ocr") == "O" or not row.get("detail_text"):
        return "none"
    return "ocr" if row.get("image_urls") else "original"


def sql_text(value: object) -> str:
    """문자열을 PostgreSQL 리터럴로 안전하게 이스케이프한다(따옴표 두 배)."""
    if value is None or value == "":
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def row_values(row: dict) -> str:
    image_urls = json.dumps(row.get("image_urls") or [], ensure_ascii=False)
    values = [
        sql_text(row.get("source")),
        sql_text(row.get("posting_id")),
        sql_text(row.get("company")),
        sql_text(row.get("title")),
        sql_text(row.get("url")),
        sql_text(row.get("employment_type")),
        sql_text(row.get("experience")),
        sql_text(row.get("education")),
        sql_text(row.get("location")),
        sql_text(row.get("posted_date")),
        sql_text(row.get("deadline")),
        # 통합본이 이미 파싱해 넣어준 값을 그대로 쓴다. 예전 형식(필드 없음)의
        # JSON으로 실행하는 경우에만 여기서 파싱한다.
        sql_text(row.get("deadline_date") or parse_deadline_date(row.get("deadline"))),
        sql_text(row.get("detail_text")),
        sql_text(text_source_of(row)),
        sql_text(image_urls) + "::jsonb",
        sql_text(row.get("need_ocr") or "X"),
        sql_text(row.get("collected_at")) + ("::timestamptz" if row.get("collected_at") else ""),
    ]
    return "(" + ", ".join(values) + ")"


def main() -> int:
    if not IN_JSON.exists():
        raise SystemExit(f"통합본이 없습니다. 먼저 실행: python3 merge_job_postings.py ({IN_JSON})")
    rows = json.loads(IN_JSON.read_text(encoding="utf-8"))

    parts: list[str] = [DDL, "\nBEGIN;\n"]
    for start in range(0, len(rows), BATCH):
        chunk = rows[start:start + BATCH]
        parts.append(
            f"INSERT INTO job_postings ({', '.join(COLUMNS)}) VALUES\n"
            + ",\n".join(row_values(r) for r in chunk)
            + "\nON CONFLICT (source, posting_id) DO NOTHING;\n"
        )
    parts.append("COMMIT;\n")

    OUT_SQL.write_text("".join(parts), encoding="utf-8")
    with_date = sum(
        1 for r in rows
        if r.get("deadline_date") or parse_deadline_date(r.get("deadline"))
    )
    print(
        f"[export_postgres] status=completed records={len(rows)} "
        f"deadline_date_parsed={with_date} sql={OUT_SQL} "
        f"size={OUT_SQL.stat().st_size / 1e6:.1f}MB",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
