"""Environment-backed model selection for the RAG index and search service.

The local providers remain the defaults so existing installations keep their
current behaviour.  GMS uses its OpenAI-compatible endpoint for embeddings and
chat completions.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


LOCAL_EMBED_MODEL = "BAAI/bge-m3"
LOCAL_RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
GMS_EMBED_MODEL = "text-embedding-3-large"
GMS_RERANK_MODEL = "gpt-4.1-mini"
VECTOR_DIMENSIONS = 1024


def _positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero")
    return value


def _positive_float(name: str, default: float) -> float:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number, got {raw!r}") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero")
    return value


@dataclass(frozen=True)
class ModelSettings:
    embed_provider: str
    embed_model: str
    vector_dimensions: int
    rerank_provider: str
    rerank_model: str
    local_cpu_threads: int
    embed_batch_size: int
    ingest_window_size: int
    local_rerank_batch_size: int
    gms_key: str
    gms_openai_base_url: str
    gms_timeout_seconds: float
    gms_max_retries: int
    gms_rerank_batch_size: int
    gms_rerank_max_chars: int

    @property
    def embedding_fingerprint(self) -> str:
        return f"{self.embed_provider}:{self.embed_model}:{self.vector_dimensions}"

    @property
    def uses_legacy_local_embedding(self) -> bool:
        return (
            self.embed_provider == "local"
            and self.embed_model == LOCAL_EMBED_MODEL
            and self.vector_dimensions == VECTOR_DIMENSIONS
        )


@lru_cache(maxsize=1)
def get_model_settings() -> ModelSettings:
    embed_provider = os.environ.get("RAG_EMBED_PROVIDER", "local").strip().lower()
    rerank_provider = os.environ.get("RAG_RERANK_PROVIDER", "local").strip().lower()
    if embed_provider not in {"local", "gms"}:
        raise RuntimeError("RAG_EMBED_PROVIDER must be one of: local, gms")
    if rerank_provider not in {"local", "gms", "none"}:
        raise RuntimeError("RAG_RERANK_PROVIDER must be one of: local, gms, none")

    if embed_provider == "local":
        provider_embed_model = os.environ.get(
            "RAG_LOCAL_EMBED_MODEL", LOCAL_EMBED_MODEL
        )
    else:
        provider_embed_model = os.environ.get(
            "RAG_GMS_EMBED_MODEL", GMS_EMBED_MODEL
        )
    embed_model = os.environ.get("RAG_EMBED_MODEL", "").strip() or provider_embed_model

    if rerank_provider == "local":
        provider_rerank_model = os.environ.get(
            "RAG_LOCAL_RERANK_MODEL", LOCAL_RERANK_MODEL
        )
    elif rerank_provider == "gms":
        provider_rerank_model = os.environ.get(
            "RAG_GMS_RERANK_MODEL", GMS_RERANK_MODEL
        )
    else:
        provider_rerank_model = "none"
    rerank_model = (
        os.environ.get("RAG_RERANK_MODEL", "").strip() or provider_rerank_model
    )

    if not embed_model:
        raise RuntimeError("The selected RAG embedding model must not be empty")
    if not rerank_model:
        raise RuntimeError("The selected RAG reranking model must not be empty")

    vector_dimensions = _positive_int("RAG_VECTOR_DIMENSIONS", VECTOR_DIMENSIONS)
    if vector_dimensions != VECTOR_DIMENSIONS:
        raise RuntimeError(
            "RAG_VECTOR_DIMENSIONS must be 1024 because the current PostgreSQL "
            "schema uses VECTOR(1024)"
        )

    gms_key = os.environ.get("GMS_KEY", "").strip()
    if (embed_provider == "gms" or rerank_provider == "gms") and not gms_key:
        raise RuntimeError(
            "GMS_KEY is required when a RAG embedding or reranking provider is gms"
        )

    base_url = os.environ.get(
        "RAG_GMS_OPENAI_BASE_URL",
        "https://gms.ssafy.io/gmsapi/api.openai.com/v1",
    ).strip().rstrip("/")
    if not base_url:
        raise RuntimeError("RAG_GMS_OPENAI_BASE_URL must not be empty")

    local_cpu_threads = _positive_int("RAG_LOCAL_CPU_THREADS", 2)
    embed_batch_size = _positive_int("RAG_EMBED_BATCH_SIZE", 8)
    ingest_window_size = _positive_int("RAG_INGEST_WINDOW_SIZE", 64)
    if ingest_window_size < embed_batch_size:
        raise RuntimeError(
            "RAG_INGEST_WINDOW_SIZE must be greater than or equal to "
            "RAG_EMBED_BATCH_SIZE"
        )
    local_rerank_batch_size = _positive_int("RAG_LOCAL_RERANK_BATCH_SIZE", 4)

    return ModelSettings(
        embed_provider=embed_provider,
        embed_model=embed_model,
        vector_dimensions=vector_dimensions,
        rerank_provider=rerank_provider,
        rerank_model=rerank_model,
        local_cpu_threads=local_cpu_threads,
        embed_batch_size=embed_batch_size,
        ingest_window_size=ingest_window_size,
        local_rerank_batch_size=local_rerank_batch_size,
        gms_key=gms_key,
        gms_openai_base_url=base_url,
        gms_timeout_seconds=_positive_float("RAG_GMS_TIMEOUT_SECONDS", 60.0),
        gms_max_retries=_positive_int("RAG_GMS_MAX_RETRIES", 2),
        gms_rerank_batch_size=_positive_int("RAG_GMS_RERANK_BATCH_SIZE", 30),
        gms_rerank_max_chars=_positive_int("RAG_GMS_RERANK_MAX_CHARS", 1800),
    )
