"""대화에 붙여 넣은 채용공고를 판별하는 결정론 유틸리티."""

from __future__ import annotations

import re

POSTING_MARKERS = re.compile(
    r"(자격\s*요건|지원\s*자격|우대\s*사항|담당\s*업무|주요\s*업무|모집\s*부문|모집\s*분야|"
    r"직무\s*내용|채용\s*(공고|절차)|필수\s*요건|근무\s*조건)"
)
POSTING_MIN_CHARS = 180


def posting_in_message(message: str) -> str:
    """발화가 공고이면 원문 또는 단일 URL을 돌려주고, 아니면 빈 문자열을 준다."""

    text = (message or "").strip()
    if not text:
        return ""
    if text.lower().startswith(("http://", "https://")) and len(text.split()) == 1:
        return text
    if len(text) >= POSTING_MIN_CHARS and POSTING_MARKERS.search(text):
        return text
    return ""
