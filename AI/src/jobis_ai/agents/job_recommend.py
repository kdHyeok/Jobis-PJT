"""job_recommend 에이전트 — 이력서만으로 갈 수 있는 공고 추천 (개선방안 Phase 1).

find_alternatives 의 프로필-단독 판이다: 공고·gap 없이 프로필 스킬·직군에서 검색 쿼리를
만들어 RAG 실공고를 찾고, 후보마다 gap_matcher 로 **다시 매칭 계산**한다. LLM 호출 없음.

대화로 수집한 선호(preference_intake 산출 — 직군·도메인·회사·지역·기술스택)를 반영한다:
검색 쿼리에 선호 용어를 넣고, 후보 랭킹에서 선호 일치를 가점하고, 사유에 표시한다.

실공고(RAG)가 없으면 추천을 지어내지 않는다 — 빈 결과 + 정직한 경고
(find_alternatives 의 "회사·공고를 지어내지 않는다" 규율 계승).
"""

from __future__ import annotations

from typing import Any

from jobis_ai.agents import AgentResult
from jobis_ai.agents._common import ensure_profile
from jobis_ai.gap_matcher import get_gap_matcher
from jobis_ai.rag import get_rag_adapter
from jobis_ai.role_taxonomy import get_role_taxonomy
from jobis_ai.skill_taxonomy import get_skill_taxonomy

_MAX_QUERY_SKILLS = 8
_MAX_RECOMMENDATIONS = 5


def _profile_role_category(profile: dict) -> str:
    """경력·프로젝트 role 서술에서 직군을 분류한다(role_taxonomy 재사용). 못 찾으면 빈 문자열."""

    texts = [e.get("role", "") for e in profile.get("experiences", [])]
    texts += [p.get("role", "") for p in profile.get("projects", [])]
    taxonomy = get_role_taxonomy()
    for text in texts:
        category = taxonomy.classify_role(text) if text else ""
        if category:
            return category
    return ""


def _preference_terms(session: dict[str, Any]) -> list[str]:
    """대화로 수집한 선호(preference_intake)를 검색·랭킹용 용어 목록으로."""

    prefs = session.get("preferences") or {}
    terms: list[str] = []
    seen: set[str] = set()
    for key in ("roles", "domains", "companies", "regions", "techStack"):
        for v in prefs.get(key) or []:
            v = str(v).strip()
            if v and v.lower() not in seen:
                terms.append(v)
                seen.add(v.lower())
    return terms


def _build_query(profile: dict, role_category: str, pref_terms: list[str]) -> str:
    skills = [s.get("name", "") for s in profile.get("skills", [])][:_MAX_QUERY_SKILLS]
    parts = [role_category] + pref_terms + skills
    seen: set[str] = set()
    unique = [p for p in parts if p and not (p.lower() in seen or seen.add(p.lower()))]
    return " ".join(unique).strip()


def _recommend_from_candidates(
    candidates: list[dict], profile: dict, pref_terms: list[str]
) -> list[dict]:
    """RAG 후보 공고 → 매칭 계산 기반 추천. find_alternatives._alternatives_from_rag 와
    같은 방식이되 목표 공고(gap)가 없으므로 reducedGaps 개념이 없다.

    랭킹: 보유 역량 일치 수 + 선호 일치 수 합산, 동률이면 선호 일치 → RAG 점수 순."""

    taxonomy = get_skill_taxonomy()
    matcher = get_gap_matcher()

    out: list[dict] = []
    for candidate in candidates:
        text = str(candidate.get("text", ""))
        skills = taxonomy.find_in_text(text)
        if not skills:
            continue
        pseudo_reqs = [
            {"requirementId": f"rec-{i}", "text": skill, "type": "required"}
            for i, skill in enumerate(skills, start=1)
        ]
        report = matcher.match(pseudo_reqs, profile)
        matched = [s for m in report.matches if m.status == "met" for s in m.matchedSkills]
        if not matched:
            continue
        haystack = " ".join([
            text, str(candidate.get("title", "")), str(candidate.get("companyName", "")),
        ]).lower()
        matched_prefs = [t for t in pref_terms if t.lower() in haystack]
        reason = (
            f"공고 요구 기술 {len(skills)}개 중 {len(matched)}개"
            f"({', '.join(matched[:5])})를 이미 보유하고 있습니다."
        )
        if matched_prefs:
            reason += f" 말씀해주신 선호({', '.join(matched_prefs[:3])})와도 맞는 공고예요."
        out.append({
            "title": str(candidate.get("title") or candidate.get("companyName") or text[:40]),
            "companyName": str(candidate.get("companyName", "")),
            "matchedSkills": matched,
            "matchedPreferences": matched_prefs,
            "requiredSkills": skills,
            "reason": reason,
            "sourceJobPostingId": candidate.get("jobPostingId"),
            "confidence": float(candidate.get("score", 0.0) or 0.0),
        })

    out.sort(
        key=lambda r: (
            len(r["matchedSkills"]) + len(r["matchedPreferences"]),
            len(r["matchedPreferences"]),
            r["confidence"],
        ),
        reverse=True,
    )
    return out[:_MAX_RECOMMENDATIONS]


def run(session: dict[str, Any]) -> AgentResult:
    """세션 이력서 → 프로필 → RAG 검색 → 매칭 계산 → 추천 목록."""

    profile, warnings = ensure_profile(session)
    role_category = _profile_role_category(profile)
    pref_terms = _preference_terms(session)
    query = _build_query(profile, role_category, pref_terms)

    if not query:
        return AgentResult(
            reply="이력서에서 검색에 쓸 기술·직무 정보를 찾지 못했습니다. 이력서에 기술 스택이 담겨 있는지 확인해 주세요.",
            warnings=warnings + [{
                "code": "empty_recommend_query",
                "message": "job_recommend: 프로필에 스킬·직무 정보가 없어 검색 쿼리를 만들지 못했습니다.",
            }],
        )

    rag = get_rag_adapter().search(query)
    warnings.extend(rag.warnings)

    recommendations = _recommend_from_candidates(rag.items, profile, pref_terms) if rag.items else []

    if recommendations:
        top = recommendations[0]
        pref_note = (
            f"말씀해주신 선호({', '.join(pref_terms[:4])})를 반영해 " if pref_terms else ""
        )
        reply = (
            f"{pref_note}보유 역량과 매칭되는 공고 {len(recommendations)}건을 찾았습니다. "
            f"가장 잘 맞는 곳은 '{top['title']}'"
            f"({len(top['matchedSkills'])}개 역량 일치)입니다. "
            "관심 있는 공고를 고르시면 그 공고로 상세 적합도 분석을 이어서 해드릴게요."
        )
    else:
        # 실공고 없이 추천을 지어내지 않는다.
        reply = (
            "실제 공고 검색(RAG)에서 결과를 얻지 못해 추천을 만들 수 없습니다. "
            "공고 데이터 연결 후 다시 시도해 주세요."
        )
        warnings.append({
            "code": "no_recommendation",
            "message": "job_recommend: RAG 결과가 없어 추천을 생성하지 않았습니다(허구 공고 금지).",
        })

    return AgentResult(
        reply=reply,
        data={"query": query, "roleCategory": role_category,
              "preferenceTerms": pref_terms, "recommendations": recommendations},
        warnings=warnings,
        sessionUpdates={"recommendations": recommendations},
    )
