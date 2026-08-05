from __future__ import annotations

import hashlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

RAG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAG_ROOT))

from jobrag import embedding, reranker
from jobrag.model_config import (
    GMS_EMBED_MODEL,
    GMS_RERANK_MODEL,
    LOCAL_EMBED_MODEL,
    LOCAL_RERANK_MODEL,
    get_model_settings,
)


_ENV_KEYS = {
    "GMS_KEY",
    "RAG_EMBED_PROVIDER",
    "RAG_RERANK_PROVIDER",
    "RAG_EMBED_MODEL",
    "RAG_RERANK_MODEL",
    "RAG_LOCAL_EMBED_MODEL",
    "RAG_GMS_EMBED_MODEL",
    "RAG_LOCAL_RERANK_MODEL",
    "RAG_GMS_RERANK_MODEL",
    "RAG_VECTOR_DIMENSIONS",
    "RAG_GMS_OPENAI_BASE_URL",
    "RAG_GMS_TIMEOUT_SECONDS",
    "RAG_GMS_MAX_RETRIES",
    "RAG_GMS_RERANK_BATCH_SIZE",
    "RAG_GMS_RERANK_MAX_CHARS",
    "RAG_LOCAL_CPU_THREADS",
    "RAG_EMBED_BATCH_SIZE",
    "RAG_INGEST_WINDOW_SIZE",
    "RAG_LOCAL_RERANK_BATCH_SIZE",
}


