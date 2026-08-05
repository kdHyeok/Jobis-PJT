"""AI Agent가 호출하는 RAG 검색 계약 서버.

POST /search는 AI/src/jobis_ai/rag.py의 HttpRagAdapter 계약을 그대로 제공한다.
Airflow가 postings/chunks를 갱신하면 DB 서명을 비교해 인메모리 BM25 인덱스도
다음 요청 전에 자동으로 다시 만든다.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field

from jobrag import search as search_engine
from jobrag import spec_adapter
from jobrag.store import ensure_index_compatible, get_dsn

app = FastAPI(title="jobrag tool server")

_pool: ConnectionPool | None = None
_lock = threading.Lock()
_warm = False
_corpus_signature: tuple[int, object] | None = None


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            get_dsn(),
            min_size=2,
            max_size=10,
            configure=register_vector,
            kwargs={"autocommit": True},
        )
    return _pool


def _read_corpus_signature(conn) -> tuple[int, object]:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*), MAX(c.updated_at)
            FROM chunks c
            JOIN postings p ON p.uid = c.posting_uid
            WHERE p.is_active
            """
        )
        count, updated_at = cursor.fetchone()
    return int(count), updated_at


def _refresh_bm25_if_changed(conn) -> tuple[int, object]:
    global _corpus_signature
    signature = _read_corpus_signature(conn)
    if signature != _corpus_signature:
        ensure_index_compatible(conn)
        search_engine._bm25_cache = None
        search_engine._load_bm25_index(conn)
        _corpus_signature = signature
        logging.getLogger(__name__).info("BM25 index refreshed: %s", signature)
    return signature


class SearchRequest(BaseModel):
    input: Any
    top_k: int = Field(default=3, ge=1, le=20)
    evaluate: bool | None = None
    use_rerank: bool = True


@app.on_event("startup")
def startup() -> None:
    global _warm
    started = time.time()
    from jobrag import embedding, reranker

    embedding.warmup()
    reranker.warmup()
    with _get_pool().connection() as conn:
        _refresh_bm25_if_changed(conn)
    _warm = True
    print(f"[tool_server] warmup done ({time.time() - started:.1f}s) - ready", flush=True)


@app.on_event("shutdown")
def shutdown() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@app.get("/health")
def health() -> dict:
    from jobrag import embedding, reranker

    return {
        "status": "ok",
        "warm": _warm,
        "corpus_chunks": _corpus_signature[0] if _corpus_signature else 0,
        "embedding_backend": embedding.backend(),
        "reranker_backend": reranker.backend(),
    }


@app.post("/search")
def search(request: SearchRequest) -> dict:
    with _lock:
        try:
            with _get_pool().connection() as conn:
                _refresh_bm25_if_changed(conn)
                result = spec_adapter.search(
                    conn,
                    request.input,
                    top_k=request.top_k,
                    use_rerank=request.use_rerank,
                )
            if request.evaluate:
                result.setdefault("warnings", []).append(
                    "현재 main RAG 검색 서버는 evaluate=true를 지원하지 않습니다."
                )
            return result
        except Exception:  # AI 검색 실패가 전체 에이전트 실행을 중단하면 안 된다.
            logging.getLogger(__name__).exception("RAG search failed")
            return {"postings": []}
