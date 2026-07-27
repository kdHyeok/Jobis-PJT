"""fit_analysis 에이전트 — 기존 판정 엔진(build_graph)의 대화 진입 래퍼.

판정 로직은 한 줄도 없다. 세션 자산(이력서·공고)을 AnalyzeRequest/GraphState 로 변환해
판정 파이프라인을 부르고, 결과를 그대로 전달한다(dispatch만, judge 금지).
"""

from __future__ import annotations

import uuid
from typing import Any

from jobis_ai.agents import AgentResult
from jobis_ai.contracts.api import AnalyzeOptions, AnalyzeRequest, JobPostingInput
from jobis_ai.service import request_to_state, run_pipeline

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
        reply = response.summary or f"적합도 판정 결과: {grade} 등급입니다."
        if not session.get("preparationPeriodWeeks"):
            reply += f" (준비 기간은 {DEFAULT_WEEKS}주·주 {DEFAULT_HOURS}시간을 가정했습니다.)"

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
        warnings=list(response.warnings),
        followUpQuestions=list(response.followUpQuestions),
        sessionUpdates=session_updates,
    )
