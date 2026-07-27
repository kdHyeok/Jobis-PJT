"""coverletter_draft 에이전트 — 자소서 초안 (개선방안 Phase 3, apply_agent P2~P5 부분).

행동 계층 골격의 부분 구현:
  P2 MAP    [룰]   프로필·분석 결과 → 근거 사실 목록(facts) 결정론 조립
  P3 DRAFT  [LLM]  근거제한 초안 생성 — facts 밖 사실 서술 금지
  P4 VERIFY [룰]   금지표현 + 스킬 근거성 검사(근거 없는 스킬 언급 문장 제거)
  P5 GATE   [중단] 산출물은 항상 "초안" — 사용자 검토 없이 완성본이 되지 않는다

두 절대 규칙(agent_develop §2.5): ① 문항 답을 지어내지 않는다 ② 이력서에 없는 성과를
서술하지 않는다 — 이력서에 없는 자소서 성과는 사용자 이름으로 나가는 거짓말이다.

LLM 미설정(개발 모드)이면 facts 만으로 결정론 템플릿 초안을 만든다(창작 0%). 호출 실패면
가짜 초안을 내지 않고 정직하게 실패를 알린다(structured.py 규율 계승).
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from jobis_ai.agents import AgentResult
from jobis_ai.agents._common import ensure_profile
from jobis_ai.skill_taxonomy import get_skill_taxonomy
from jobis_ai.structured import llm_unconfigured, run_structured
from jobis_ai.verify_rules import FORBIDDEN_EXPRESSIONS

_MAX_FACTS = 20

_DRAFT_SYSTEM = """너는 자기소개서 초안 작성기다. 아래 규칙을 절대 어기지 않는다.

1. [facts] 목록에 있는 사실만 쓴다. 목록에 없는 경험·성과·수치·기술을 창작하면 그것은
   지원자 이름으로 나가는 거짓말이다. 과장도 금지다.
