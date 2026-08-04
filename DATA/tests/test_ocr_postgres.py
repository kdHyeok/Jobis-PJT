from __future__ import annotations

import sys
import unittest
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DATA_DIR))

import ocr_postgres  # noqa: E402


class OcrPostgresTest(unittest.TestCase):
    def test_claim_is_atomic_and_skips_locked_rows(self) -> None:
        self.assertIn("FOR UPDATE SKIP LOCKED", ocr_postgres.CLAIM_SQL)
        self.assertIn("ocr_attempt_count < %s", ocr_postgres.CLAIM_SQL)
        self.assertIn("ocr_lease_until", ocr_postgres.CLAIM_SQL)
        self.assertIn("RETURNING posting.source", ocr_postgres.CLAIM_SQL)

    def test_retry_delay_uses_capped_exponential_backoff(self) -> None:
        self.assertEqual(60, ocr_postgres.retry_delay_minutes(1, 60))
        self.assertEqual(120, ocr_postgres.retry_delay_minutes(2, 60))
        self.assertEqual(1440, ocr_postgres.retry_delay_minutes(10, 60))

    def test_all_airflow_sites_map_to_database_sources(self) -> None:
        self.assertEqual(
            {"잡코리아", "사람인", "원티드", "인크루트", "고용24"},
            set(ocr_postgres.SOURCE_BY_SITE.values()),
        )


if __name__ == "__main__":
    unittest.main()
