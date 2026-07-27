"""요청 → 그래프 실행 → 응답 (백엔드가 호출할 진입점, 설계 15장).

향후 FastAPI 라우터(`POST /api/v1/analyze`)가 이 함수를 그대로 호출한다.
"""

from __future__ import annotations

import time
import uuid

from jobis_ai import trace
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


def run_pipeline(init_state: GraphState) -> AnalyzeResponse:
    """초기 상태로 판정 파이프라인을 1회 실행한다.

    run_analysis(HTTP 계약 경로)와 fit_analysis 에이전트(대화 경로)가 공유하는 실행부.
    대화 경로는 resumeInput 등 내부 필드를 상태에 직접 실어야 해서 상태 단위 진입점이 필요하다.
    """

    app = _get_app()

    if trace.active():
        # 관찰 모드 — 노드 단위로 스트리밍하며 각 노드가 갱신한 상태를 트레이스에 남긴다.
        # "updates"는 (노드 이름 → 부분 갱신), "values"는 병합된 전체 상태. 최종 상태는
        # 리듀서(누적 리스트 등)를 직접 재구현하지 않도록 values 의 마지막 것을 쓴다.
        final_state: dict = {}
        prev = time.perf_counter()
        for mode, chunk in app.stream(init_state, stream_mode=["updates", "values"]):
            if mode == "values":
                final_state = chunk
                continue
            now = time.perf_counter()
            for node_name, update in (chunk or {}).items():
                trace.emit("node", f"판정 엔진 노드: {node_name}", {
                    "node": node_name,
                    "durationMs": round((now - prev) * 1000),
                    "status": (update or {}).get("status"),
                    "update": update or {},
                })
            prev = now
    else:
        final_state = app.invoke(init_state)

    result = final_state.get("analysisResult") or {}
    return AnalyzeResponse(**result)


def run_analysis(request: AnalyzeRequest) -> AnalyzeResponse:
    """전체 분석 파이프라인을 실행하고 계약 응답을 반환한다."""

    analysis_id = request.analysisId or str(uuid.uuid4())
    return run_pipeline(request_to_state(request, analysis_id))
