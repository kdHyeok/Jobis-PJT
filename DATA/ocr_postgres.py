"""Claim OCR work from PostgreSQL and update the same job_postings rows.

Row failures are persisted as retry_wait/dead and do not fail the Airflow task.
Database/worker infrastructure failures still exit non-zero so Airflow can retry.
"""
from __future__ import annotations

import argparse
import os
import uuid

import enrich_ocr


SOURCE_BY_SITE = {
    "jobkorea": "잡코리아",
    "saramin": "사람인",
    "wanted": "원티드",
    "incruit": "인크루트",
    "work24": "고용24",
}

CLAIM_SQL = """
WITH candidate AS (
    SELECT source, posting_id
    FROM job_postings
    WHERE source = %s
      AND need_ocr = 'O'
      AND jsonb_array_length(image_urls) > 0
      AND ocr_attempt_count < %s
      AND (
          ocr_status = 'pending'
          OR (
              ocr_status = 'retry_wait'
              AND COALESCE(ocr_next_retry_at, '-infinity'::timestamptz) <= now()
          )
          OR (
              ocr_status = 'processing'
              AND COALESCE(ocr_lease_until, '-infinity'::timestamptz) <= now()
          )
      )
    ORDER BY COALESCE(ocr_next_retry_at, collected_at, '-infinity'::timestamptz), posting_id
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
UPDATE job_postings posting
SET ocr_status = 'processing',
    ocr_attempt_count = posting.ocr_attempt_count + 1,
    ocr_worker_id = %s,
    ocr_last_attempt_at = now(),
    ocr_lease_until = now() + (%s * INTERVAL '1 minute'),
    ocr_updated_at = now()
FROM candidate
WHERE posting.source = candidate.source
  AND posting.posting_id = candidate.posting_id
RETURNING posting.source, posting.posting_id, posting.company, posting.title,
          posting.image_urls, posting.ocr_attempt_count
"""

SUCCESS_SQL = """
UPDATE job_postings
SET detail_text = %s,
    text_source = 'ocr',
    need_ocr = 'X',
    ocr_status = 'succeeded',
    ocr_last_error = NULL,
    ocr_next_retry_at = NULL,
    ocr_lease_until = NULL,
    ocr_worker_id = NULL,
    ocr_updated_at = now()
WHERE source = %s
  AND posting_id = %s
  AND ocr_status = 'processing'
  AND ocr_worker_id = %s
"""

FAILURE_SQL = """
UPDATE job_postings
SET ocr_status = %s,
    ocr_last_error = %s,
    ocr_next_retry_at = CASE
        WHEN %s = 'retry_wait' THEN now() + (%s * INTERVAL '1 minute')
        ELSE NULL
    END,
    ocr_lease_until = NULL,
    ocr_worker_id = NULL,
    ocr_updated_at = now()
WHERE source = %s
  AND posting_id = %s
  AND ocr_status = 'processing'
  AND ocr_worker_id = %s
"""

EXHAUSTED_SQL = """
UPDATE job_postings
SET ocr_status = 'dead',
    ocr_last_error = COALESCE(ocr_last_error, 'lease_expired_after_max_attempts'),
    ocr_next_retry_at = NULL,
    ocr_lease_until = NULL,
    ocr_worker_id = NULL,
    ocr_updated_at = now()
WHERE source = %s
  AND need_ocr = 'O'
  AND ocr_attempt_count >= %s
  AND (
      ocr_status = 'retry_wait'
      OR (
          ocr_status = 'processing'
          AND COALESCE(ocr_lease_until, '-infinity'::timestamptz) <= now()
      )
  )
"""


def open_connection(dsn: str):
    import psycopg2

    return psycopg2.connect(dsn)


def retry_delay_minutes(attempt: int, base_minutes: int, cap_minutes: int = 1440) -> int:
    return min(base_minutes * (2 ** max(attempt - 1, 0)), cap_minutes)


def mark_exhausted(connection, source: str, max_attempts: int) -> int:
    with connection.cursor() as cursor:
        cursor.execute(EXHAUSTED_SQL, (source, max_attempts))
        count = cursor.rowcount
    connection.commit()
    return count


def claim_one(connection, source: str, max_attempts: int, worker_id: str,
              lease_minutes: int) -> dict | None:
    with connection.cursor() as cursor:
        cursor.execute(CLAIM_SQL, (source, max_attempts, worker_id, lease_minutes))
        row = cursor.fetchone()
        columns = [description.name for description in cursor.description] if row else []
    connection.commit()
    return dict(zip(columns, row)) if row else None


