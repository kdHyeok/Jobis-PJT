"""resume_diagnosis 에이전트 — 이력서 정리·진단.

**판정(적합/부적합)을 하지 않는다.** 프로필에서 계산 가능한 사실만 항목화해 보여준다:
읽어낸 섹션들(기술/프로젝트/경력/학력/자격/어학) / 근거 있는 스킬 vs 기재만 된 스킬 /
빈 섹션. 공고를 항목화해 주는 posting_analysis 의 이력서 짝이다 — 무엇을 근거로
판정하게 될지 사용자가 먼저 확인할 수 있어야 한다.

마무리 문장(다음 단계 제안: "공고와 대조해 진단할까요?")은 맥락을 보고 LLM 이 쓰고,
금지표현·질문형 검증을 통과 못 하면 결정론 폴백을 쓴다 (posting_analysis 와 같은 패턴).
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from jobis_ai.agents import AgentResult
from jobis_ai.agents._common import ensure_profile
from jobis_ai.profile_completeness import build_completion_questions, find_missing_enum_fields
from jobis_ai.structured import run_structured
from jobis_ai.verify_rules import FORBIDDEN_EXPRESSIONS

_SECTION_LABELS = {
    "education": "학력",
    "experiences": "경력",
    "projects": "프로젝트",
    "skills": "기술 스택",
    "certifications": "자격증",
    "languages": "어학",
    "awards": "수상",
}


class _ClosingWrite(BaseModel):
    """이력서 정리를 건네고 턴을 되돌려주는 마무리 문장."""

    reply: str = Field(default="", description=(
        "이력서 정리를 마친 뒤 사용자에게 보낼 한두 문장. 사용자가 방금 한 말에 이어지게 쓴다. "
        "hasPosting 이 true 면 이미 받아 둔 공고와 대조해 지원 가능성 진단을 해볼지 묻고, "
        "false 면 어떤 공고와 대조하고 싶은지(공고 원문·URL을 주면 된다고) 묻는다. "
        "정리 항목을 다시 나열하지 않는다. 적합도·합격 가능성을 단정하지 않는다."))


_CLOSING_SYSTEM = """너는 취업 서비스의 대화 상담원이다. 방금 사용자의 이력서를 읽어 항목별로 정리해 보여줬다.
그 아래에 붙일 마무리 문장을 쓴다.

입력:
- userMessage: 사용자의 직전 발화. 여기에 이어지게 쓴다.
- recentHistory: 직전까지의 대화. 이미 한 말을 반복하지 않는다.
- resume: 방금 정리한 이력서의 요점(스킬 수·프로젝트 수·경력 유무). 숫자를 다시 나열하지 않는다.
- hasPosting: 세션에 공고가 이미 있는지.

