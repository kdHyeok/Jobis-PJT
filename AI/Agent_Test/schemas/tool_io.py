"""툴 입출력 스키마 — AGENTS §4.1 / §2.3.

- `GapResult`      : analyze_gap 출력
- `ScoredPosting`  : 원본 공고 + score + match_reason (search_postings 항목)
- `SearchResult`   : search_postings 출력 (postings 배열)
- `ToolError`      : 툴 실패 봉투 {error, source, detail} (AGENTS §7)
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from schemas.posting import Posting

Level = Literal["상", "중", "하"]


class GapResult(BaseModel):
    """analyze_gap 출력 (AGENTS §4.1).

    `uncertain`: 판정 불가 요건(not_met과 구분 — score 분모·missing에서 제외).
    """

    score: float
    level: Level
    matched_required: list[str] = Field(default_factory=list)
    missing_required: list[str] = Field(default_factory=list)
    matched_preferred: list[str] = Field(default_factory=list)
    uncertain: list[str] = Field(default_factory=list)
    rationale: str


class MatchReason(BaseModel):
    """RAG 매칭 근거(디버그/관측) — 계약 단일출처: RAG 입출력 명세서(3필드).
    extra="allow": RAG가 나중에 디버그 필드 추가해도 버리지 않는다."""

    model_config = ConfigDict(extra="allow")

    matched_skills: list[str] = Field(default_factory=list)
    matched_keywords: list[str] = Field(default_factory=list)
    matched_fields: list[str] = Field(default_factory=list)


class ScoredPosting(Posting):
    """원본 공고 JSON에 score·match_reason만 얹은 것 (AGENTS §2.3)."""

    score: float
    match_reason: MatchReason = Field(default_factory=MatchReason)


class SearchResult(BaseModel):
    """search_postings 출력. 0건이면 postings=[] (AGENTS §2.3)."""

    postings: list[ScoredPosting] = Field(default_factory=list)


class ToolError(BaseModel):
    """툴 실패 반환 봉투 (AGENTS §4.1·§7). 예외 throw 대신 이걸 반환한다."""

    error: str          # NOT_FOUND / INSUFFICIENT_INPUT / SEARCH_FAILED (§7)
    source: str         # 던진 모듈명 (예: load_posting)
    detail: Optional[str] = None
