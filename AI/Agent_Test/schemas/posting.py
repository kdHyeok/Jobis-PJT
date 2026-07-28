"""공고 JSON 스키마 — AGENTS §2.2 (DB 원본, 약 15필드).

`load_posting` 출력이자 `analyze_gap` 입력. 실제 `sample_data/db내 공고파일/*.json`과
필드·타입 대조 완료(전부 str, `image_urls`만 list, 일부 필드 null 허용).
`need_ocr == "X"`(본문 채워진 것)만 사용.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class Posting(BaseModel):
    source: Optional[str] = None
    posting_id: Optional[str] = None
    company: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None
    employment_type: Optional[str] = None
    experience: Optional[str] = None
    education: Optional[str] = None
    location: Optional[str] = None
    posted_date: Optional[str] = None
    deadline: Optional[str] = None
    detail_text: Optional[str] = None
    image_urls: list[str] = Field(default_factory=list)
    need_ocr: Optional[str] = None
    collected_at: Optional[str] = None
