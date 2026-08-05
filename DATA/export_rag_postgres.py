"""Export only completed PostgreSQL job postings as the RAG JSON input."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import date, datetime
from pathlib import Path


DEFAULT_OUTPUT = Path("exports/all_job_postings_rag.json")
RAG_COLUMNS = (
    "source", "posting_id", "company", "title", "url", "employment_type",
    "experience", "education", "location", "posted_date", "deadline",
    "deadline_date", "detail_text", "text_source", "image_urls", "need_ocr",
    "collected_at",
)
SELECT_COMPLETED_SQL = f"""
SELECT {', '.join(RAG_COLUMNS)}
FROM job_postings
WHERE need_ocr = 'X'
  AND NULLIF(BTRIM(detail_text), '') IS NOT NULL
ORDER BY source, posting_id
"""


def open_connection(dsn: str):
    import psycopg2

    return psycopg2.connect(dsn)


def json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def fetch_completed(connection) -> list[dict]:
    with connection.cursor() as cursor:
        cursor.execute(SELECT_COMPLETED_SQL)
        rows = cursor.fetchall()
        columns = [description.name for description in cursor.description]
    return [
        {column: json_value(value) for column, value in zip(columns, row)}
        for row in rows
    ]


def write_json_atomic(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            json.dump(rows, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    dsn = os.environ.get("JOBRAG_PG_DSN")
    if not dsn:
        raise SystemExit("JOBRAG_PG_DSN 환경변수가 필요합니다.")

    connection = open_connection(dsn)
    try:
        rows = fetch_completed(connection)
    finally:
        connection.close()
    write_json_atomic(args.output, rows)
    print(
        f"[export_rag_postgres] status=completed records={len(rows)} output={args.output}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
