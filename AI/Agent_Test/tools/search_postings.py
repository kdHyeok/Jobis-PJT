"""search_postings — 유사 공고 검색 (RAG **Mock**) · AGENTS §4.1 · RAG 입출력 명세서.

실제 검색은 RAG 팀 담당. 여기선 **naive 키워드 매칭 Mock** (LLM 없음 = 결정적).
실제 RAG 완성 시 **이 함수 몸통만 교체**(입출력 계약 불변).
※ DB 접근을 load_posting과 공유하지 않는다 — 프로덕션에선
   load_posting=데이터팀 DB(키 조회), search_postings=RAG(의미 검색)로 백엔드가 갈리므로.
"""
from __future__ import annotations

import glob
import json
import os

from schemas import MatchReason, ScoredPosting, SearchResult, UserProfile

TOP_K = 3

_DB_GLOB = os.path.join(
    os.path.dirname(__file__), "..", "sample_data", "db내 공고파일", "*.json"
)

_POSTINGS: list[dict] | None = None


def _load_postings() -> list[dict]:
    """검색 후보 공고(need_ocr=='X' & detail_text 있음)를 로드한다(1회 캐시)."""
    global _POSTINGS
    if _POSTINGS is None:
        items: list[dict] = []
        for path in glob.glob(_DB_GLOB):
            with open(path, encoding="utf-8") as f:
                for p in json.load(f):
                    if p.get("need_ocr") == "X" and str(p.get("detail_text", "")).strip():
                        items.append(p)
        _POSTINGS = items
    return _POSTINGS


def _extract_terms(
    query: str | UserProfile | dict,
) -> tuple[list[str], list[str], dict[str, str], bool]:
    """입력 → (skills, keywords, term→기여필드, title_only).

    - profile → skills·techStack 를 본문(title+detail_text)에서 매칭 (title_only=False)
    - 직업명(str) → 토큰을 **제목(title)에서만** 매칭 (title_only=True) — 본문 전체면 false positive 많음
    """
    if isinstance(query, dict):
        query = UserProfile(**query)
    if isinstance(query, UserProfile):
        skills = list(dict.fromkeys(s.name for s in query.skills if s.name))
        techstack = list(
            dict.fromkeys(t for p in query.projects for t in p.techStack if t)
        )
        field = {s: "skills" for s in skills}
        field.update({t: "projects.techStack" for t in techstack})
        return skills, techstack, field, False
    # 직업명 문자열 → 제목 매칭
    terms = list(dict.fromkeys([query, *query.split()]))
    return [], terms, {t: "query" for t in terms}, True


def search_postings(query: str | UserProfile | dict) -> SearchResult:
    """직업명 또는 profile로 유사 공고를 찾는다(Mock). 계약: RAG 입출력 명세서.

    원본 공고 필드는 그대로 두고 score·match_reason만 얹어 top_k개를 반환. 0건이면 빈 배열.
    """
    skills, keywords, field, title_only = _extract_terms(query)
    all_terms = skills + keywords
    scored: list[tuple[float, ScoredPosting]] = []
    for p in _load_postings():
        # 직업명 → 제목만, profile → 제목+본문
        if title_only:
            hay = str(p.get("title", "")).lower()
        else:
            hay = f"{p.get('title', '')} {p.get('detail_text', '')}".lower()
        m_skills = [s for s in skills if s.lower() in hay]
        m_keywords = [k for k in keywords if k.lower() in hay]
        matched = m_skills + m_keywords
        if not matched:
            continue
        score = round(len(matched) / max(1, len(all_terms)), 3)  # mock 임의값(0~1)
        fields = sorted({field[t] for t in matched})
        mr = MatchReason(
            matched_skills=m_skills, matched_keywords=m_keywords, matched_fields=fields
        )
        scored.append((score, ScoredPosting(**p, score=score, match_reason=mr)))
    scored.sort(key=lambda x: x[0], reverse=True)
    return SearchResult(postings=[sp for _, sp in scored[:TOP_K]])
