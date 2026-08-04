"""레거시 SQLite 통합본을 검증하고 PostgreSQL 일회성 import SQL로 변환한다.

본문 완료 행과 OCR 대기 행을 모두 ``job_postings``에 가져온다. 생성 SQL은 임시
staging 테이블에서 입력 건수와 PK, OCR 상태를 검증한 뒤 UPSERT하며, 현재 PostgreSQL
값이 있으면 보존하고 빈 본문만 레거시 본문으로 보강한다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import export_postgres
import merge_job_postings


DEFAULT_SQLITE = Path("/opt/jobis/imports/all_job_postings.db")
DEFAULT_IMPORT_SQL = Path("exports/legacy_job_postings_import.sql")
DEFAULT_VERIFY_SQL = Path("exports/legacy_job_postings_verify.sql")
DEFAULT_MANIFEST = Path("exports/legacy_job_postings_import_manifest.json")
LEGACY_COLUMNS = tuple(field for field in merge_job_postings.FIELDS if field != "deadline_date")
STAGE_TABLE = "legacy_job_postings_stage"

LEGACY_UPSERT = """\
ON CONFLICT (source, posting_id) DO UPDATE SET
    company = COALESCE(existing.company, EXCLUDED.company),
    title = COALESCE(existing.title, EXCLUDED.title),
    url = COALESCE(existing.url, EXCLUDED.url),
    employment_type = COALESCE(existing.employment_type, EXCLUDED.employment_type),
    experience = COALESCE(existing.experience, EXCLUDED.experience),
    education = COALESCE(existing.education, EXCLUDED.education),
    location = COALESCE(existing.location, EXCLUDED.location),
    posted_date = COALESCE(existing.posted_date, EXCLUDED.posted_date),
    deadline = COALESCE(existing.deadline, EXCLUDED.deadline),
    deadline_date = COALESCE(existing.deadline_date, EXCLUDED.deadline_date),
    detail_text = CASE
        WHEN NULLIF(BTRIM(existing.detail_text), '') IS NULL
             AND NULLIF(BTRIM(EXCLUDED.detail_text), '') IS NOT NULL
        THEN EXCLUDED.detail_text
        ELSE existing.detail_text
    END,
    text_source = CASE
        WHEN NULLIF(BTRIM(existing.detail_text), '') IS NULL
             AND NULLIF(BTRIM(EXCLUDED.detail_text), '') IS NOT NULL
        THEN EXCLUDED.text_source
        ELSE existing.text_source
    END,
    image_urls = CASE
        WHEN existing.image_urls = '[]'::jsonb
             AND EXCLUDED.image_urls <> '[]'::jsonb
        THEN EXCLUDED.image_urls
        ELSE existing.image_urls
    END,
    need_ocr = CASE
        WHEN NULLIF(BTRIM(existing.detail_text), '') IS NOT NULL
             OR NULLIF(BTRIM(EXCLUDED.detail_text), '') IS NOT NULL
        THEN 'X'
        ELSE 'O'
    END,
    ocr_status = CASE
        WHEN NULLIF(BTRIM(existing.detail_text), '') IS NOT NULL
        THEN existing.ocr_status
        WHEN NULLIF(BTRIM(EXCLUDED.detail_text), '') IS NOT NULL
        THEN EXCLUDED.ocr_status
        WHEN existing.ocr_status IN ('pending', 'processing', 'retry_wait', 'dead')
        THEN existing.ocr_status
        ELSE EXCLUDED.ocr_status
    END,
    ocr_attempt_count = CASE
        WHEN existing.image_urls = '[]'::jsonb
             AND EXCLUDED.image_urls <> '[]'::jsonb
        THEN 0
        ELSE existing.ocr_attempt_count
    END,
    ocr_last_error = CASE
        WHEN NULLIF(BTRIM(EXCLUDED.detail_text), '') IS NOT NULL
          OR (existing.image_urls = '[]'::jsonb AND EXCLUDED.image_urls <> '[]'::jsonb)
        THEN NULL
        ELSE existing.ocr_last_error
    END,
    ocr_next_retry_at = CASE
        WHEN NULLIF(BTRIM(EXCLUDED.detail_text), '') IS NOT NULL
          OR (existing.image_urls = '[]'::jsonb AND EXCLUDED.image_urls <> '[]'::jsonb)
        THEN NULL
        ELSE existing.ocr_next_retry_at
    END,
    ocr_lease_until = CASE
        WHEN NULLIF(BTRIM(EXCLUDED.detail_text), '') IS NOT NULL THEN NULL
        ELSE existing.ocr_lease_until
    END,
    ocr_worker_id = CASE
        WHEN NULLIF(BTRIM(EXCLUDED.detail_text), '') IS NOT NULL THEN NULL
        ELSE existing.ocr_worker_id
    END,
    ocr_updated_at = CASE
        WHEN NULLIF(BTRIM(EXCLUDED.detail_text), '') IS NOT NULL
          OR (existing.image_urls = '[]'::jsonb AND EXCLUDED.image_urls <> '[]'::jsonb)
        THEN now()
        ELSE existing.ocr_updated_at
    END,
    collected_at = COALESCE(existing.collected_at, EXCLUDED.collected_at)
