"""데이터 탐색기 — 현재 인덱스된 공고 분포를 보고 검색 성능을 가늠하기 위한 대시보드.

검색 테스트 페이지(server.py)와 별개 서버(기본 포트 8768). DB를 읽기만 한다.
"""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jobrag.store import connect

STATIC_DIR = Path(__file__).resolve().parent


def _overview(conn) -> dict:
    cur = conn.cursor()
    cur.execute("SELECT count(*), count(*) FILTER (WHERE is_active) FROM postings")
    total, active = cur.fetchone()
    cur.execute("SELECT count(*) FROM chunks")
    chunks = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM chunks WHERE embedding IS NOT NULL")
    embedded = cur.fetchone()[0]
    cur.execute("SELECT round(avg(tokens)), max(tokens) FROM chunks")
    tok_avg, tok_max = cur.fetchone()
    tok_avg = float(tok_avg) if tok_avg is not None else None  # NUMERIC -> Decimal, JSON이 못 다룸
    cur.execute("SELECT count(*) FROM postings WHERE is_active AND needs_review")
    needs_review = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM postings WHERE is_active AND cardinality(tech)=0")
    no_tech = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM postings WHERE is_active AND cardinality(regions)=0")
    no_region = cur.fetchone()[0]

    cur.execute("""SELECT source, count(*) FROM postings WHERE is_active
                   GROUP BY source ORDER BY 2 DESC""")
    sources = [{"label": s, "count": c} for s, c in cur.fetchall()]

    cur.execute("""SELECT t, count(*) FROM postings p, unnest(p.tech) t
                   WHERE p.is_active GROUP BY t ORDER BY 2 DESC LIMIT 15""")
    tech = [{"label": t, "count": c} for t, c in cur.fetchall()]

    cur.execute("""SELECT r, count(*) FROM postings p, unnest(p.regions) r
                   WHERE p.is_active AND r NOT LIKE '% %' GROUP BY r ORDER BY 2 DESC""")
    regions = [{"label": r, "count": c} for r, c in cur.fetchall()]

    cur.execute("""SELECT
        CASE WHEN exp_min IS NULL THEN '경력무관'
             WHEN exp_min = 0 THEN '신입'
             WHEN exp_min <= 3 THEN '1~3년'
             WHEN exp_min <= 6 THEN '4~6년'
             WHEN exp_min <= 10 THEN '7~10년'
             ELSE '10년+' END AS bucket,
        count(*)
        FROM postings WHERE is_active GROUP BY 1""")
    order = {"신입": 0, "1~3년": 1, "4~6년": 2, "7~10년": 3, "10년+": 4, "경력무관": 5}
    exp = sorted(({"label": b, "count": c} for b, c in cur.fetchall()),
                 key=lambda x: order.get(x["label"], 9))

    return {
        "total": total, "active": active, "chunks": chunks, "embedded": embedded,
        "chunk_tokens_avg": tok_avg, "chunk_tokens_max": tok_max,
        "needs_review": needs_review, "no_tech": no_tech, "no_region": no_region,
        "sources": sources, "tech": tech, "regions": regions, "exp": exp,
    }


def _postings(conn) -> list[dict]:
    cur = conn.cursor()
    cur.execute("""SELECT uid, source, company, title, regions, tech, exp_min,
                          employment_type, deadline, needs_review, is_active, url
                   FROM postings ORDER BY company""")
    cols = ("uid", "source", "company", "title", "regions", "tech", "exp_min",
            "employment_type", "deadline", "needs_review", "is_active", "url")
    return [dict(zip(cols, row)) for row in cur.fetchall()]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json(self, status: int, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            html = (STATIC_DIR / "explorer.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return
        conn = connect()
        try:
            if self.path == "/api/overview":
                self._json(200, _overview(conn))
                return
            if self.path == "/api/postings":
                self._json(200, _postings(conn))
                return
        finally:
            conn.close()
        self._json(404, {"error": "not found"})


def main():
    port = 8768
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    print(f"jobrag explorer: http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
