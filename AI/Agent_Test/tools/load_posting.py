"""load_posting — 공고 URL로 로컬 DB(샘플 JSON) 조회 (AGENTS §4.1 · 정본 §4.3).

**조회만**(가공·구조화 안 함). LLM 안 씀 = 결정적 툴.
성공 → `Posting`(D10) / 없는 URL → `ToolError(NOT_FOUND)` (raise 금지).
※ DB는 샘플 JSON. 데이터팀 실제 DB 연동은 범위 밖(계약 동일).
"""
from __future__ import annotations

import glob
import json
import os

from schemas import Posting, ToolError

_DB_GLOB = os.path.join(
    os.path.dirname(__file__), "..", "sample_data", "db내 공고파일", "*.json"
)

_INDEX: dict[str, dict] | None = None


def _load_db() -> dict[str, dict]:
    """공고 JSON들을 `{url: 공고dict}`로 인덱싱한다(모듈 레벨 1회 캐시)."""
    global _INDEX
    if _INDEX is None:
        idx: dict[str, dict] = {}
        for path in glob.glob(_DB_GLOB):
            with open(path, encoding="utf-8") as f:
                for posting in json.load(f):
                    url = posting.get("url")
                    if url:
                        idx[url] = posting
        _INDEX = idx
    return _INDEX


def load_posting(url: str) -> Posting | ToolError:
    """공고 URL로 DB에서 공고 1건 조회(정확 일치). 없으면 NOT_FOUND."""
    posting = _load_db().get(url)
    if posting is None:
        return ToolError(
            error="NOT_FOUND",
            source="load_posting",
            detail=f"해당 URL 공고가 DB에 없음: {url}",
        )
    return Posting(**posting)
