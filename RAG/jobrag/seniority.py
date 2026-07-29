"""연차(exp_min) + 고용형태 -> seniority 라벨.

RagAdapter 출력 계약의 "권장" 필드. exp_min만으로는 인턴을 구분 못 하므로
employment_type도 함께 본다.
"""
from __future__ import annotations

_INTERN_WORDS = ("인턴", "intern")


def to_seniority(exp_min: int | None, employment_type: str = "") -> str:
    if any(w in (employment_type or "").lower() for w in _INTERN_WORDS):
        return "intern"
    if exp_min is None:
        return "unspecified"
    if exp_min == 0:
        return "junior"
    if exp_min <= 3:
        return "junior"
    if exp_min <= 7:
        return "mid"
    return "senior"
