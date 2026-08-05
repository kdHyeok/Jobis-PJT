"""Regression coverage for an empty production RAG corpus."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

RAG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAG_ROOT))

from jobrag import search


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, _sql, _params=None):
        return None

    def fetchall(self):
        return self._rows


class _Connection:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return _Cursor(self._rows)


class EmptyBm25Test(unittest.TestCase):
    def tearDown(self):
        search._bm25_cache = None

    def test_empty_chunk_table_builds_a_safe_empty_cache(self):
        search._bm25_cache = None

        index = search._load_bm25_index(_Connection([]))

        self.assertIsNone(index["bm25"])
        self.assertEqual(index["chunks"], [])

    def test_empty_corpus_returns_no_lexical_candidates(self):
        search._bm25_cache = None
        spec = SimpleNamespace(text="backend developer")

        result = search._bm25_axis(_Connection([]), spec, ())

        self.assertEqual(result, [])

    def test_text_without_searchable_tokens_is_also_safe(self):
        search._bm25_cache = None

        index = search._load_bm25_index(
            _Connection([("posting-1", "chunk-1", "!!!")])
        )

        self.assertIsNone(index["bm25"])
        self.assertEqual(index["chunks"], [("posting-1", "chunk-1")])


if __name__ == "__main__":
    unittest.main()
