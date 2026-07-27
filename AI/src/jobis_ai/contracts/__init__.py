"""백엔드 ↔ AI 서버, 그리고 에이전트 간 데이터 계약(스키마).

설계 문서 15장(백엔드 계약)과 8~14장(에이전트별 출력 스키마)을 Pydantic 모델로 고정한다.
계약 우선 개발 원칙(설계 15.4)에 따라, 이 스키마를 먼저 확정하고 양측이 mock 으로 병렬 개발한다.
"""

from jobis_ai.contracts.api import (
    AnalyzeOptions,
    AnalyzeRequest,
    AnalyzeResponse,
    JobPostingInput,
    ResponseMeta,
    SourceType,
)

__all__ = [
    "AnalyzeOptions",
    "AnalyzeRequest",
    "AnalyzeResponse",
    "JobPostingInput",
    "ResponseMeta",
    "SourceType",
]
