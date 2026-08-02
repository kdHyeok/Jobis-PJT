"""RAG 툴 서버 — AI Agent가 Tool로 호출하는 명세서 계약 진입점 (FastAPI).

명세서(RAG_입출력_명세서.md) 계약을 HTTP로 노출한다:
  POST /search  body {"input": <직업명 str | profile dict | {title, profile}>,
                      "top_k": 3, "evaluate": null, "use_rerank": true}
             → spec_adapter.search() 결과 그대로 ({"postings": [...]})
  GET  /health → {"status": "ok", "warm": bool}

기동 시 warmup(임베딩·리랭커·BM25)을 수행해 첫 툴 호출 지연을 없앤다.
spec_adapter.search는 예외를 내보내지 않으므로(계약) 이 서버도 5xx 대신
{"postings": []}로 응답한다 — 에이전트 툴이 죽지 않게.

사용: python -m uvicorn webapp.tool_server:app --host 127.0.0.1 --port 8765
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from pgvector.psycopg import register_vector
from pydantic import BaseModel

from jobrag import spec_adapter
from jobrag.store import connect

app = FastAPI(title="jobrag tool server")

# 단일 커넥션 + 락 — psycopg3 커넥션은 스레드 안전하지 않다.
# (모델·BM25 전역 캐시는 warmup 후 read-only라 락 불필요)
_conn = None
_lock = threading.Lock()
_warm = False


def _ensure_conn():
    """커넥션이 없거나 죽었으면 재연결한다 (rag_adapter_server와 동일한 관례)."""
    global _conn
    if _conn is None or _conn.closed:
        _conn = connect()
        register_vector(_conn)
        return _conn
    try:
        with _conn.cursor() as cur:
            cur.execute("SELECT 1")
    except Exception:
        try:
            _conn.close()
        except Exception:
            pass
        _conn = connect()
        register_vector(_conn)
    return _conn


@app.on_event("startup")
def _warmup():
    global _warm
    t0 = time.time()
    from jobrag import embedding, reranker, search
    embedding.warmup()
    reranker.warmup()
    # 커넥션은 **모델 로딩 뒤에** 연다(2026-08-01 수정). 전에는 로딩 전에 열어 두고 여기서
    # 썼는데, 로딩이 몇 분 걸리는 동안 커넥션이 유휴로 방치돼 끊겼다:
    #   psycopg.OperationalError: ... Software caused connection abort (10053)
    # WSL 안의 PostgreSQL 에 Windows 에서 붙는 구성에서 재현됐지만(localhost 릴레이가 유휴
    # 연결을 끊는다) 원인은 환경이 아니라 **몇 분짜리 유휴 커넥션을 들고 있는 것**이다.
    # `_ensure_conn` 은 이미 죽은 커넥션을 되살리는 로직을 갖고 있으니 호출 위치만 옮긴다.
    conn = _ensure_conn()
    search._load_bm25_index(conn)  # 프로세스당 1회 빌드 — 여기서 미리 낸다
    _warm = True
    # cp949 콘솔에서도 안 깨지게 ASCII만 쓴다
    print(f"[tool_server] warmup done ({time.time() - t0:.1f}s) - ready")


class SearchRequest(BaseModel):
    input: Any                      # 명세서 §2: 직업명(str) / profile(dict) / {title, profile}
    top_k: int = 3
    evaluate: bool | None = None    # None → JOBRAG_EVALUATOR 환경변수 따름
    use_rerank: bool = True


@app.get("/health")
def health():
    return {"status": "ok", "warm": _warm}


@app.post("/search")
def search(req: SearchRequest):
    with _lock:
        try:
            conn = _ensure_conn()
            return spec_adapter.search(conn, req.input, top_k=req.top_k,
                                       use_rerank=req.use_rerank,
                                       evaluate=req.evaluate)
        except Exception:                       # noqa: BLE001 — 계약: 예외 금지
            return {"postings": []}
