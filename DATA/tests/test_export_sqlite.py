from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from array import array
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DATA_DIR))

import export_sqlite  # noqa: E402


CSV = (
    "source,posting_id,detail_text,ocr_status,ocr_last_error,ocr_attempt_count\n"
    '사람인,1,"첫 줄\n둘째 줄",succeeded,\\N,0\n'
    '잡코리아,2,"",pending,"timeout, retry",3\n'
)


CHUNKS_CSV = (
    "chunk_id,posting_uid,tokens,embedding\n"
    "c1,사람인:1,12,\"[0.5,-0.25,0.125]\"\n"
    "c2,사람인:1,7,\\N\n"
)


class ExportSqliteTest(unittest.TestCase):
    def test_null_token_and_empty_string_stay_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.db"
            self.assertEqual(2, export_sqlite.build_sqlite(path, "job_postings", CSV))
            connection = sqlite3.connect(path)
            rows = dict(
                (row[0], row[1:])
                for row in connection.execute(
                    "SELECT posting_id, detail_text, ocr_last_error, ocr_attempt_count,"
                    " typeof(ocr_attempt_count) FROM job_postings"
                )
            )
            connection.close()

        # 본문 줄바꿈은 보존하고, \N은 NULL로, 빈 문자열은 빈 문자열로 남긴다.
        self.assertEqual(("첫 줄\n둘째 줄", None, 0, "integer"), rows["1"])
        self.assertEqual(("", "timeout, retry", 3, "integer"), rows["2"])

    def test_breakdown_counts_by_ocr_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.db"
            export_sqlite.build_sqlite(path, "job_postings", CSV)
            self.assertEqual(
                {"succeeded": 1, "pending": 1}, export_sqlite.ocr_breakdown(path)
            )

    def test_embedding_round_trips_as_float32_blob(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.db"
            self.assertEqual(2, export_sqlite.build_sqlite(path, "chunks", CHUNKS_CSV))
            connection = sqlite3.connect(path)
            rows = dict(connection.execute("SELECT chunk_id, embedding FROM chunks"))
            connection.close()

        # pgvector는 float4를 저장하므로 float32 BLOB 왕복에서 값이 그대로 나온다.
        self.assertEqual([0.5, -0.25, 0.125], array("f", rows["c1"]).tolist())
        self.assertIsNone(rows["c2"])


if __name__ == "__main__":
    unittest.main()
