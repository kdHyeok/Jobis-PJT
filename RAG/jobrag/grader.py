"""CRAG 관련성 평가자 — 질의 대비 개별 검색결과(hit)를 3단계로 채점.

채점만 담당한다. 등급별 교정 동작(재검색, 웹검색, 컨텍스트 정제 등)은
apply_correction에 분기 자리만 만들어두고 구현은 아직 없다.
"""
from __future__ import annotations

from typing import Literal

from .generate import GmsClient
from .search import SearchHit

Grade = Literal["correct", "ambiguous", "incorrect"]

GRADE_SYSTEM_PROMPT = """당신은 채용공고 검색결과의 관련성을 채점하는 평가자입니다.
[질문]과 [공고] 하나를 비교해 아래 세 등급 중 하나만 출력하세요. 다른 말은 하지 마세요.
- correct: 질문의 핵심 조건(직무/기술/경력/지역 등)에 실제로 부합
- ambiguous: 일부만 부합하거나 판단이 애매함
- incorrect: 질문과 관련이 없거나 조건에 명백히 어긋남"""

_client: GmsClient | None = None


def _format_hit(hit: SearchHit) -> str:
    exp = "경력무관" if hit.exp_min is None else f"{hit.exp_min}년+"
    loc = ", ".join(hit.regions[:2]) or "지역 미상"
    tech = ", ".join(hit.tech[:8]) or "명시 없음"
    return f"{hit.company} — {hit.title}\n조건: {exp} · {loc} · 기술: {tech}"


def grade_hit(query: str, hit: SearchHit) -> Grade:
    """질의-hit 쌍을 LLM으로 채점. 호출 실패 시 ambiguous로 폴백(안전 쪽으로)."""
    global _client
    if _client is None:
        _client = GmsClient()
    try:
        raw = _client.classify(
            GRADE_SYSTEM_PROMPT, f"[질문]\n{query}\n\n[공고]\n{_format_hit(hit)}"
        ).strip().lower()
    except Exception:  # noqa: BLE001 — 채점 실패가 검색 흐름을 막으면 안 됨
        return "ambiguous"
    if "incorrect" in raw:
        return "incorrect"
    if "correct" in raw:
        return "correct"
    return "ambiguous"


def grade_hits(query: str, hits: list[SearchHit]) -> dict[str, Grade]:
    """hit별 등급을 posting_uid -> grade 로 반환."""
    return {h.posting_uid: grade_hit(query, h) for h in hits}


def apply_correction(query: str, hits: list[SearchHit], grades: dict[str, Grade]) -> list[SearchHit]:
    """등급별 교정 동작이 들어갈 자리 — 지금은 아무 필터링 없이 원본을 그대로 통과."""
    for grade in ("correct", "ambiguous", "incorrect"):
        pass  # TODO: correct=그대로, ambiguous=컨텍스트 정제, incorrect=제외/재검색 등
    return hits