"""


def sqlite_connection(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise SystemExit(f"레거시 SQLite 파일을 찾을 수 없습니다: {path}")
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def parse_image_urls(value: object, source: object, posting_id: object) -> list[str]:
    if value in (None, ""):
        return []
    parsed = value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise SystemExit(
                f"image_urls JSON이 잘못되었습니다: source={source!r} "
                f"posting_id={posting_id!r} error={exc.msg}"
            ) from exc
    if not isinstance(parsed, list) or any(not isinstance(url, str) for url in parsed):
        raise SystemExit(
            f"image_urls는 문자열 배열이어야 합니다: source={source!r} "
            f"posting_id={posting_id!r}"
        )
    return parsed


def load_rows(path: Path) -> list[dict]:
    connection = sqlite_connection(path)
    try:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'job_postings'"
        ).fetchone()
        if not table:
            raise SystemExit("레거시 SQLite에 job_postings 테이블이 없습니다.")
        actual_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(job_postings)")
        }
        missing = sorted(set(LEGACY_COLUMNS) - actual_columns)
        if missing:
            raise SystemExit(f"레거시 SQLite 필수 컬럼이 없습니다: {','.join(missing)}")
        raw_rows = [dict(row) for row in connection.execute("SELECT * FROM job_postings")]
    finally:
        connection.close()

    normalized: list[dict] = []
    for raw in raw_rows:
        source = raw.get("source")
        posting_id = raw.get("posting_id")
        status = raw.get("need_ocr")
        if status not in {"O", "X"}:
            raise SystemExit(
                f"need_ocr 값이 O/X가 아닙니다: source={source!r} "
                f"posting_id={posting_id!r} need_ocr={status!r}"
            )
        row = merge_job_postings.normalize_row(str(source or ""), raw)
        row["image_urls"] = parse_image_urls(raw.get("image_urls"), source, posting_id)
        normalized.append(export_postgres.normalize_row_for_load(row))

    # staging에 들어가기 전에 누락/중복 PK를 차단한다. OCR 대기 행도 원본 품질 검증에는 포함한다.
    export_postgres.validate_rows(normalized)
    return normalized


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_rows(path: Path) -> tuple[list[dict], dict]:
    rows = load_rows(path)
    completed = sum(
        row.get("need_ocr") == "X" and bool(str(row.get("detail_text") or "").strip())
        for row in rows
    )
    pending = len(rows) - completed
    merged, duplicates = merge_job_postings.deduplicate(rows)
    export_postgres.validate_rows(merged)
    source_counts = Counter(str(row["source"]) for row in merged)
    stats = {
        "sqlite_path": str(path.resolve()),
        "sqlite_sha256": file_sha256(path),
        "input_records": len(rows),
        "ready_before_dedup": len(rows),
        "completed_records": completed,
        "ocr_pending_records": pending,
        "ocr_or_empty_excluded": 0,
        "duplicates_removed": duplicates,
        "ready_to_upsert": len(merged),
        "source_counts": dict(sorted(source_counts.items())),
    }
    return merged, stats


def values_insert(table: str, rows: list[dict]) -> str:
    parts: list[str] = []
    for start in range(0, len(rows), export_postgres.BATCH):
        chunk = rows[start:start + export_postgres.BATCH]
        parts.append(
            f"INSERT INTO {table} ({', '.join(export_postgres.COLUMNS)}) VALUES\n"
            + ",\n".join(export_postgres.row_values(row) for row in chunk)
            + ";\n"
        )
    return "".join(parts)


def stage_validation_sql(expected: int) -> str:
    return f"""\
DO $$
BEGIN
    IF (SELECT COUNT(*) FROM {STAGE_TABLE}) <> {expected} THEN
        RAISE EXCEPTION 'legacy staging row count mismatch: expected={expected} actual=%',
            (SELECT COUNT(*) FROM {STAGE_TABLE});
    END IF;
    IF EXISTS (
        SELECT 1 FROM {STAGE_TABLE}
        WHERE source IS NULL OR posting_id IS NULL
           OR need_ocr NOT IN ('O', 'X')
           OR (need_ocr = 'X' AND NULLIF(BTRIM(detail_text), '') IS NULL)
           OR ocr_status NOT IN (
               'not_required', 'pending', 'processing',
               'retry_wait', 'succeeded', 'dead'
           )
    ) THEN
        RAISE EXCEPTION 'legacy staging contains invalid rows or OCR states';
    END IF;
    IF EXISTS (
        SELECT 1 FROM {STAGE_TABLE}
        GROUP BY source, posting_id HAVING COUNT(*) > 1
    ) THEN
        RAISE EXCEPTION 'legacy staging contains duplicate primary keys';
    END IF;
