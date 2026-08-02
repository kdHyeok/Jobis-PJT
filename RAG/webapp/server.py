"""테스트용 웹 서버 — http.server, 외부 의존 최소화(crag-pipeline 관례와 동일).

Evaluator 없음 — 검색(하이브리드+재순위) 결과를 그대로 GMS에 넘겨 1회 생성.
사용: python webapp/server.py [--port 8766] [--no-rerank]
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pgvector.psycopg import register_vector

from eval import harness
from jobrag.generate import generate_answer
from jobrag.query_parser import load_region_vocab, parse_query
from jobrag.search import hybrid_search
from jobrag.store import connect
from jobrag.tracing import new_trace_id, node_span

STATIC_DIR = Path(__file__).resolve().parent
USE_RERANK = "--no-rerank" not in sys.argv
DISPLAY_K = 8  # 사용자에게 보여주고 GMS에 넘기는 최종 개수

_conn = None
_vocab = None


def _ensure_ready():
    global _conn, _vocab
    if _conn is None:
        _conn = connect()
        register_vector(_conn)
        _vocab = load_region_vocab(_conn)


def _hit_to_json(h) -> dict:
    return {
        "posting_uid": h.posting_uid, "company": h.company, "title": h.title,
        "url": h.url, "regions": h.regions, "tech": h.tech, "exp_min": h.exp_min,
        "exact": h.exact,
        "dense_rank": h.dense_rank, "dense_score": h.dense_score,
        "bm25_rank": h.bm25_rank, "bm25_score": h.bm25_score,
        "rerank_score": h.rerank_score, "rrf": h.rrf,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # 콘솔 노이즈 억제 — 필요하면 여기서 tracing으로 대체

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            html = (STATIC_DIR / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return
        if self.path == "/api/eval":
            if not harness.OUT.exists():
                self._send_json(404, {"error": "아직 실행 안 됨 — '다시 계산' 버튼을 눌러줘"})
                return
            self._send_json(200, json.loads(harness.OUT.read_text(encoding="utf-8")))
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/api/eval/run":
            try:
                _ensure_ready()
                report = {
                    "generated_at": __import__("datetime").datetime.now().isoformat(),
                    "search": harness.eval_search(_conn, _vocab),
                    "discrimination": harness.eval_discrimination(_conn, _vocab),
                    "parsing": harness.eval_parsing(_vocab),
                    "latency": harness.eval_latency(),
                    "chunking": harness.eval_chunking(_conn),
                }
                harness.OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                self._send_json(200, report)
            except Exception:
                self._send_json(500, {"error": traceback.format_exc()})
            return
        if self.path != "/api/search":
            self._send_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            query = (body.get("query") or "").strip()
            if not query:
                self._send_json(400, {"error": "query is required"})
                return

            _ensure_ready()
            trace = new_trace_id()
            t0 = time.perf_counter()

            with node_span(trace, "query_parse", "query", query) as span:
                spec = parse_query(query, _vocab)
                span.output_summary = spec.summary()

            with node_span(trace, "hybrid_search", "query", query) as span:
                result = hybrid_search(_conn, spec, top_k=DISPLAY_K, use_rerank=USE_RERANK)
                span.metrics = result.metrics()

            answer, gen_error = "", None
            with node_span(trace, "generate", "query", query) as span:
                try:
                    answer = generate_answer(spec.text, result.hits)
                except Exception as e:
                    gen_error = str(e)
                    span.metrics = {"error": gen_error}

            self._send_json(200, {
                "trace_id": trace,
                "parsed": spec.summary(),
                "hits": [_hit_to_json(h) for h in result.hits],
                "relaxed": result.relaxed,
                "reranked": result.reranked,
                "reranker_backend": result.reranker_backend,
                "answer": answer,
                "generate_error": gen_error,
                "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
            })
        except Exception:
            self._send_json(500, {"error": traceback.format_exc()})


def _warmup_models():
    from jobrag.embedding import warmup as warmup_embed
    from jobrag.reranker import warmup as warmup_rerank
    print("모델 사전 로딩 중 (임베딩 + 리랭커)...")
    t0 = time.perf_counter()
    warmup_embed()
    warmup_rerank()
    print(f"모델 로딩 완료 ({time.perf_counter() - t0:.1f}s) — 첫 쿼리부터 빠르게 응답합니다")


def main():
    port = 8766
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    _ensure_ready()
    _warmup_models()
    print(f"jobrag webapp: http://127.0.0.1:{port}  (rerank={'ON' if USE_RERANK else 'OFF'})")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
