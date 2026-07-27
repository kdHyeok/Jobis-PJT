"""resume_diagnosis 에이전트 — 이력서 진단 (개선방안 Phase 1).

**순수 룰 — LLM 호출 없음(프로필 빌드 제외).** 판정(적합/부적합)을 하지 않는다.
프로필에서 계산 가능한 사실만 말한다: 근거 있는 스킬 / 근거 없는 스킬 / 빈 섹션 /
결측 enum 필드 보완 질문(profile_completeness 재사용).
"""

from __future__ import annotations

from typing import Any

from jobis_ai.agents import AgentResult
from jobis_ai.agents._common import ensure_profile
from jobis_ai.profile_completeness import build_completion_questions, find_missing_enum_fields

_SECTION_LABELS = {
    "education": "학력",
    "experiences": "경력",
    "projects": "프로젝트",
    "skills": "기술 스택",
    "certifications": "자격증",
    "languages": "어학",
    "awards": "수상",
}


def run(session: dict[str, Any]) -> AgentResult:
    profile, warnings = ensure_profile(session)

    skill_evidence: dict = profile.get("skillEvidence") or {}
    skills = [s.get("name", "") for s in profile.get("skills", []) if s.get("name")]
    evidenced = [s for s in skills if skill_evidence.get(s)]
    unverified = [s for s in skills if not skill_evidence.get(s)]

    empty_sections = [
        label for key, label in _SECTION_LABELS.items() if not profile.get(key)
    ]

    missing = find_missing_enum_fields(profile)
    completion_questions = build_completion_questions(missing)

    section_counts = {key: len(profile.get(key) or []) for key in _SECTION_LABELS}

    parts: list[str] = []
    if evidenced:
        parts.append(
            f"경험으로 뒷받침되는 기술이 {len(evidenced)}개({', '.join(evidenced[:5])}) 있습니다 — "
            "이 항목들이 이력서의 강점입니다."
        )
    if unverified:
        parts.append(
            f"기술 목록에는 있지만 이를 증명하는 경험 서술이 없는 기술이 {len(unverified)}개"
            f"({', '.join(unverified[:5])}) 있습니다. 관련 프로젝트·업무 경험을 한 줄이라도 적어 주면 "
            "설득력이 올라갑니다."
        )
    if empty_sections:
        parts.append(f"비어 있는 섹션: {', '.join(empty_sections)}.")
    if completion_questions:
        parts.append(f"보완하면 좋은 항목이 {len(completion_questions)}건 있습니다(아래 질문 참고).")
    if not parts:
        parts.append("이력서에서 진단할 항목을 찾지 못했습니다. 파일이 제대로 읽혔는지 확인해 주세요.")

    return AgentResult(
        reply=" ".join(parts),
        data={
            "sectionCounts": section_counts,
            "evidencedSkills": evidenced,
            "unverifiedSkills": unverified,
            "emptySections": empty_sections,
        },
        warnings=warnings,
        followUpQuestions=completion_questions,
    )
