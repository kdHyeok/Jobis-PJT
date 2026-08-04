from __future__ import annotations

import sys
import unittest
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DATA_DIR))

import export_postgres  # noqa: E402


def sample_row(**overrides: object) -> dict:
    row = {
        "source": "test-source",
        "posting_id": "posting-1",
        "company": "테스트 회사",
        "title": "백엔드 개발자",
        "detail_text": "새 OCR 본문",
        "image_urls": ["https://example.test/posting.png"],
        "need_ocr": "X",
    }
    row.update(overrides)
    return row


class ExportPostgresTest(unittest.TestCase):
    def test_renders_guarded_upsert_for_ocr_body(self) -> None:
        sql = export_postgres.render_sql([sample_row()])

        self.assertIn("ON CONFLICT (source, posting_id) DO UPDATE SET", sql)
        self.assertIn("NULLIF(BTRIM(EXCLUDED.detail_text), '') IS NOT NULL", sql)
        self.assertIn("ELSE job_postings.detail_text", sql)
        self.assertIn("ELSE job_postings.text_source", sql)
        self.assertIn("ELSE job_postings.need_ocr", sql)
        self.assertIn("ocr_status", sql)
        self.assertIn("EXCLUDED.image_urls IS DISTINCT FROM job_postings.image_urls", sql)
        self.assertNotIn("CREATE TABLE", sql)
        self.assertNotIn("DO NOTHING", sql)

    def test_rejects_duplicate_primary_key_in_same_batch(self) -> None:
        with self.assertRaisesRegex(SystemExit, "중복 PK"):
            export_postgres.render_sql([sample_row(), sample_row(title="중복")])

    def test_rejects_missing_primary_key(self) -> None:
        with self.assertRaisesRegex(SystemExit, "필수 PK"):
            export_postgres.render_sql([sample_row(posting_id=None)])

    def test_text_source_distinguishes_ocr_original_and_none(self) -> None:
        self.assertEqual("ocr", export_postgres.text_source_of(sample_row()))
        self.assertEqual(
            "original",
            export_postgres.text_source_of(sample_row(image_urls=[])),
        )
        self.assertEqual(
            "none",
            export_postgres.text_source_of(sample_row(detail_text="", need_ocr="O")),
        )

    def test_pending_row_is_kept_for_database_ocr_queue(self) -> None:
        pending = export_postgres.normalize_row_for_load(
            sample_row(detail_text="", need_ocr="X", image_urls=["https://example.test/image.png"])
        )

        self.assertEqual("O", pending["need_ocr"])
        self.assertEqual("pending", export_postgres.ocr_status_of(pending))
        sql = export_postgres.render_sql([pending])
        self.assertIn("'O', 'pending'", sql)

    def test_pending_without_images_is_dead_instead_of_unclaimable_pending(self) -> None:
        pending = export_postgres.normalize_row_for_load(
            sample_row(detail_text="", need_ocr="O", image_urls=[])
        )
        self.assertEqual("dead", export_postgres.ocr_status_of(pending))


if __name__ == "__main__":
    unittest.main()