class ModelProviderTest(unittest.TestCase):
    def setUp(self):
        self._saved = {key: os.environ.get(key) for key in _ENV_KEYS}
        for key in _ENV_KEYS:
            os.environ.pop(key, None)
        self._reset()

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._reset()

    @staticmethod
    def _reset():
        get_model_settings.cache_clear()
        embedding._model = None
        embedding._client = None
        embedding._loaded_key = None
        reranker._model = None
        reranker._backend = "unavailable"
        reranker._loaded_key = None

    def test_defaults_preserve_existing_local_models_and_hashes(self):
        settings = get_model_settings()
        self.assertEqual(settings.embed_provider, "local")
        self.assertEqual(settings.embed_model, LOCAL_EMBED_MODEL)
        self.assertEqual(settings.rerank_provider, "local")
        self.assertEqual(settings.rerank_model, LOCAL_RERANK_MODEL)
        self.assertEqual(settings.local_cpu_threads, 2)
        self.assertEqual(settings.embed_batch_size, 8)
        self.assertEqual(settings.ingest_window_size, 64)
        self.assertEqual(settings.local_rerank_batch_size, 4)
        self.assertEqual(
            embedding.content_hash("same text"),
            hashlib.sha1(b"same text").hexdigest(),
        )

    def test_switching_providers_selects_gms_models_and_changes_hash(self):
        os.environ.update(
            {
                "RAG_EMBED_PROVIDER": "gms",
                "RAG_RERANK_PROVIDER": "gms",
                "GMS_KEY": "test-only",
            }
        )
        get_model_settings.cache_clear()
        settings = get_model_settings()
        self.assertEqual(settings.embed_model, GMS_EMBED_MODEL)
        self.assertEqual(settings.rerank_model, GMS_RERANK_MODEL)
        self.assertNotEqual(
            embedding.content_hash("same text"),
            hashlib.sha1(b"same text").hexdigest(),
        )

    def test_gms_provider_requires_key(self):
        os.environ["RAG_EMBED_PROVIDER"] = "gms"
        get_model_settings.cache_clear()
        with self.assertRaisesRegex(RuntimeError, "GMS_KEY"):
            get_model_settings()

    def test_schema_dimension_is_guarded(self):
        os.environ["RAG_VECTOR_DIMENSIONS"] = "1536"
        get_model_settings.cache_clear()
        with self.assertRaisesRegex(RuntimeError, r"VECTOR\(1024\)"):
            get_model_settings()

    def test_ingest_window_cannot_be_smaller_than_embedding_batch(self):
        os.environ["RAG_EMBED_BATCH_SIZE"] = "16"
        os.environ["RAG_INGEST_WINDOW_SIZE"] = "8"
        get_model_settings.cache_clear()
        with self.assertRaisesRegex(RuntimeError, "greater than or equal"):
            get_model_settings()

    def test_gms_embeddings_restore_order_validate_dimension_and_normalize(self):
        os.environ.update(
            {
                "RAG_EMBED_PROVIDER": "gms",
                "RAG_RERANK_PROVIDER": "none",
                "GMS_KEY": "test-only",
            }
        )
        get_model_settings.cache_clear()

        class Item:
            def __init__(self, index: int, value: float):
                self.index = index
                self.embedding = [value] * 1024

        class Embeddings:
            def create(self, **kwargs):
                self.kwargs = kwargs
                return type("Response", (), {"data": [Item(1, 2.0), Item(0, 1.0)]})()

        class Client:
            def __init__(self):
                self.embeddings = Embeddings()

        client = Client()
        embedding._client = client
        embedding._loaded_key = ("gms", GMS_EMBED_MODEL)
        vectors, stats = embedding.embed_texts(["a", "b"], batch_size=2)

        self.assertEqual(stats, {"attempted": 2, "succeeded": 2, "failed": 0})
        self.assertEqual(len(vectors), 2)
        self.assertEqual(len(vectors[0]), 1024)
        self.assertAlmostEqual(sum(value * value for value in vectors[0]), 1.0, places=5)
        self.assertEqual(client.embeddings.kwargs["dimensions"], 1024)

    def test_gms_reranker_scores_are_reordered_by_index(self):
        content = '{"scores":[{"index":1,"score":0.2},{"index":0,"score":0.9}]}'
        self.assertEqual(reranker._parse_scores(content, 2), [0.9, 0.2])

    def test_permanent_gms_error_aborts_without_retrying_remaining_batches(self):
        os.environ.update(
            {
                "RAG_EMBED_PROVIDER": "gms",
                "RAG_RERANK_PROVIDER": "none",
                "GMS_KEY": "test-only",
            }
        )
        get_model_settings.cache_clear()

        class TokenExhaustedError(Exception):
            status_code = 401

        embedding._client = object()
        embedding._loaded_key = ("gms", GMS_EMBED_MODEL)
        with patch.object(
            embedding,
            "_encode_batch",
            side_effect=TokenExhaustedError("no token left"),
        ) as encode:
            with self.assertRaisesRegex(RuntimeError, "cannot continue"):
                embedding.embed_texts(["a", "b", "c"], batch_size=1)

        encode.assert_called_once()

    def test_gms_reranker_rejects_incomplete_response(self):
        with self.assertRaisesRegex(RuntimeError, "1 scores for 2"):
            reranker._parse_scores(
                '{"scores":[{"index":0,"score":0.9}]}',
                2,
            )

    def test_none_reranker_preserves_rrf_fallback(self):
        os.environ["RAG_RERANK_PROVIDER"] = "none"
        get_model_settings.cache_clear()
        self.assertIsNone(reranker.rerank("query", [("posting", "text")]))
        self.assertEqual(reranker.backend(), "none")

    def test_local_reranker_uses_configured_batch_size(self):
        class Model:
            def predict(self, pairs, **kwargs):
                self.pairs = pairs
                self.kwargs = kwargs
                return [0.75] * len(pairs)

        model = Model()
        reranker._model = model
        reranker._backend = "local:test(cpu)"
        reranker._loaded_key = ("local", LOCAL_RERANK_MODEL)

        scores = reranker.rerank("query", [("posting", "text")])

        self.assertEqual(scores, [0.75])
        self.assertEqual(model.kwargs["batch_size"], 4)
        self.assertFalse(model.kwargs["show_progress_bar"])


if __name__ == "__main__":
    unittest.main()
