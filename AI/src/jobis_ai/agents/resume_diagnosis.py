"""resume_diagnosis 에이전트 — 이력서 정리·진단.

**판정(적합/부적합)을 하지 않는다.** 프로필에서 계산 가능한 사실만 항목화해 보여준다:
읽어낸 섹션들(기술/프로젝트/경력/학력/자격/어학) / 근거 있는 스킬 vs 기재만 된 스킬 /
빈 섹션. 공고를 항목화해 주는 posting_analysis 의 이력서 짝이다 — 무엇을 근거로
판정하게 될지 사용자가 먼저 확인할 수 있어야 한다.

**도구다 — 말하지 않는다**(0729 표현 분리). 요약 줄과 마무리 문장은 `tool_render` 로 옮겼다.
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


def _labels(items: list, *keys: str) -> list[str]:
    out = []
    for item in items or []:
        text = " ".join(str(item.get(k) or "").strip() for k in keys).strip()
        if text:
            out.append(text)
    return out


def run(session: dict[str, Any]) -> AgentResult:
    """세션 이력서 → 프로필 → 항목별 사실(데이터). **도구다 — 말하지 않는다.**

    요약 줄·마무리 문장은 전부 표현이므로 `tool_render.render_resume_diagnosis` 로 옮겼다.
    `resumeSummary` 는 표현만을 위한 우회로가 아니다 — 같은 항목이 우측 패널
    (PROFILE_CONTEXT/context.profile)에도 표로 가는 산출물이다.
    """

    profile, warnings = ensure_profile(session)

    skill_evidence: dict = profile.get("skillEvidence") or {}
    skills = [s.get("name", "") for s in profile.get("skills", []) if s.get("name")]
    evidenced = [s for s in skills if skill_evidence.get(s)]
    unverified = [s for s in skills if not skill_evidence.get(s)]

    empty_sections = [
        label for key, label in _SECTION_LABELS.items() if not profile.get(key)
    ]
    section_counts = {key: len(profile.get(key) or []) for key in _SECTION_LABELS}
    readable = any(profile.get(k) for k in _SECTION_LABELS)

    completion_questions = (
        build_completion_questions(find_missing_enum_fields(profile)) if readable else []
    )
    return AgentResult(
        reply="",                       # 도구는 말하지 않는다 — 문장은 render 가 만든다
        data={
            "readable": readable,
            "sectionCounts": section_counts,
            "evidencedSkills": evidenced,
            "unverifiedSkills": unverified,
            "emptySections": empty_sections,
            # 표현·우측 패널이 함께 쓰는 항목화 결과.
            "resumeSummary": {
                "skills": skills,
                "projects": _labels(profile.get("projects"), "title"),
                "experiences": _labels(profile.get("experiences"), "company", "role"),
                "education": _labels(profile.get("education"), "school", "major"),
                "certifications": _labels(profile.get("certifications"), "name"),
                "languages": _labels(profile.get("languages"), "name", "testName", "score"),
            },
        },
        warnings=warnings,
        # 카드 질문은 **결정론** — 맥락을 살린 마무리 문장은 표현 계층이 쓴다.
        followUpQuestions=([] if not readable else [{
            "field": "confirm_fit",
            "question": "공고와 대조해 지원 가능성 진단을 해볼까요?",
        }] + completion_questions),
    )
