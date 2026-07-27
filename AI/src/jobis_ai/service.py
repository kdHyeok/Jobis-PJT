"""요청 → 그래프 실행 → 응답 (백엔드가 호출할 진입점, 설계 15장).

향후 FastAPI 라우터(`POST /api/v1/analyze`)가 이 함수를 그대로 호출한다.
"""

from __future__ import annotations

import uuid

from jobis_ai.contracts.api import AnalyzeRequest, AnalyzeResponse
from jobis_ai.graph.builder import build_graph
from jobis_ai.graph.state import GraphState

# 그래프는 상태를 갖지 않으므로 프로세스당 한 번만 컴파일해 재사용한다.
_APP = None


def _get_app():
    global _APP
    if _APP is None:
        _APP = build_graph()
    return _APP


def request_to_state(request: AnalyzeRequest, analysis_id: str) -> GraphState:
    """AnalyzeRequest → 초기 GraphState (설계 15.1)."""

    return {
        "analysisId": analysis_id,
        "userId": request.userId,
        "jobPostingInput": request.jobPostingInput.model_dump(),
        "selectedExperienceIds": request.selectedExperienceIds,
        "preparationPeriodWeeks": request.preparationPeriodWeeks,
        "availableHoursPerWeek": request.availableHoursPerWeek,
        "includeAlternatives": request.options.includeAlternatives,
        "followUpQuestions": [],
        "sources": [],
        "toolLog": [],
        "warnings": [],
        "retryCount": {},
        "isComplete": False,
    }


def run_analysis(request: AnalyzeRequest) -> AnalyzeResponse:
    """전체 분석 파이프라인을 실행하고 계약 응답을 반환한다."""

    analysis_id = request.analysisId or str(uuid.uuid4())
    init_state = request_to_state(request, analysis_id)

    final_state = _get_app().invoke(init_state)

    result = final_state.get("analysisResult") or {}
    return AnalyzeResponse(**result)
