"""analyze_gap — 이력서·공고 갭분석 (AGENTS §5.1 · §4.1 · 정본 §4.1). 🎯 핵심 툴.

**결정론 우선**(아류 프로젝트 gap_matcher 아이디어 차용, 통째 포팅 아님):
- 스킬 매칭은 **룰**(LLM 없이) — profile 스킬 토큰이 요건에 있으면 met.
- LLM은 ① 요건 추출(mid) + ② 룰로 못 잡은 서술형 요건 폴백 판정(strong)만.
- **uncertain ≠ not_met** — 판정 불가는 score 분모·missing에서 제외("모른다"를 "없다"로 안 찍음).
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from llm import get_structured_llm
from schemas import GapResult, Posting, ToolError, UserProfile

# --- 채점 상수 (조정 시 여기만) ---
_TYPE_W = {"required": 1.0, "preferred": 0.5}
_STATUS_S = {"met": 1.0, "not_met": 0.0}  # uncertain 은 제외(분모에서 뺌)
_GRADE_HIGH = 0.70
_GRADE_MID = 0.40


def _level_of(score: float) -> str:
    """score → level(상/중/하). 임계치는 위 상수 (task 06 확정). 테스트에서 재사용."""
    return "상" if score >= _GRADE_HIGH else "중" if score >= _GRADE_MID else "하"


# --- 내부 스키마 (모듈 로컬 — 공개 계약 아님) ---
class _Requirements(BaseModel):
    required: list[str] = Field(default_factory=list)
    preferred: list[str] = Field(default_factory=list)


class _Fallback(BaseModel):
    """룰로 못 잡은 요건들에 대한 순서대로의 판정."""

    statuses: list[Literal["met", "not_met", "uncertain"]] = Field(default_factory=list)


def _tokens(s: str) -> set[str]:
    return {w for w in re.split(r"[^0-9a-zA-Z가-힣]+", s.lower()) if len(w) >= 2 and not w.isdigit()}


def _skill_tokens(p: UserProfile) -> set[str]:
    toks: set[str] = set()
    for s in p.skills:
        if s.name:
            toks |= _tokens(s.name)
    for pr in p.projects:
        for t in pr.techStack:
            toks |= _tokens(t)
    return toks


def _profile_summary(p: UserProfile) -> str:
    skills = ", ".join(s.name for s in p.skills if s.name)
    exps = "; ".join(f"{e.role or ''}({e.period or ''})" for e in p.experiences) or "(없음)"
    projs = "; ".join(
        f"{pr.title or ''}[{', '.join(pr.techStack)}]" for pr in p.projects
    ) or "(없음)"
    return f"스킬: {skills}\n경력: {exps}\n프로젝트: {projs}"


def _as_profile(p) -> UserProfile:
    return p if isinstance(p, UserProfile) else UserProfile(**p)


def _as_posting(p) -> Posting:
    return p if isinstance(p, Posting) else Posting(**p)


def analyze_gap(profile, posting) -> GapResult | ToolError:
    """profile + 공고 → GapResult(score·level·matched/missing/uncertain·rationale). raise 안 함."""
    prof = _as_profile(profile)
    post = _as_posting(posting)

    # 입력 검증
    if not (post.detail_text and post.detail_text.strip()):
        return ToolError(error="INSUFFICIENT_INPUT", source="analyze_gap",
                         detail="공고 본문(detail_text)이 없습니다 — 이미지 공고일 수 있어 요건을 추출할 수 없습니다")
    if not (prof.skills or prof.experiences or prof.projects):
        return ToolError(error="INSUFFICIENT_INPUT", source="analyze_gap",
                         detail="이력서에 스킬·경력·프로젝트 정보가 없습니다")

    # ① [LLM/mid] 요건 추출
    reqs: _Requirements = get_structured_llm("mid", _Requirements).invoke(
        [
            ("system", "채용공고 본문에서 지원 요건을 추출한다. 필수(required)와 우대(preferred)로 나눈다. "
                       "각 항목은 짧은 문구로. 본문에 없는 요건은 지어내지 마라."),
            ("human", f"공고 본문:\n{post.detail_text}"),
        ]
    )
    all_reqs = [(t, "required") for t in reqs.required] + [(t, "preferred") for t in reqs.preferred]

    # ② (a) 룰 스킬 매칭
    skill_toks = _skill_tokens(prof)
    judged: list[tuple[str, str, str]] = []  # (text, type, status)
    unmatched: list[tuple[str, str]] = []
    for text, rtype in all_reqs:
        if _tokens(text) & skill_toks:
            judged.append((text, rtype, "met"))
        else:
            unmatched.append((text, rtype))

    # ② (b) [LLM/strong] 폴백 판정 (룰 미매칭만, 1회 호출)
    if unmatched:
        fb: _Fallback = get_structured_llm("strong", _Fallback).invoke(
            [
                ("system", "지원자 프로필을 보고 각 요건 충족 여부를 순서대로 판정한다. "
                           "met/not_met/uncertain 중 하나를 statuses에 요건 개수만큼 넣어라. "
                           "프로필에 근거가 없어 판단할 수 없으면 not_met이 아니라 uncertain."),
                ("human", f"[프로필]\n{_profile_summary(prof)}\n\n[요건]\n"
                          + "\n".join(f"{i+1}. {t}" for i, (t, _) in enumerate(unmatched))),
            ]
        )
        statuses = list(fb.statuses)[: len(unmatched)]
        statuses += ["uncertain"] * (len(unmatched) - len(statuses))
        for (text, rtype), status in zip(unmatched, statuses):
            judged.append((text, rtype, status))

    # ③ 채점 (uncertain 제외)
    decided = [(t, rt, s) for t, rt, s in judged if s in _STATUS_S]
    if decided:
        total_w = sum(_TYPE_W[rt] for _, rt, _ in decided)
        got = sum(_STATUS_S[s] * _TYPE_W[rt] for _, rt, s in decided)
        score = round(got / total_w, 3) if total_w else 0.5
        level = _level_of(score)
    else:
        score, level = 0.5, "중"  # 판정불가 중립 (엣지)

    matched_required = [t for t, rt, s in judged if rt == "required" and s == "met"]
    missing_required = [t for t, rt, s in judged if rt == "required" and s == "not_met"]
    matched_preferred = [t for t, rt, s in judged if rt == "preferred" and s == "met"]
    uncertain = [t for t, rt, s in judged if s == "uncertain"]

    parts = [f"필수 {len(matched_required)}건 충족"]
    if missing_required:
        head = ", ".join(missing_required[:3]) + ("…" if len(missing_required) > 3 else "")
        parts.append(f"필수 미충족 {len(missing_required)}건({head})")
    if matched_preferred:
        parts.append(f"우대 {len(matched_preferred)}건 충족")
    if uncertain:
        parts.append(f"판정불가 {len(uncertain)}건")
    rationale = f"[{level}] " + " / ".join(parts)

    return GapResult(
        score=score, level=level,
        matched_required=matched_required, missing_required=missing_required,
        matched_preferred=matched_preferred, uncertain=uncertain, rationale=rationale,
    )
