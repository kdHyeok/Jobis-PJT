"""interview_prep 에이전트 — 적합도 분석 결과 기반 면접 예상 질문 (개선방안 Phase 3).

**판정 결과의 소비자.** 세션의 analysis(AnalyzeResponse) 산출물에서만 질문을 만든다 —
분석에 없는 역량·경험을 소재로 삼지 않는다(근거 제한). MVP 는 결정론 템플릿 생성이라
LLM 호출이 없고, 문구 다듬기는 이후 말하기 계층(nl_render)에 붙인다.
"""

from __future__ import annotations

from typing import Any

from jobis_ai.agents import AgentResult

_MAX_QUESTIONS_PER_KIND = 5


def _gap_questions(gaps: list[dict]) -> list[dict]:
    out: list[dict] = []
    for gap in gaps[:_MAX_QUESTIONS_PER_KIND]:
        skills = gap.get("missingSkills") or []
        topic = ", ".join(skills) if skills else str(gap.get("requirementId", ""))
        if not topic:
            continue
        out.append({
            "type": "gap",
            "topic": topic,
            "question": (
                f"{topic} 경험이 부족한 것으로 보이는데, 이 부분을 어떻게 보완할 계획인지 "
                "설명해 주시겠어요?"
            ),
            "basis": gap.get("reason", ""),
            "severity": gap.get("severity", ""),
        })
    return out


def _strength_questions(strengths: list[dict]) -> list[dict]:
    out: list[dict] = []
    for strength in strengths[:_MAX_QUESTIONS_PER_KIND]:
        skills = strength.get("matchedSkills") or []
        if not skills:
            continue
        topic = ", ".join(skills[:3])
        out.append({
            "type": "strength",
            "topic": topic,
            "question": (
                f"{topic}을(를) 실제 프로젝트나 업무에서 어떻게 활용했는지, 본인이 기여한 부분을 "
                "중심으로 구체적으로 설명해 주시겠어요?"
            ),
            "basis": strength.get("text", ""),
        })
    return out


def run(session: dict[str, Any]) -> AgentResult:
    analysis: dict = session.get("analysis") or {}
    gaps = list(analysis.get("gaps") or [])
    strengths = list(analysis.get("strengths") or [])

    questions = _gap_questions(gaps) + _strength_questions(strengths)

    if not questions:
        return AgentResult(
            reply=(
                "적합도 분석 결과에 질문을 만들 만한 강점·부족 역량 정보가 없습니다. "
                "먼저 공고 적합도 분석을 다시 실행해 주세요."
            ),
            warnings=[{
                "code": "no_interview_basis",
                "message": "interview_prep: analysis 에 gaps/strengths 가 비어 질문을 생성하지 않았습니다.",
            }],
        )

    gap_count = sum(1 for q in questions if q["type"] == "gap")
    strength_count = len(questions) - gap_count
    reply = (
        f"분석 결과를 바탕으로 면접 예상 질문 {len(questions)}개를 준비했습니다 — "
        f"보완이 필요한 역량 관련 {gap_count}개, 강점 검증 관련 {strength_count}개입니다. "
        "각 질문은 적합도 분석에서 확인된 항목만 근거로 삼았습니다."
    )

    return AgentResult(reply=reply, data={"questions": questions})
