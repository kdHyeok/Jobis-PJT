from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

RAG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAG_ROOT))

from jobrag import store
from jobrag.model_config import LOCAL_EMBED_MODEL, get_model_settings
from jobrag.schema import Chunk


class _Cursor:
    def __init__(self, connection):
        self.connection = connection
        self._row = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, _params=None):
        self.connection.statements.append(sql)
        if "count(DISTINCT c.posting_uid)" in sql:
            self._row = (self.connection.uncovered_postings,)

    def fetchone(self):
        return self._row


class _Connection:
    def __init__(self, uncovered_postings: int):
        self.uncovered_postings = uncovered_postings
        self.statements: list[str] = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return _Cursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class StoreProfileSafetyTest(unittest.TestCase):
    def setUp(self):
        self._saved = {
            key: os.environ.get(key)
            for key in ("RAG_EMBED_PROVIDER", "RAG_RERANK_PROVIDER", "GMS_KEY")
        }
        os.environ.update(
            {
                "RAG_EMBED_PROVIDER": "gms",
                "RAG_RERANK_PROVIDER": "none",
                "GMS_KEY": "test-only",
            }
        )
        get_model_settings.cache_clear()
        self.chunk = Chunk(
            chunk_id="source:1:full",
            posting_uid="source:1",
            part="full",
            text="posting text",
            tokens=2,
        )

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_model_settings.cache_clear()

    @staticmethod
    def _local_profile():
        return ("local", LOCAL_EMBED_MODEL, 1024)

    def test_provider_switch_rejects_partial_active_corpus(self):
        connection = _Connection(uncovered_postings=1)
        with (
            patch.object(store, "existing_hashes", return_value={}),
            patch.object(store, "get_index_profile", return_value=self._local_profile()),
        ):
            with self.assertRaisesRegex(RuntimeError, "does not cover 1 active"):
                store.upsert_chunks(connection, [self.chunk], [[0.1] * 1024])

        self.assertEqual(connection.rollbacks, 1)
        self.assertEqual(connection.commits, 0)

    def test_provider_switch_rolls_back_any_failed_replacement(self):
        connection = _Connection(uncovered_postings=0)
        with (
            patch.object(store, "existing_hashes", return_value={}),
            patch.object(store, "get_index_profile", return_value=self._local_profile()),
        ):
            with self.assertRaisesRegex(RuntimeError, "replacement vectors failed"):
                store.upsert_chunks(connection, [self.chunk], [None])

        self.assertEqual(connection.rollbacks, 1)
        self.assertEqual(connection.commits, 0)

    def test_successful_switch_publishes_profile_and_cleanup_atomically(self):
        connection = _Connection(uncovered_postings=0)
        with (
            patch.object(store, "existing_hashes", return_value={}),
            patch.object(store, "get_index_profile", return_value=self._local_profile()),
            patch.object(store, "delete_orphan_chunks", return_value=2) as delete,
            patch.object(store, "_record_index_profile") as record,
        ):
            result = store.upsert_chunks(
                connection,
                [self.chunk],
                [[0.1] * 1024],
            )

        delete.assert_called_once_with(
            connection,
            ["source:1"],
            ["source:1:full"],
            commit=False,
        )
        record.assert_called_once()
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)
        self.assertEqual(result["orphans_deleted"], 2)


if __name__ == "__main__":
    unittest.main()
