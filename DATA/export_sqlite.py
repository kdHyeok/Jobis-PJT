"""jobrag PostgreSQL(OCR 본문 + RAG 임베딩 현재 상태)을 SQLite 파일로 스냅샷한다.

사용법(호스트에서 실행):
    python3 export_sqlite.py                       # → exports/all_job_postings.db
    python3 export_sqlite.py --output snap.db

호스트에 psycopg2가 없고 파이프라인 PostgreSQL은 포트를 열지 않으므로,
컨테이너 psql의 COPY(CSV)를 그대로 읽어 넣는다. job_postings 테이블은
import_legacy_sqlite.py가 다시 읽을 수 있는 형태 그대로다.

chunks.embedding(pgvector 1024차원)은 float32 BLOB으로 저장한다. 읽을 때:
    numpy.frombuffer(blob, dtype="float32")            # 또는 array("f").frombytes(blob)
PostgreSQL로 되돌릴 때는 다시 '[a,b,c]' 텍스트로 만들어 ::vector로 캐스팅한다.

테이블별 COPY는 각각 다른 시점의 스냅샷이다. 인제스트가 도는 중에 뜨면 부분 결과가
담기므로, 완료 후 다시 실행한다(파일은 매번 통째로 다시 쓴다).
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import sqlite3
import subprocess
from array import array
from pathlib import Path

DEFAULT_OUTPUT = Path("exports/all_job_postings.db")
NULL_TOKEN = "\\N"  # CSV에서 NULL과 빈 문자열을 구분하는 표식
INTEGER_COLUMNS = {"ocr_attempt_count", "tokens", "exp_min", "exp_max", "embed_dimensions"}
VECTOR_COLUMNS = {"embedding"}  # pgvector 텍스트 '[a,b,...]' → float32 BLOB
# chunks가 postings를 참조하므로 부모 테이블을 먼저 뜬다.
PRIMARY_KEYS = {
    "job_postings": "source, posting_id",
    "postings": "uid",
    "chunks": "chunk_id",
    "rag_index_metadata": "singleton",
}


def copy_sql(table: str) -> str:
    return (
        f"COPY (SELECT * FROM {table} ORDER BY {PRIMARY_KEYS[table]}) "
        f"TO STDOUT WITH (FORMAT csv, HEADER, NULL '{NULL_TOKEN}')"
    )


def dump_csv(container: str, user: str, database: str, table: str) -> str:
    """컨테이너 psql로 테이블 전체를 CSV로 받는다."""
    result = subprocess.run(
        [
            "docker", "exec", container,
            "psql", "-U", user, "-d", database, "-v", "ON_ERROR_STOP=1",
            "-c", copy_sql(table),
        ],
        capture_output=True,
        check=True,
    )
    return result.stdout.decode("utf-8")


def cell(column: str, value: str):
    if value == NULL_TOKEN:
        return None
    if column in VECTOR_COLUMNS:
        return array("f", (float(part) for part in value.strip("[]").split(","))).tobytes()
    return value


def build_sqlite(path: Path, table: str, csv_text: str) -> int:
    """CSV 한 덩어리를 테이블 하나로 적재하고 행 수를 돌려준다."""
    # newline=""로 본문에 들어 있는 줄바꿈을 psql이 준 그대로 보존한다.
    reader = csv.reader(io.StringIO(csv_text, newline=""))
    header = next(reader)
    columns = ", ".join(
        f'"{name}" {"BLOB" if name in VECTOR_COLUMNS else "INTEGER" if name in INTEGER_COLUMNS else "TEXT"}'
        for name in header
    )
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            f"CREATE TABLE {table} ({columns}, PRIMARY KEY ({PRIMARY_KEYS[table]}))"
        )
        with connection:
            connection.executemany(
                f"INSERT INTO {table} VALUES ({', '.join('?' * len(header))})",
                (
                    [cell(column, value) for column, value in zip(header, row)]
                    for row in reader
                ),
            )
        return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        connection.close()


def ocr_breakdown(path: Path) -> dict[str, int]:
    connection = sqlite3.connect(path)
    try:
        return dict(
            connection.execute("SELECT ocr_status, COUNT(*) FROM job_postings GROUP BY 1")
        )
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", default="jobis-data-pipeline-postgres-1")
    parser.add_argument("--user", default="postgres")
    parser.add_argument("--database", default="jobrag")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    try:
        counts = {
            table: build_sqlite(
                temporary,
                table,
                dump_csv(args.container, args.user, args.database, table),
            )
            for table in PRIMARY_KEYS
        }
        os.replace(temporary, args.output)
    finally:
        temporary.unlink(missing_ok=True)

    print(
        "[export_sqlite] status=completed "
        + " ".join(f"{table}={count}" for table, count in counts.items())
        + " ocr("
        + " ".join(f"{status}={count}" for status, count in sorted(ocr_breakdown(args.output).items()))
        + f") output={args.output} size={args.output.stat().st_size / 1e6:.1f}MB",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
