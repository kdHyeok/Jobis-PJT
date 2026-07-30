"""fit_analysis 도구 — 기존 판정 엔진(build_graph)의 대화 진입 래퍼.

판정 로직은 한 줄도 없다. 세션 자산(이력서·공고)을 AnalyzeRequest/GraphState 로 변환해
판정 파이프라인을 부르고, 결과를 그대로 전달한다(dispatch만, judge 금지).

**도구다 — 말하지 않는다.** 등급·요약·대안 공고·다음 행동 제안은 전부 표현이므로
`tool_render.render_fit_analysis` 로 옮겼다(A단계 구분: 말을 하는가). 여기 남은 것은
"무엇을 계산했나"뿐이고, 문구를 고칠 때 이 파일을 건드릴 일은 없다.

이 도구의 결과는 **뒤에 예정된 단계의 타당성을 바꾼다** — 등급이 낮거나 판정이 완료되지
않으면 그 위에서 도는 자소서·면접은 근거가 없다. 그 전이는 `orchestrator/observe_rules.py`
가 결정론으로 처리한다(등급 하·판정불가면 생성 단계를 지원 경로 설계로 교체, 판정이
승격되지 않으면 전제 붕괴로 제외). 여기서 판단하지 않는다.
"""

from __future__ import annotations

import uuid
from typing import Any

from jobis_ai.agents import AgentResult
from jobis_ai.agents._common import ensure_posting_text
from jobis_ai.contracts.api import AnalyzeOptions, AnalyzeRequest, JobPostingInput
from jobis_ai.service import request_to_state, run_pipeline

# 대화 경로에는 준비 기간 입력 폼이 없으므로 기본값을 가정하고, 가정임을 응답에 명시한다.
DEFAULT_WEEKS = 8
DEFAULT_HOURS = 10


def run(session: dict[str, Any]) -> AgentResult:
    """세션의 이력서+공고로 적합도 판정을 실행하고 결과를 세션에 남긴다."""

    # URL 자산이면 먼저 수집해 원문으로 승격한다(D62) — 판정 파이프라인이 재수집하지 않는다.
    _, fetch_warnings = ensure_posting_text(session)
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

    # 완료된 분석만 세션 자산으로 승격한다 — need_more_info 의 미완성 결과를 저장하면
    # 다음 턴 라우터가 "분석 있음"으로 오판해 자소서·면접 에이전트가 빈 근거 위에서 돈다.
    session_updates: dict = {}
    if response.status == "completed":
        session_updates["analysis"] = result
        if response.roadmap:
            # 로드맵도 세션 자산으로 승격 — roadmap_manager 가 대화로 조회한다.
            session_updates["roadmap"] = result["roadmap"]

    # 표현이 알아야 하지만 판정 결과에는 없는 것 — 준비 기간을 사용자가 준 게 아니라
    # 우리가 가정했는지. 세션 자산(analysis)에는 넣지 않는다(판정 산출물을 오염시키지 않는다).
    data = dict(result)
    if not session.get("preparationPeriodWeeks"):
        data["assumedPeriod"] = {"weeks": DEFAULT_WEEKS, "hours": DEFAULT_HOURS}

    return AgentResult(
        reply="",                       # 도구는 말하지 않는다 — 문장은 render 가 만든다
        data=data,
        warnings=fetch_warnings + list(response.warnings),
        followUpQuestions=list(response.followUpQuestions),
        sessionUpdates=session_updates,
    )
