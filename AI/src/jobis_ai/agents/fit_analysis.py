"""fit_analysis 에이전트 — 기존 판정 엔진(build_graph)의 대화 진입 래퍼.

판정 로직은 한 줄도 없다. 세션 자산(이력서·공고)을 AnalyzeRequest/GraphState 로 변환해
판정 파이프라인을 부르고, 결과를 그대로 전달한다(dispatch만, judge 금지).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from pydantic import BaseModel, Field

from jobis_ai.agents import AgentResult
from jobis_ai.contracts.api import AnalyzeOptions, AnalyzeRequest, JobPostingInput
from jobis_ai.service import request_to_state, run_pipeline
from jobis_ai.structured import run_structured
from jobis_ai.verify_rules import FORBIDDEN_EXPRESSIONS


class _NextWrite(BaseModel):
    """판정 결과를 건넨 뒤 다음 행동을 제안하는 마무리 문장."""

    reply: str = Field(default="", description=(
        "판정 요약 아래에 붙일 한두 문장. 이 결과로 이어서 할 수 있는 일 — 준비 로드맵 확인, "
        "자소서 초안, 면접 예상 질문, (격차가 크면) 대안 공고 탐색 — 중 결과에 맞는 것을 "
        "제안하고 무엇부터 할지 묻는 질문으로 끝낸다. 판정 내용을 다시 요약하지 않는다. "
        "합격 가능성을 단정하지 않는다."))


_NEXT_SYSTEM = """너는 취업 서비스의 대화 상담원이다. 방금 공고×이력서 적합도 판정 결과를 사용자에게 보여줬다.
그 아래에 붙일 다음 행동 제안 문장을 쓴다.
- facts 의 grade(상/중/하)·topGap 에 맞는 다음 행동만 제안한다. 예: 격차가 크면 로드맵·대안 공고,
  적합도가 높으면 자소서·면접 준비.
- 제안 가능한 것: 준비 로드맵 확인, 자소서 초안 작성, 면접 예상 질문, 대안 공고 탐색.
- 응답은 무엇부터 할지 묻는 질문으로 끝난다. 두 문장 이내. 합격 가능성 단정 금지."""


def _next_steps(facts: dict) -> tuple[str, list[dict]]:
    """다음 행동 제안 — LLM 표현 + 검증(금지표현·질문형), 실패 시 결정론 폴백."""

    fallback = ("이 결과로 준비 로드맵 확인, 자소서 초안, 면접 예상 질문, 대안 공고 탐색을 "
                "이어서 할 수 있어요. 무엇부터 해볼까요?")
    read, warnings = run_structured(
        _NextWrite, _NEXT_SYSTEM, json.dumps(facts, ensure_ascii=False),
        node="fit_analysis_next",
    )
    text = (read.reply or "").strip() if read is not None else ""
    if not text or "?" not in text or any(expr in text for expr in FORBIDDEN_EXPRESSIONS):
        return fallback, warnings
    return text, warnings

# 대화 경로에는 준비 기간 입력 폼이 없으므로 기본값을 가정하고, 가정임을 응답에 명시한다.
DEFAULT_WEEKS = 8
DEFAULT_HOURS = 10


def run(session: dict[str, Any]) -> AgentResult:
    """세션의 이력서+공고로 적합도 판정을 실행하고 결과를 세션에 남긴다."""

    request = AnalyzeRequest(
        userId=int(session.get("userId") or 0),
        jobPostingInput=JobPostingInput(**session["job_posting"]),
        preparationPeriodWeeks=int(session.get("preparationPeriodWeeks") or DEFAULT_WEEKS),
        availableHoursPerWeek=int(session.get("availableHoursPerWeek") or DEFAULT_HOURS),
        options=AnalyzeOptions(includeAlternatives=True),
    )
    state = request_to_state(request, str(uuid.uuid4()))
    if session.get("resume"):
        state["resumeInput"] = session["resume"]

    response = run_pipeline(state)
    result = response.model_dump()

    if response.status == "need_more_info":
        # 무엇이 부족한지 **그 자리에서** 말한다. "아래 질문에 답해 주세요"라고만 하고 질문을
        # 싣지 않으면(대화 채널에는 질문 카드가 없다) 사용자는 무엇을 해야 할지 알 수 없다.
        asks = [str(q.get("text") or "").strip() for q in response.followUpQuestions]
        asks = [a for a in asks if a]
        if asks:
            reply = ("판정을 확정하려면 이것만 확인하면 돼요.\n"
                     + "\n".join(f"· {a}" for a in asks))
        else:
            reply = "판정을 확정할 근거가 이력서에서 확인되지 않았어요. 관련 경험을 조금 더 알려주실래요?"
    else:
        grade = response.fitGrade or "판정불가"
        # 등급·점수를 요약 앞에 명시한다 — 요약(LLM 표현)만 있으면 사용자가 등급을
        # 문장 뉘앙스로 추측해야 한다(실사용 피드백). 판정 데이터 그대로, 서술 없음.
        score_part = f" (가중 점수 {response.overallScore})" if response.overallScore is not None else ""
        head = f"**적합도 등급 {grade}**{score_part}"
        reply = f"{head}\n{response.summary}" if response.summary else f"{head} — 적합도 판정 결과입니다."
        if not session.get("preparationPeriodWeeks"):
            reply += f" (준비 기간은 {DEFAULT_WEEKS}주·주 {DEFAULT_HOURS}시간을 가정했습니다.)"
        # 판정을 건넨 뒤 다음 행동(로드맵·자소서·면접·대안 공고)을 제안한다 —
        # 결과에 따라 무엇을 할 수 있는지 사용자가 골라 이어가게 한다.
        top_gap = next((g.get("reason") or "" for g in (response.gaps or [])), "")
        next_line, next_warnings = _next_steps({
            "grade": grade, "topGap": top_gap,
            "hasRoadmap": bool(response.roadmap),
            "gapCount": len(response.gaps or []),
        })
        reply += "\n\n" + next_line

    # 완료된 분석만 세션 자산으로 승격한다 — need_more_info 의 미완성 결과를 저장하면
    # 다음 턴 라우터가 "분석 있음"으로 오판해 자소서·면접 에이전트가 빈 근거 위에서 돈다.
    session_updates: dict = {}
    if response.status == "completed":
        session_updates["analysis"] = result
        if response.roadmap:
            # 로드맵도 세션 자산으로 승격 — roadmap_manager 가 대화로 조회한다.
            session_updates["roadmap"] = result["roadmap"]

    return AgentResult(
        reply=reply,
        data=result,
        warnings=list(response.warnings) + (next_warnings if response.status == "completed" else []),
        followUpQuestions=list(response.followUpQuestions),
        sessionUpdates=session_updates,
    )