2. 합격 가능성을 단정하지 않는다. "반드시", "무조건", "확실히" 같은 단정 표현을 쓰지 않는다.
3. 지원 동기 문단은 [requirements]의 요구 역량과 [facts]의 접점만으로 쓴다.
4. 보완 계획 문단은 [gaps]에 명시된 부족 역량만 다룬다. 부족을 숨기지 말고 학습 의지로 서술한다.
5. 각 문단은 3~5문장, 한국어 존댓말."""


class _DraftRead(BaseModel):
    """초안 3문단 — 이 스키마 밖의 산출(합격 예측 등)은 구조적으로 불가능하다.

    **각 필드의 description 을 유지한다.** 구조화 출력에서 설명이 없으면 모델이 문단 칸을
    '제목'처럼 취급해 한 줄만 채운다(career_chat 에서 실측: 설명 없음 43자 → 설명 있음 1400자대).
    """

    motivation: str = Field(default="", description=(
        "지원 동기 문단. [requirements] 의 요구 역량과 [facts] 의 접점만으로 3~5문장, 한국어 존댓말. "
        "한 문단의 완성된 글로 쓴다 — 제목이나 한 줄 요약이 아니다."))
    strengthsParagraph: str = Field(default="", description=(
        "강점 문단. [facts] 에 있는 사실만 근거로 3~5문장. 프로젝트·수치는 facts 에 적힌 그대로 인용하고 "
        "없는 경험을 만들지 않는다."))
    improvementParagraph: str = Field(default="", description=(
        "보완 계획 문단. [gaps] 에 명시된 부족 역량만 다뤄 3~5문장. 부족을 숨기지 말고 "
        "무엇을 어떻게 메울지 구체적으로 쓴다."))


# --- P2 MAP [룰] — 근거 사실 목록 조립 -----------------------------------------
def _collect_facts(profile: dict) -> list[str]:
    """프로필에서 초안 재료가 될 사실 문장을 모은다. 여기 없는 것은 초안에 못 들어간다."""

    facts: list[str] = []
    for p in profile.get("projects", []):
        base = f"프로젝트 '{p.get('title', '')}'"
        if p.get("role"):
            base += f"에서 {p['role']} 역할 수행"
        if p.get("techStack"):
            base += f" (기술: {', '.join(p['techStack'][:5])})"
        if p.get("summary"):
            base += f" — {p['summary']}"
        facts.append(base)
        facts.extend(f"'{p.get('title', '')}' 성과: {a}" for a in p.get("achievements", []))
    for e in profile.get("experiences", []):
        text = f"{e.get('company', '')} {e.get('role', '')} 경력"
        if e.get("period"):
            text += f" ({e['period']})"
        if e.get("summary"):
            text += f" — {e['summary']}"
        facts.append(text.strip())
    facts.extend(
        f"자격증: {c.get('name', '')} ({c.get('status', '')})"
        for c in profile.get("certifications", []) if c.get("name")
    )
    facts.extend(
        f"수상: {a.get('title', '')} ({a.get('organization', '')})"
        for a in profile.get("awards", []) if a.get("title")
    )
    return [f for f in facts if f.strip()][:_MAX_FACTS]


def _allowed_skills(profile: dict) -> set[str]:
    """초안이 '보유'라고 말해도 되는 스킬 — 프로필에 실재하는 것만."""

    skills = {s.get("name", "").lower() for s in profile.get("skills", [])}
    for p in profile.get("projects", []):
        skills.update(t.lower() for t in p.get("techStack", []))
    skills.update(k.lower() for k in (profile.get("skillEvidence") or {}))
    return {s for s in skills if s}


# --- P3 DRAFT — LLM(근거제한) 또는 결정론 템플릿 폴백 ---------------------------
def _draft_input(facts: list[str], requirements: list[dict], gaps: list[dict]) -> str:
    lines = ["[facts]"] + [f"- {f}" for f in facts]
    lines += ["", "[requirements]"] + [
        f"- {r.get('text', '')}" for r in requirements if r.get("text")
    ]
    lines += ["", "[gaps]"] + [
        f"- {', '.join(g.get('missingSkills') or []) or g.get('requirementId', '')}"
        for g in gaps
    ]
    return "\n".join(lines)


def _template_draft(facts: list[str], requirements: list[dict], gaps: list[dict]) -> _DraftRead:
    """LLM 없는 개발 모드 폴백 — facts 문장을 그대로 이어 붙인다(창작 없음)."""

    req_texts = [r.get("text", "") for r in requirements if r.get("text")][:3]
    gap_topics = [
        ", ".join(g.get("missingSkills") or []) or g.get("requirementId", "") for g in gaps
    ][:3]
    return _DraftRead(
        motivation=(
            "채용 공고의 요구 역량(" + "; ".join(req_texts) + ")과 맞닿은 경험을 쌓아 왔기에 지원합니다."
            if req_texts else "해당 직무와 맞닿은 경험을 쌓아 왔기에 지원합니다."
        ),
        strengthsParagraph=" ".join(f"{f}." if not f.endswith(".") else f for f in facts[:5]),
        improvementParagraph=(
            "다만 " + "; ".join(t for t in gap_topics if t) + " 역량은 아직 부족하여, 학습 계획을 세워 보완하고 있습니다."
            if any(gap_topics) else ""
        ),
    )


# --- P4 VERIFY [룰] -------------------------------------------------------------
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?다])\s+")


def _verify_draft(draft: _DraftRead, allowed: set[str]) -> tuple[_DraftRead, list[dict]]:
    """금지표현 경고 + 강점 문단의 근거 없는 스킬 언급 문장 제거."""

    warnings: list[dict] = []

    full_text = " ".join([draft.motivation, draft.strengthsParagraph, draft.improvementParagraph])
    for bad in FORBIDDEN_EXPRESSIONS:
        if bad in full_text:
            warnings.append({
                "code": "forbidden_expression",
                "message": f"coverletter_draft: 단정 표현 '{bad}' 발견 — 초안 검토 시 수정이 필요합니다.",
            })

    # 강점 문단은 "보유 역량 주장"이므로 프로필에 없는 스킬이 나오면 그 문장을 제거한다.
    taxonomy = get_skill_taxonomy()
    kept: list[str] = []
    for sentence in _SENTENCE_SPLIT.split(draft.strengthsParagraph):
        mentioned = {s.lower() for s in taxonomy.find_in_text(sentence)}
        ungrounded = mentioned - allowed
        if ungrounded:
            warnings.append({
                "code": "ungrounded_skill_removed",
                "message": (
                    "coverletter_draft: 이력서에 근거가 없는 기술 언급 문장을 제거했습니다 — "
                    f"{', '.join(sorted(ungrounded))}"
                ),
            })
            continue
        kept.append(sentence)

    verified = draft.model_copy(update={"strengthsParagraph": " ".join(kept).strip()})
    return verified, warnings


# --- 진입점 ----------------------------------------------------------------------
def run(session: dict[str, Any]) -> AgentResult:
    analysis: dict = session.get("analysis") or {}
    profile, warnings = ensure_profile(session)

    facts = _collect_facts(profile)
    requirements = list(analysis.get("requirements") or [])
    gaps = list(analysis.get("gaps") or [])

    if not facts:
        return AgentResult(
            reply=(
                "이력서에서 자소서 재료가 될 경험·프로젝트를 찾지 못했습니다. "
                "지어내서 쓸 수는 없어요 — 이력서에 경험을 보강한 뒤 다시 요청해 주세요."
            ),
            warnings=warnings + [{
                "code": "no_coverletter_facts",
                "message": "coverletter_draft: 근거 사실이 없어 초안을 생성하지 않았습니다(창작 금지).",
            }],
        )

    read, llm_warnings = run_structured(
        _DraftRead, _DRAFT_SYSTEM, _draft_input(facts, requirements, gaps),
        node="coverletter_draft",
    )
    warnings.extend(llm_warnings)

    if read is None:
        if llm_unconfigured(llm_warnings):
            read = _template_draft(facts, requirements, gaps)  # 개발 모드 — 창작 없는 템플릿
        else:
            return AgentResult(
                reply="자소서 초안 생성에 실패했습니다. 잠시 후 다시 시도해 주세요.",
                warnings=warnings,
            )

    verified, verify_warnings = _verify_draft(read, _allowed_skills(profile))
    warnings.extend(verify_warnings)

    draft_payload = {
        "status": "draft_pending_review",   # P5 GATE — 사용자 검토 전에는 항상 초안
        "motivation": verified.motivation,
        "strengthsParagraph": verified.strengthsParagraph,
        "improvementParagraph": verified.improvementParagraph,
        "factsUsed": facts,
    }

    reply = (
        "자소서 초안을 만들었습니다. 이력서에서 확인된 사실만 사용했고, 제출 전 반드시 직접 "
        "검토·수정해 주세요. 수정하고 싶은 문단을 말씀해 주시면 다시 다듬어 드릴게요."
    )
    if verify_warnings:
        reply += " (검증 단계에서 일부 문장이 조정되었습니다 — warnings 참고)"

    return AgentResult(
        reply=reply,
        data=draft_payload,
        warnings=warnings,
        sessionUpdates={"coverletter": draft_payload},
    )
