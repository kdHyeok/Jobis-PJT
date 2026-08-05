"""통합 채용공고(exports/all_job_postings.json)를 PostgreSQL 적재용 SQL 파일로 내보낸다.

사용법:
    python3 merge_job_postings.py      # 먼저 최신 통합본 생성
    python3 export_postgres.py         # → exports/all_job_postings_postgres.sql

만들어진 SQL은 psql로 한 번에 적재한다:
    psql -h <호스트> -U <유저> -d <DB명> -f all_job_postings_postgres.sql

- 같은 파일을 여러 번 부어도 안전하다. PK 충돌 시 최신 수집값으로 갱신하되,
  새 본문이 비어 있으면 기존 본문/OCR 상태를 보존한다.
- 원본 값은 그대로 두고, 날짜 비교용으로 파싱한 deadline_date(DATE) 컬럼만 추가한다.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import merge_job_postings

IN_JSON = Path("exports/all_job_postings.json")
OUT_SQL = Path("exports/all_job_postings_postgres.sql")
BATCH = 500  # multi-row INSERT 단위

SQL_HEADER = """\
-- Jobis 통합 채용공고 적재 스크립트 (자동 생성: export_postgres.py)
-- 스키마는 infra/airflow/migrations/jobrag 의 Flyway 마이그레이션이 관리합니다.
-- 같은 파일을 여러 번 실행해도 안전하며, 기존 공고는 아래 UPSERT 정책으로 갱신합니다.
"""

COLUMNS = (
    "source", "posting_id", "company", "title", "url", "employment_type",
    "experience", "education", "location", "posted_date", "deadline",
    "deadline_date", "detail_text", "text_source", "image_urls", "need_ocr",
    "ocr_status", "collected_at",
)

UPSERT = """\
ON CONFLICT (source, posting_id) DO UPDATE SET
    company = COALESCE(EXCLUDED.company, job_postings.company),
    title = COALESCE(EXCLUDED.title, job_postings.title),
    url = COALESCE(EXCLUDED.url, job_postings.url),
    employment_type = COALESCE(EXCLUDED.employment_type, job_postings.employment_type),
    experience = COALESCE(EXCLUDED.experience, job_postings.experience),
    education = COALESCE(EXCLUDED.education, job_postings.education),
    location = COALESCE(EXCLUDED.location, job_postings.location),
    posted_date = COALESCE(EXCLUDED.posted_date, job_postings.posted_date),
    deadline = EXCLUDED.deadline,
    deadline_date = EXCLUDED.deadline_date,
    detail_text = CASE
        WHEN NULLIF(BTRIM(EXCLUDED.detail_text), '') IS NOT NULL
             AND EXCLUDED.text_source <> 'none'
             AND EXCLUDED.need_ocr = 'X'
        THEN EXCLUDED.detail_text
        ELSE job_postings.detail_text
    END,
    text_source = CASE
        WHEN NULLIF(BTRIM(EXCLUDED.detail_text), '') IS NOT NULL
             AND EXCLUDED.text_source <> 'none'
             AND EXCLUDED.need_ocr = 'X'
        THEN EXCLUDED.text_source
        ELSE job_postings.text_source
    END,
    image_urls = CASE
        WHEN EXCLUDED.image_urls <> '[]'::jsonb THEN EXCLUDED.image_urls
        ELSE job_postings.image_urls
    END,
    need_ocr = CASE
        WHEN NULLIF(BTRIM(EXCLUDED.detail_text), '') IS NOT NULL
             AND EXCLUDED.text_source <> 'none'
             AND EXCLUDED.need_ocr = 'X'
        THEN EXCLUDED.need_ocr
        ELSE job_postings.need_ocr
    END,
    ocr_status = CASE
        WHEN NULLIF(BTRIM(EXCLUDED.detail_text), '') IS NOT NULL
             AND EXCLUDED.text_source <> 'none'
             AND EXCLUDED.need_ocr = 'X'
        THEN EXCLUDED.ocr_status
        WHEN job_postings.need_ocr = 'X'
             AND NULLIF(BTRIM(job_postings.detail_text), '') IS NOT NULL
        THEN job_postings.ocr_status
        WHEN EXCLUDED.need_ocr = 'O'
             AND EXCLUDED.image_urls <> '[]'::jsonb
             AND EXCLUDED.image_urls IS DISTINCT FROM job_postings.image_urls
        THEN 'pending'
        ELSE job_postings.ocr_status
    END,
    ocr_attempt_count = CASE
        WHEN job_postings.need_ocr = 'O'
             AND EXCLUDED.need_ocr = 'O'
             AND EXCLUDED.image_urls <> '[]'::jsonb
             AND EXCLUDED.image_urls IS DISTINCT FROM job_postings.image_urls
        THEN 0
        ELSE job_postings.ocr_attempt_count
    END,
    ocr_last_error = CASE
        WHEN NULLIF(BTRIM(EXCLUDED.detail_text), '') IS NOT NULL
             AND EXCLUDED.need_ocr = 'X'
        THEN NULL
        WHEN job_postings.need_ocr = 'O'
             AND EXCLUDED.need_ocr = 'O'
             AND EXCLUDED.image_urls <> '[]'::jsonb
             AND EXCLUDED.image_urls IS DISTINCT FROM job_postings.image_urls
        THEN NULL
        ELSE job_postings.ocr_last_error
    END,
    ocr_next_retry_at = CASE
        WHEN NULLIF(BTRIM(EXCLUDED.detail_text), '') IS NOT NULL
             AND EXCLUDED.need_ocr = 'X'
        THEN NULL
        WHEN job_postings.need_ocr = 'O'
             AND EXCLUDED.need_ocr = 'O'
             AND EXCLUDED.image_urls <> '[]'::jsonb
             AND EXCLUDED.image_urls IS DISTINCT FROM job_postings.image_urls
        THEN NULL
        ELSE job_postings.ocr_next_retry_at
    END,
    ocr_lease_until = CASE
        WHEN NULLIF(BTRIM(EXCLUDED.detail_text), '') IS NOT NULL
             AND EXCLUDED.need_ocr = 'X'
        THEN NULL
        ELSE job_postings.ocr_lease_until
    END,
    ocr_worker_id = CASE
        WHEN NULLIF(BTRIM(EXCLUDED.detail_text), '') IS NOT NULL
             AND EXCLUDED.need_ocr = 'X'
        THEN NULL
        ELSE job_postings.ocr_worker_id
    END,
    ocr_updated_at = CASE
        WHEN NULLIF(BTRIM(EXCLUDED.detail_text), '') IS NOT NULL
             AND EXCLUDED.need_ocr = 'X'
        THEN now()
        WHEN job_postings.need_ocr = 'O'
             AND EXCLUDED.need_ocr = 'O'
             AND EXCLUDED.image_urls <> '[]'::jsonb
             AND EXCLUDED.image_urls IS DISTINCT FROM job_postings.image_urls
        THEN now()
        ELSE job_postings.ocr_updated_at
    END,
    collected_at = COALESCE(EXCLUDED.collected_at, job_postings.collected_at)
