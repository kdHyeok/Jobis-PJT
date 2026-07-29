"""RagAdapter.search 수동 테스트용 웹 서버.

find_alternatives 훅(jobrag/rag_adapter.py)을 브라우저에서 직접 두드려보기 위한
전용 서버 — webapp/server.py(일반 검색+생성 테스트)와는 별개 경로다.
사용: python webapp/rag_adapter_server.py [--port 8770]
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg
from pgvector.psycopg import register_vector

from jobrag.rag_adapter import search_with_reasons as rag_search
from jobrag.store import connect

STATIC_DIR = Path(__file__).resolve().parent

_conn = None


def _ensure_conn():
    """살아있는 커넥션을 반환. 끊겼으면 재연결 — 다른 스크립트의 idle 세션 종료 등으로
    커넥션이 죽는 사고를 이미 한 번 겪었으므로(운영 중 락 해제 작업), 여기선 방어한다."""
    global _conn
    if _conn is not None:
        try:
            with _conn.cursor() as cur:
                cur.execute("SELECT 1")
            return _conn
        except psycopg.OperationalError:
            _conn = None
    _conn = connect()
    register_vector(_conn)
    return _conn


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            html = (STATIC_DIR / "rag_adapter_index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/api/rag-search":
            self._send_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            sub_roles = body.get("sub_roles") or []
            top_k = int(body.get("top_k") or 3)
            if not (1 <= len(sub_roles) <= 6):
                self._send_json(400, {"error": "sub_roles는 1개 이상 6개 이하"})
                return

            conn = _ensure_conn()
            t0 = time.perf_counter()
            results = rag_search(conn, sub_roles, top_k)
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)

            self._send_json(200, {
                "results": results,
                "reranked": False,  # rag_adapter는 use_rerank=False 고정
                "elapsed_ms": elapsed_ms,
            })
        except Exception:
            self._send_json(500, {"error": traceback.format_exc()})


def main():
    port = 8770
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    _ensure_conn()
    print(f"rag_adapter webapp: http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
