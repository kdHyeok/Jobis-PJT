"""search_postings — 유사 공고 검색 (실 RAG 연동) · AGENTS §4.1 · RAG 입출력 명세서.

Mock(키워드 매칭) → **실제 RAG HTTP 서비스 호출**로 몸통 교체(입출력 계약 불변, D12/D14).
RAG 서비스: job-rag-pipeline의 `webapp/tool_server.py` (하이브리드 검색 + 리랭킹).
  - 환경변수 `RAG_SEARCH_URL` (기본 http://127.0.0.1:8765) 로 위치 지정.
  - 서버 미기동/타임아웃 시: 그래프(_tools_node)가 ToolError 분기를 갖지 않으므로
    크래시 대신 **빈 SearchResult**를 반환하고 로그로 사유를 남긴다
    ("관련 공고 없음"으로 안내됨 — 0건 계약과 동일 경로).
※ 의존성 추가 없음 — stdlib urllib 사용 (requirements.txt 불변).
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

from schemas import SearchResult, UserProfile

log = logging.getLogger(__name__)

TOP_K = 3
_TIMEOUT_SEC = 30

RAG_SEARCH_URL = os.getenv("RAG_SEARCH_URL", "http://127.0.0.1:8765")


def search_postings(query: str | UserProfile | dict) -> SearchResult:
    """직업명 또는 profile로 유사 공고를 찾는다(실 RAG). 계약: RAG 입출력 명세서.

    원본 공고 필드는 그대로 두고 score·match_reason만 얹어 top_k개를 반환. 0건이면 빈 배열.
    """
    if isinstance(query, UserProfile):
        payload_input: str | dict = query.model_dump()
    else:
        payload_input = query

    body = json.dumps(
        # evaluate=False — CRAG 평가자(문서별 LLM 채점)를 끈다. 툴 경로는 LLM 0회·최소 지연.
        {"input": payload_input, "top_k": TOP_K, "evaluate": False}, ensure_ascii=False
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{RAG_SEARCH_URL}/search", body, {"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC) as resp:
            data = json.load(resp)
        return SearchResult(**data)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as e:
        # SEARCH_FAILED 상황 — 사유를 삼키지 않고 로그로 남긴다 (graph는 0건 경로로 진행)
        log.warning("search_postings: RAG 호출 실패(%s) — %s", RAG_SEARCH_URL, e)
        return SearchResult(postings=[])
