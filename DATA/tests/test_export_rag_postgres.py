from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DATA_DIR))

import export_rag_postgres  # noqa: E402


class ExportRagPostgresTest(unittest.TestCase):
    def test_query_exports_only_completed_rows(self) -> None:
        sql = export_rag_postgres.SELECT_COMPLETED_SQL
        self.assertIn("need_ocr = 'X'", sql)
        self.assertIn("NULLIF(BTRIM(detail_text), '') IS NOT NULL", sql)
        self.assertNotIn("ocr_last_error", sql)

    def test_dates_are_json_serialized_as_iso_8601(self) -> None:
        self.assertEqual("2026-08-04", export_rag_postgres.json_value(date(2026, 8, 4)))
        value = datetime(2026, 8, 4, 1, 2, 3, tzinfo=timezone.utc)
        self.assertEqual("2026-08-04T01:02:03+00:00", export_rag_postgres.json_value(value))


if __name__ == "__main__":
    unittest.main()