규칙:
- 응답은 **질문으로 끝난다** — 다음 단계(공고와 대조한 지원 가능성 진단)로 갈지 사용자가 정한다.
- 적합도·합격 가능성을 단정하지 않는다. 진단은 아직 하지 않았다.
- 짧고 자연스럽게, 두 문장 이내."""


def _closing(facts: dict) -> tuple[str, list[dict]]:
    """마무리 문장 — LLM 표현 + 검증(금지표현·질문형), 실패 시 결정론 폴백."""

    fallback = (
        "여기까지가 이력서에서 읽어낸 내용이에요. 앞서 주신 공고와 대조해 지원 가능성 진단을 해볼까요?"
        if facts.get("hasPosting")
        else "여기까지가 이력서에서 읽어낸 내용이에요. 대조해보고 싶은 공고가 있으면 원문이나 URL을 주세요 — 지원 가능성 진단까지 해드릴게요."
    )
    read, warnings = run_structured(
        _ClosingWrite, _CLOSING_SYSTEM, json.dumps(facts, ensure_ascii=False),
        node="resume_diagnosis_closing",
    )
    text = (read.reply or "").strip() if read is not None else ""
    if not text or "?" not in text or any(expr in text for expr in FORBIDDEN_EXPRESSIONS):
        return fallback, warnings
    return text, warnings


def _labels(items: list, *keys: str) -> list[str]:
    out = []
    for item in items or []:
        text = " ".join(str(item.get(k) or "").strip() for k in keys).strip()
        if text:
            out.append(text)
    return out


def _summary_reply(profile: dict, evidenced: list[str], unverified: list[str],
                   empty_sections: list[str], closing: str) -> str:
    """읽어낸 항목을 **줄로 나눠** 요약 — 순수 조립, LLM 없음.

    공고 정리(posting_analysis)와 같은 형식: 라벨은 **굵게**, 목록은 끝까지 나열.
    같은 항목이 우측 패널(PROFILE_CONTEXT/context.profile)에도 표로 간다.
    """

    lines = ["이력서를 정리했어요."]

    skills = [s.get("name", "") for s in (profile.get("skills") or []) if s.get("name")]
    if skills:
        line = f"· **기술 스택** {len(skills)}개 — {', '.join(skills)}"
        if unverified:
            line += f" (이 중 경험 근거 없이 기재만 된 것 {len(unverified)}개: {', '.join(unverified)})"
        lines.append(line)

    projects = _labels(profile.get("projects"), "title")
    if projects:
        lines.append(f"· **프로젝트** {len(projects)}건 — {' / '.join(projects)}")

    experiences = _labels(profile.get("experiences"), "company", "role")
    lines.append(f"· **경력** {len(experiences)}건 — {' / '.join(experiences)}" if experiences
                 else "· **경력** — 재직 이력 없음")

    education = _labels(profile.get("education"), "school", "major")
    if education:
        lines.append(f"· **학력** — {' / '.join(education)}")
    certifications = _labels(profile.get("certifications"), "name")
    if certifications:
        lines.append(f"· **자격증** — {', '.join(certifications)}")
    languages = _labels(profile.get("languages"), "name", "testName", "score")
    if languages:
        lines.append(f"· **어학** — {', '.join(languages)}")
    if empty_sections:
        lines.append(f"· 비어 있는 섹션 — {', '.join(empty_sections)}")

    lines.append("")
    lines.append(closing)
    return "\n".join(lines)


def run(session: dict[str, Any]) -> AgentResult:
    profile, warnings = ensure_profile(session)

    skill_evidence: dict = profile.get("skillEvidence") or {}
    skills = [s.get("name", "") for s in profile.get("skills", []) if s.get("name")]
    evidenced = [s for s in skills if skill_evidence.get(s)]
    unverified = [s for s in skills if not skill_evidence.get(s)]

    empty_sections = [
        label for key, label in _SECTION_LABELS.items() if not profile.get(key)
    ]
    section_counts = {key: len(profile.get(key) or []) for key in _SECTION_LABELS}

    if not any(profile.get(k) for k in _SECTION_LABELS):
        return AgentResult(
            reply="이력서에서 읽어낼 항목을 찾지 못했어요. 파일이 제대로 읽혔는지 확인하거나 원문을 붙여넣어 주시겠어요?",
            warnings=warnings,
        )

    missing = find_missing_enum_fields(profile)
    completion_questions = build_completion_questions(missing)

    from jobis_ai.orchestrator.session import recent_history

    closing, closing_warnings = _closing({
        "userMessage": str(session.get("last_message") or ""),
        "recentHistory": recent_history(session, max_items=4),
        "resume": {"skillCount": len(skills), "projectCount": section_counts["projects"],
                   "hasExperience": bool(profile.get("experiences"))},
        "hasPosting": bool(session.get("job_posting")),
    })

    return AgentResult(
        reply=_summary_reply(profile, evidenced, unverified, empty_sections, closing),
        data={
            "sectionCounts": section_counts,
            "evidencedSkills": evidenced,
            "unverifiedSkills": unverified,
            "emptySections": empty_sections,
        },
        warnings=warnings + closing_warnings,
        followUpQuestions=[{
            "field": "confirm_fit",
            # 이 턴에 실제로 한 말 — UI 는 이걸 다시 그리지 않고 답변만 기다린다.
            "question": closing,
        }] + completion_questions,
    )
