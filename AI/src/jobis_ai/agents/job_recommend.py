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
from jobis_ai.agents._common import agent_arg, ensure_profile
from jobis_ai.experience_estimator import estimate_experience_months
from jobis_ai.gap_matcher import get_gap_matcher
from jobis_ai.postings_db import experience_floor_years, fits_experience, posting_floor_years
from jobis_ai.rag import get_rag_adapter
from jobis_ai.role_taxonomy import get_role_taxonomy
from jobis_ai.skill_taxonomy import get_skill_taxonomy

_MAX_QUERY_SKILLS = 8
_MAX_RECOMMENDATIONS = 5
# 검색은 넉넉히 받아서 연차로 걸러낸 뒤 자른다 — 5건만 받아 거르면 남는 게 없다.
_SEARCH_POOL = 30


def _user_experience_years(session: dict[str, Any], profile: dict) -> float | None:
    """사용자 연차. 대화로 말한 경력 수준이 우선, 없으면 이력서에서 추정. 모르면 None.

    말한 것을 이력서 추정보다 앞세우는 이유: "신입인데 공고 봐줘" 처럼 사용자가 스스로
    규정한 것이 가장 확실한 근거다. 둘 다 없으면 None — 그때는 연차로 거르지 않는다.
    """

    said = str((session.get("preferences") or {}).get("experienceLevel") or "").strip()
    if said:
        years = experience_floor_years(said)
        if years is not None:
            return years
    if profile:
        estimate = estimate_experience_months(profile)
        if estimate.totalMonths is not None:
            return estimate.totalMonths / 12.0
    return None


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
    candidates: list[dict], profile: dict, pref_terms: list[str], *, profile_known: bool = True
) -> list[dict]:
    """RAG 후보 공고 → 매칭 계산 기반 추천. find_alternatives._alternatives_from_rag 와
    같은 방식이되 목표 공고(gap)가 없으므로 reducedGaps 개념이 없다.

    랭킹: 보유 역량 일치 수 + 선호 일치 수 합산, 동률이면 선호 일치 → RAG 점수 순.

    profile_known=False(이력서 없이 선호만으로 온 경우)는 **역량 일치를 계산하지 않는다**.
    빈 프로필로 매칭을 돌리면 전 후보가 "일치 0" 으로 탈락해 추천이 통째로 사라지기 때문이다.
    이때 근거는 선호 일치와 공고 요구 기술 나열까지만 말하고, 역량 일치는 계산하지 않았음을
    분명히 한다 — 없는 근거를 있는 것처럼 말하지 않는다."""

    taxonomy = get_skill_taxonomy()
    matcher = get_gap_matcher()

    out: list[dict] = []
    for candidate in candidates:
        text = str(candidate.get("text", ""))
        skills = taxonomy.find_in_text(text)
        if not skills:
            continue
        matched: list[str] = []
        if profile_known:
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
        if profile_known:
            reason = (
                f"공고 요구 기술 {len(skills)}개 중 {len(matched)}개"
                f"({', '.join(matched[:5])})를 이미 보유하고 있습니다."
            )
            if matched_prefs:
                reason += f" 말씀해주신 선호({', '.join(matched_prefs[:3])})와도 맞는 공고예요."
        else:
            reason = f"공고가 요구하는 기술은 {', '.join(skills[:5])} 입니다."
            if matched_prefs:
                reason = (f"말씀해주신 선호({', '.join(matched_prefs[:3])})와 맞는 공고예요. "
                          + reason)
            reason += " 이력서를 올려주시면 보유 역량과의 일치까지 계산해 드려요."
        out.append({
            "title": str(candidate.get("title") or candidate.get("companyName") or text[:40]),
            "companyName": str(candidate.get("companyName", "")),
            "matchedSkills": matched,
            "matchedPreferences": matched_prefs,
            "requiredSkills": skills,
            "reason": reason,
            "sourceJobPostingId": candidate.get("jobPostingId"),
            # 공고의 연차 표기 원문 — 사용자에게 그대로 보여준다(우리 해석이 아니라 공고 표기).
            "experience": str(candidate.get("seniority") or ""),
            # 공고를 나열할 때는 URL 을 함께 준다 — 사용자가 바로 그 공고로 적합도
            # 분석을 이어갈 수 있게 (Agent_Test 프로토타입의 UX 규칙 이식).
            "url": str(candidate.get("url") or ""),
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
    """세션 이력서 → 프로필 → RAG 검색 → 매칭 계산 → 추천 목록.

    이력서 없이 선호만 있어도 실공고를 추천한다(전제가 "이력서 또는 선호"). 그때는 프로필을
    만들지 않는다 — 이력서가 없으면 build_user_profile 은 빈 프로필밖에 못 내면서 LLM 만 쓴다.
    """

    profile_known = bool(session.get("resume") or session.get("profile"))
    if profile_known:
        profile, warnings = ensure_profile(session)
    else:
        profile, warnings = {}, []
    role_category = _profile_role_category(profile)
    pref_terms = _preference_terms(session)
    # 플래너(LLM)가 발화에서 직군을 읽어 넘겼으면 그것을 검색의 앞자리에 둔다 —
    # "데이터 엔지니어 공고 찾아줘" 처럼 대상이 발화에만 있는 경우, 이 통로가 없으면
    # 선호 수집 턴을 한 번 더 거쳐야 했다. 없으면 기존대로 프로필·선호만으로 만든다.
    job_name = agent_arg(session, "job_recommend", "job_name")
    if job_name and job_name.lower() not in {t.lower() for t in pref_terms}:
        pref_terms = [job_name] + pref_terms
    query = _build_query(profile, role_category, pref_terms)

    if not query:
        return AgentResult(
            data={"recommendations": [], "emptyQuery": True, "profileKnown": profile_known,
                  "query": "", "roleCategory": role_category, "preferenceTerms": pref_terms},
            warnings=warnings + [{
                "code": "empty_recommend_query",
                "message": "job_recommend: 프로필·선호 어디에도 스킬·직무 정보가 없어 검색 쿼리를 만들지 못했습니다.",
            }],
        )

    rag = get_rag_adapter().search(query, top_k=_SEARCH_POOL)
    warnings.extend(rag.warnings)
    # 실 RAG 가 아니라 키워드 폴백으로 찾은 결과인지 — 표현 계층이 사용자에게 명시한다(D90).
    rag_fallback = any(w.get("code") == "rag_http_failed" for w in rag.warnings)

    # 연차 불일치 공고를 랭킹 전에 걸러낸다 — "신입" 이라고 말한 사용자에게 경력 8년 요구
    # 공고를 추천하던 문제. 사용자 연차나 공고 표기를 모르면 거르지 않는다.
    user_years = _user_experience_years(session, profile)
    candidates = [
        c for c in rag.items
        if fits_experience(posting_floor_years(c.get("seniority"), c.get("title")), user_years)
    ]
    dropped = len(rag.items) - len(candidates)
    if dropped:
        warnings.append({
            "code": "experience_filtered",
            "message": (f"job_recommend: 연차 불일치로 공고 {dropped}건 제외"
                        f"(사용자 {user_years:g}년 기준)."),
        })

    recommendations = (
        _recommend_from_candidates(candidates, profile, pref_terms, profile_known=profile_known)
        if candidates else []
    )

    # 문장은 만들지 않는다 — 이 모듈은 도구다(계산만). 표현은 tool_render.render_job_recommend.
    if not recommendations and dropped and not candidates:
        warnings.append({
            "code": "no_recommendation_after_experience_filter",
            "message": f"job_recommend: 연차 필터로 후보 {dropped}건이 전부 제외돼 추천이 없습니다.",
        })
    elif not recommendations:
        # 실공고 없이 추천을 지어내지 않는다.
        warnings.append({
            "code": "no_recommendation",
            "message": "job_recommend: RAG 결과가 없어 추천을 생성하지 않았습니다(허구 공고 금지).",
        })

    return AgentResult(
        data={"query": query, "roleCategory": role_category,
              "preferenceTerms": pref_terms, "recommendations": recommendations,
              # 표현 계층이 문장을 고르는 데 쓰는 사실들(판단이 아니라 상태다)
              "profileKnown": profile_known, "droppedByExperience": dropped,
              "userExperienceYears": user_years, "ragFallback": rag_fallback},
        warnings=warnings,
        sessionUpdates={"recommendations": recommendations},
    )