def mark_success(connection, row: dict, worker_id: str, text: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            SUCCESS_SQL,
            (text, row["source"], row["posting_id"], worker_id),
        )
        updated = cursor.rowcount == 1
    connection.commit()
    return updated


def mark_failure(connection, row: dict, worker_id: str, max_attempts: int,
                 base_minutes: int, error: str) -> tuple[str, int, bool]:
    attempt = int(row["ocr_attempt_count"])
    status = "dead" if attempt >= max_attempts else "retry_wait"
    delay = 0 if status == "dead" else retry_delay_minutes(attempt, base_minutes)
    with connection.cursor() as cursor:
        cursor.execute(
            FAILURE_SQL,
            (
                status,
                error[:2000],
                status,
                delay,
                row["source"],
                row["posting_id"],
                worker_id,
            ),
        )
        updated = cursor.rowcount == 1
    connection.commit()
    return status, delay, updated


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", choices=sorted(SOURCE_BY_SITE), required=True)
    parser.add_argument("--max", type=int, default=1, help="이번 실행의 최대 처리 행 수(0=무제한)")
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--retry-base-minutes", type=int, default=60)
    parser.add_argument("--lease-minutes", type=int, default=60)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--min-chars", type=int, default=250)
    parser.add_argument("--slice-height", type=int, default=2000)
    parser.add_argument("--overlap", type=int, default=150)
    parser.add_argument("--engine", choices=["auto", "paddle", "easy"], default="paddle")
    parser.add_argument("--gpu", action="store_true")
    args = parser.parse_args()
    if args.max < 0 or args.max_attempts < 1 or args.retry_base_minutes < 1 or args.lease_minutes < 1:
        parser.error("max는 0 이상, max-attempts/retry-base-minutes/lease-minutes는 1 이상이어야 합니다.")
    return args


def main() -> int:
    args = parse_args()
    dsn = os.environ.get("JOBRAG_PG_DSN")
    if not dsn:
        raise SystemExit("JOBRAG_PG_DSN 환경변수가 필요합니다.")

    source = SOURCE_BY_SITE[args.site]
    worker_id = f"{args.site}-{uuid.uuid4()}"
    connection = open_connection(dsn)
    claimed = filled = retry_wait = dead = lost_lease = 0
    try:
        exhausted = mark_exhausted(connection, source, args.max_attempts)
        if exhausted:
            print(f"[ocr_db] site={args.site} exhausted_to_dead={exhausted}", flush=True)

        while not args.max or claimed < args.max:
            row = claim_one(
                connection,
                source,
                args.max_attempts,
                worker_id,
                args.lease_minutes,
            )
            if row is None:
                break
            claimed += 1
            posting_id = str(row["posting_id"])
            try:
                text = enrich_ocr.ocr_posting(
                    row["image_urls"],
                    args.gpu,
                    args.slice_height,
                    args.overlap,
                    args.delay,
                    args.engine,
                )
                text = enrich_ocr.fix_common_ocr(enrich_ocr.clean_multiline(text))
                if not enrich_ocr.ocr_text_is_usable(text, args.min_chars):
                    raise ValueError(f"insufficient_ocr_text chars={len(text)}")
                if mark_success(connection, row, worker_id, text):
                    filled += 1
                    print(
                        f"[ocr_db] site={args.site} posting_id={posting_id} "
                        f"status=succeeded chars={len(text)} attempt={row['ocr_attempt_count']}",
                        flush=True,
                    )
                else:
                    lost_lease += 1
                    print(
                        f"[ocr_db] site={args.site} posting_id={posting_id} status=lost_lease",
                        flush=True,
                    )
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                status, delay, updated = mark_failure(
                    connection,
                    row,
                    worker_id,
                    args.max_attempts,
                    args.retry_base_minutes,
                    error,
                )
                if not updated:
                    lost_lease += 1
                    status = "lost_lease"
                elif status == "dead":
                    dead += 1
                else:
                    retry_wait += 1
                print(
                    f"[ocr_db] site={args.site} posting_id={posting_id} status={status} "
                    f"attempt={row['ocr_attempt_count']} retry_minutes={delay} "
                    f"error={type(exc).__name__}",
                    flush=True,
                )
    finally:
        connection.close()

    print(
        f"[ocr_db] site={args.site} status=completed claimed={claimed} filled={filled} "
        f"retry_wait={retry_wait} dead={dead} lost_lease={lost_lease}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
