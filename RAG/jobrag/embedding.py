"""Dense embedding provider used by both ingestion and online search.

``local`` keeps the existing BGE-M3 implementation. ``gms`` calls the
OpenAI-compatible embeddings endpoint exposed by SSAFY GMS.  Both paths emit
normalized 1024-dimensional vectors so the pgvector contract stays unchanged.
"""
from __future__ import annotations

import hashlib
import logging

import numpy as np

from .model_config import get_model_settings
from .runtime_limits import configure_local_cpu

_model = None
_client = None
_loaded_key: tuple[str, str] | None = None


def _load():
    global _model, _client, _loaded_key
    settings = get_model_settings()
    key = (settings.embed_provider, settings.embed_model)
    if _loaded_key == key:
        return _model if settings.embed_provider == "local" else _client

    _model = None
    _client = None
    if settings.embed_provider == "local":
        configure_local_cpu(settings.local_cpu_threads)
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(settings.embed_model)
        loaded = _model
    else:
        from openai import OpenAI

        _client = OpenAI(
            api_key=settings.gms_key,
            base_url=settings.gms_openai_base_url,
            timeout=settings.gms_timeout_seconds,
            max_retries=settings.gms_max_retries,
        )
        loaded = _client
    _loaded_key = key
    return loaded


def warmup() -> None:
    """Load local weights or validate and construct the GMS client.

    The GMS path deliberately does not issue a billable network request during
    startup.  Its first real request is the normal search or ingestion call.
    """

    _load()


def backend() -> str:
    settings = get_model_settings()
    return f"{settings.embed_provider}:{settings.embed_model}"


def embed_texts(
    texts: list[str], batch_size: int | None = None
) -> tuple[list[list[float] | None], dict]:
    """Return vectors and attempted/succeeded/failed counters.

    A failed batch is retried once by this layer.  The OpenAI client also uses
    its configured transport retries.  The legacy contract of returning
    ``None`` for failed items is retained for existing ingestion callers.
    """

    if not texts:
        return [], {"attempted": 0, "succeeded": 0, "failed": 0}
    if batch_size is None:
        batch_size = get_model_settings().embed_batch_size
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero")

    loaded = _load()
    out: list[list[float] | None] = [None] * len(texts)
    failed = 0
    for start in range(0, len(texts), batch_size):
        batch = texts[start:start + batch_size]
        idxs = list(range(start, start + len(batch)))
        vecs = _encode_with_retry(loaded, batch)
        if vecs is None:
            failed += len(batch)
            continue
        for i, vector in zip(idxs, vecs):
            out[i] = vector.tolist()
    stats = {
        "attempted": len(texts),
        "succeeded": len(texts) - failed,
        "failed": failed,
    }
    return out, stats


def _encode_with_retry(loaded, batch: list[str], retries: int = 1):
    for attempt in range(retries + 1):
        try:
            return _encode_batch(loaded, batch)
        except Exception as exc:  # noqa: BLE001 - retain the legacy soft-failure contract
            if _is_fatal_gms_error(exc):
                raise RuntimeError(
                    "GMS embedding request cannot continue; check the key, token "
                    "balance, model, and request configuration"
                ) from exc
            logging.getLogger(__name__).warning(
                "RAG embedding batch failed (provider=%s, attempt=%s/%s): %s",
                get_model_settings().embed_provider,
                attempt + 1,
                retries + 1,
                exc,
            )
            if attempt == retries:
                return None
    return None


def _is_fatal_gms_error(exc: Exception) -> bool:
    """Stop the whole ingest on permanent GMS errors instead of flooding it."""

    if get_model_settings().embed_provider != "gms":
        return False
    return getattr(exc, "status_code", None) in {400, 401, 403, 404}


def _encode_batch(loaded, batch: list[str]) -> np.ndarray:
    settings = get_model_settings()
    if settings.embed_provider == "local":
        vectors = loaded.encode(
            batch,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
    else:
        response = loaded.embeddings.create(
            model=settings.embed_model,
            input=batch,
            dimensions=settings.vector_dimensions,
        )
        items = sorted(response.data, key=lambda item: item.index)
        if len(items) != len(batch):
            raise RuntimeError(
                f"GMS embeddings returned {len(items)} vectors for {len(batch)} inputs"
            )
        vectors = np.asarray([item.embedding for item in items], dtype=np.float32)

    vectors = np.asarray(vectors, dtype=np.float32)
    expected = (len(batch), settings.vector_dimensions)
    if vectors.shape != expected:
        raise RuntimeError(
            f"Embedding shape mismatch: expected {expected}, got {vectors.shape}"
        )
    if not np.isfinite(vectors).all():
        raise RuntimeError("Embedding response contains non-finite values")

    # BGE is already normalized, while API providers may not guarantee it.
    # Normalizing both keeps pgvector cosine behaviour provider-independent.
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if np.any(norms == 0):
        raise RuntimeError("Embedding response contains a zero-length vector")
    return vectors / norms


def content_hash(text: str) -> str:
    """Hash text together with the effective embedding profile.

    The default local BGE-M3 profile intentionally retains the historical
    text-only hash, so existing indexes are not rebuilt after this upgrade.
    Switching provider, model, or dimensions changes every hash and therefore
    triggers a complete and safe re-embedding.
    """

    settings = get_model_settings()
    payload = text
    if not settings.uses_legacy_local_embedding:
        payload = f"{settings.embedding_fingerprint}\0{text}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()
