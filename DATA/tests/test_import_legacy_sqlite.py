from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DATA_DIR))

import import_legacy_sqlite  # noqa: E402


LEGACY_SCHEMA = """
CREATE TABLE job_postings (
    source TEXT, posting_id TEXT, company TEXT, title TEXT, url TEXT,
    employment_type TEXT, experience TEXT, education TEXT, location TEXT,
    posted_date TEXT, deadline TEXT, detail_text TEXT, image_urls TEXT,
    need_ocr TEXT, collected_at TEXT
)
"""


def row(
    source: str,
    posting_id: str,
    company: str,
    title: str,
    detail_text: str,
    need_ocr: str = "X",
    image_urls: object | None = None,
) -> tuple:
    return (
        source,
        posting_id,
        company,
        title,
        f"https://example.test/{posting_id}",
        "정규직",
        "경력",
        "학력무관",
        "서울",
        "2026-07-01",
        "2026-08-31",
        detail_text,
        json.dumps(image_urls or [], ensure_ascii=False),
        need_ocr,
        "2026-07-28T00:00:00+00:00",
    )


class ImportLegacySqliteTest(unittest.TestCase):
    def make_db(self, rows: list[tuple]) -> tuple[tempfile.TemporaryDirectory, Path]:
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / "legacy.db"
        connection = sqlite3.connect(path)
        try:
            connection.execute(LEGACY_SCHEMA)
            connection.executemany(
                "INSERT INTO job_postings VALUES (" + ",".join("?" for _ in range(15)) + ")",
                rows,
            )
            connection.commit()
        finally:
            connection.close()
        return directory, path

    def test_prepares_completed_and_pending_rows_and_deduplicates_cross_source(self) -> None:
        directory, path = self.make_db(
            [
                row("잡코리아", "1", "테스트", "백엔드 개발자", "완료 본문"),
                row("고용24", "2", "테스트", "백엔드 개발자", "더 긴 완료 본문입니다"),
                row("사람인", "3", "대기 회사", "OCR 대기", "", "O", ["https://img"]),
            ]
        )
        self.addCleanup(directory.cleanup)

        prepared, stats = import_legacy_sqlite.prepare_rows(path)

        self.assertEqual(2, len(prepared))
        self.assertEqual({"2", "3"}, {prepared_row["posting_id"] for prepared_row in prepared})
        self.assertEqual(3, stats["input_records"])
        self.assertEqual(2, stats["completed_records"])
        self.assertEqual(1, stats["ocr_pending_records"])
        self.assertEqual(0, stats["ocr_or_empty_excluded"])
        self.assertEqual(1, stats["duplicates_removed"])
        self.assertEqual(2, stats["ready_to_upsert"])

    def test_renders_staged_preserve_existing_upsert_and_verification(self) -> None:
        directory, path = self.make_db(
            [row("잡코리아", "1", "테스트", "백엔드 개발자", "레거시 본문")]
        )
        self.addCleanup(directory.cleanup)
        prepared, _ = import_legacy_sqlite.prepare_rows(path)

        sql = import_legacy_sqlite.render_import_sql(prepared, commit=False)
        verify_sql = import_legacy_sqlite.render_verify_sql(prepared)

        self.assertIn("CREATE TEMP TABLE legacy_job_postings_stage", sql)
        self.assertIn("ON CONFLICT (source, posting_id) DO UPDATE SET", sql)
        self.assertIn("COALESCE(existing.company, EXCLUDED.company)", sql)
        self.assertIn("NULLIF(BTRIM(existing.detail_text), '') IS NULL", sql)
        self.assertIn("ocr_status", sql)
        self.assertTrue(sql.rstrip().endswith("ROLLBACK;"))
        self.assertIn("legacy_job_postings_expected", verify_sql)
        self.assertIn("missing or invalid loaded rows", verify_sql)

    def test_rejects_invalid_image_urls_json(self) -> None:
        bad = list(row("잡코리아", "1", "테스트", "백엔드", "본문"))
        bad[12] = "not-json"
        directory, path = self.make_db([tuple(bad)])
        self.addCleanup(directory.cleanup)

        with self.assertRaisesRegex(SystemExit, "image_urls JSON"):
            import_legacy_sqlite.prepare_rows(path)


if __name__ == "__main__":
    unittest.main()