"""


def text_source_of(row: dict) -> str:
    """본문의 출처를 판정한다. OCR로 채운 공고는 image_urls가 남아 있는 것으로 구분한다."""
    if row.get("need_ocr") == "O" or not row.get("detail_text"):
        return "none"
    return "ocr" if row.get("image_urls") else "original"


def normalize_row_for_load(row: dict) -> dict:
    """Keep the DB queue invariant: incomplete bodies are OCR-pending."""
    normalized = dict(row)
    has_body = bool(str(normalized.get("detail_text") or "").strip())
    if normalized.get("need_ocr") != "X" or not has_body:
        normalized["need_ocr"] = "O"
        normalized["detail_text"] = normalized.get("detail_text") or ""
    return normalized


def ocr_status_of(row: dict) -> str:
    if row.get("need_ocr") == "O" or not str(row.get("detail_text") or "").strip():
        return "pending" if row.get("image_urls") else "dead"
    return "succeeded" if text_source_of(row) == "ocr" else "not_required"


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
        sql_text(row.get("deadline_date") or merge_job_postings.parse_deadline_date(row.get("deadline"))),
        sql_text(row.get("detail_text")),
        sql_text(text_source_of(row)),
        sql_text(image_urls) + "::jsonb",
        sql_text(row.get("need_ocr") or "X"),
        sql_text(row.get("ocr_status") or ocr_status_of(row)),
        sql_text(row.get("collected_at")) + ("::timestamptz" if row.get("collected_at") else ""),
    ]
    return "(" + ", ".join(values) + ")"


def validate_rows(rows: list[dict]) -> None:
    """PostgreSQL이 한 INSERT에서 같은 행을 두 번 갱신하기 전에 입력을 검증한다."""
    seen: dict[tuple[str, str], int] = {}
    for index, row in enumerate(rows):
        source = row.get("source")
        posting_id = row.get("posting_id")
        if not source or not posting_id:
            raise SystemExit(
                f"필수 PK가 비어 있습니다: row={index} source={source!r} "
                f"posting_id={posting_id!r}"
            )
        key = (str(source), str(posting_id))
        if key in seen:
            raise SystemExit(
                f"동일 배치에 중복 PK가 있습니다: source={key[0]!r} "
                f"posting_id={key[1]!r} rows={seen[key]},{index}"
            )
        seen[key] = index


def load_source_rows() -> tuple[list[dict], dict[str, object]]:
    """Load all site JSON snapshots, including OCR-pending rows."""
    rows, missing, present = merge_job_postings.load_rows()
    if not rows:
        raise SystemExit("적재할 사이트별 원본 JSON이 없습니다.")
    normalized = [normalize_row_for_load(row) for row in rows]
    merged, duplicates = merge_job_postings.deduplicate(normalized)
    validate_rows(merged)
    return merged, {
        "present": present,
        "missing": missing,
        "duplicates_removed": duplicates,
    }


def render_sql(rows: list[dict]) -> str:
    rows = [normalize_row_for_load(row) for row in rows]
    validate_rows(rows)
    parts: list[str] = [SQL_HEADER, "\nBEGIN;\n"]
    for start in range(0, len(rows), BATCH):
        chunk = rows[start:start + BATCH]
        parts.append(
            f"INSERT INTO job_postings ({', '.join(COLUMNS)}) VALUES\n"
            + ",\n".join(row_values(r) for r in chunk)
            + f"\n{UPSERT};\n"
        )
    parts.append("COMMIT;\n")
    return "".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from-source-jsons",
        action="store_true",
        help="사이트별 원본 JSON에서 X/O 행을 모두 읽어 DB 적재 SQL 생성",
    )
    parser.add_argument("--input", type=Path, default=IN_JSON)
    parser.add_argument("--output", type=Path, default=OUT_SQL)
    args = parser.parse_args()

    load_stats: dict[str, object] = {}
    if args.from_source_jsons:
        rows, load_stats = load_source_rows()
    else:
        if not args.input.exists():
            raise SystemExit(
                f"통합본이 없습니다. 먼저 실행: python3 merge_job_postings.py ({args.input})"
            )
        rows = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise SystemExit("통합본 JSON은 객체 배열이어야 합니다.")
        rows = [normalize_row_for_load(row) for row in rows]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_sql(rows), encoding="utf-8")
    with_date = sum(
        1 for r in rows
        if r.get("deadline_date") or merge_job_postings.parse_deadline_date(r.get("deadline"))
    )
    pending = sum(row.get("need_ocr") == "O" for row in rows)
    print(
        f"[export_postgres] status=completed records={len(rows)} "
        f"ocr_pending={pending} duplicates_removed={load_stats.get('duplicates_removed', 0)} "
        f"deadline_date_parsed={with_date} sql={args.output} "
        f"size={args.output.stat().st_size / 1e6:.1f}MB",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