END $$;
"""


def post_upsert_validation_sql(expected_table: str) -> str:
    return f"""\
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM {expected_table} expected
        LEFT JOIN job_postings loaded
          ON loaded.source = expected.source
         AND loaded.posting_id = expected.posting_id
        WHERE loaded.source IS NULL
           OR NOT (
               (
                   loaded.need_ocr = 'X'
                   AND NULLIF(BTRIM(loaded.detail_text), '') IS NOT NULL
                   AND loaded.ocr_status IN ('not_required', 'succeeded')
               )
               OR (
                   loaded.need_ocr = 'O'
                   AND loaded.ocr_status IN ('pending', 'processing', 'retry_wait', 'dead')
               )
           )
    ) THEN
        RAISE EXCEPTION 'legacy import verification failed: missing or invalid loaded rows';
    END IF;
END $$;
"""


def render_import_sql(rows: list[dict], commit: bool = True) -> str:
    if not rows:
        raise SystemExit("레거시 import 대상이 없습니다.")
    export_postgres.validate_rows(rows)
    transaction_end = "COMMIT" if commit else "ROLLBACK"
    return (
        "-- JOBIS legacy SQLite one-time import. Generated file; do not edit.\n"
        "BEGIN;\n"
        f"CREATE TEMP TABLE {STAGE_TABLE} "
        "(LIKE job_postings INCLUDING DEFAULTS) ON COMMIT DROP;\n"
        + values_insert(STAGE_TABLE, rows)
        + stage_validation_sql(len(rows))
        + f"INSERT INTO job_postings AS existing ({', '.join(export_postgres.COLUMNS)})\n"
        + f"SELECT {', '.join(export_postgres.COLUMNS)} FROM {STAGE_TABLE}\n"
        # INSERT ... SELECT의 ON을 JOIN 조건으로 오해하지 않도록 PostgreSQL 권장 형태를 쓴다.
        + "WHERE true\n"
        + LEGACY_UPSERT
        + ";\n"
        + post_upsert_validation_sql(STAGE_TABLE)
        + f"SELECT COUNT(*) AS staged_records FROM {STAGE_TABLE};\n"
        + f"{transaction_end};\n"
    )


def expected_values_insert(rows: list[dict]) -> str:
    parts: list[str] = []
    for start in range(0, len(rows), export_postgres.BATCH):
        chunk = rows[start:start + export_postgres.BATCH]
        values = ",\n".join(
            f"({export_postgres.sql_text(row['source'])}, "
            f"{export_postgres.sql_text(row['posting_id'])})"
            for row in chunk
        )
        parts.append(
            "INSERT INTO legacy_job_postings_expected (source, posting_id) VALUES\n"
            + values
            + ";\n"
        )
    return "".join(parts)


def render_verify_sql(rows: list[dict]) -> str:
    export_postgres.validate_rows(rows)
    return (
        "-- Verify the committed one-time legacy import.\n"
        "BEGIN;\n"
        "CREATE TEMP TABLE legacy_job_postings_expected "
        "(source TEXT NOT NULL, posting_id TEXT NOT NULL, PRIMARY KEY (source, posting_id)) "
        "ON COMMIT DROP;\n"
        + expected_values_insert(rows)
        + post_upsert_validation_sql("legacy_job_postings_expected")
        + "SELECT COUNT(*) AS verified_records FROM legacy_job_postings_expected;\n"
        + "COMMIT;\n"
    )


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "prepare"):
        child = subparsers.add_parser(command)
        child.add_argument("--sqlite", type=Path, default=DEFAULT_SQLITE)
        if command == "prepare":
            child.add_argument("--import-sql", type=Path, default=DEFAULT_IMPORT_SQL)
            child.add_argument("--verify-sql", type=Path, default=DEFAULT_VERIFY_SQL)
            child.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
            child.add_argument(
                "--rollback",
                action="store_true",
                help="실제 PostgreSQL 통합 검증용으로 마지막에 COMMIT 대신 ROLLBACK",
            )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows, stats = prepare_rows(args.sqlite)
    if args.command == "validate":
        print(json.dumps(stats, ensure_ascii=False, indent=2), flush=True)
        return 0

    write_text(args.import_sql, render_import_sql(rows, commit=not args.rollback))
    write_text(args.verify_sql, render_verify_sql(rows))
    manifest = {
        **stats,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "transaction_end": "ROLLBACK" if args.rollback else "COMMIT",
        "import_sql": str(args.import_sql),
        "verify_sql": str(args.verify_sql),
    }
    write_text(args.manifest, json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
