"""공유 상태(GraphState)와 진행 상태 코드 (설계 13.2 / 15.1 / 17.1).

모든 노드가 읽고 갱신하는 단일 상태 객체. 누적 필드는 리듀서(add)로 병합한다.
"""

from __future__ import annotations

from operator import add
from typing import Annotated, Optional, TypedDict


def merge_dicts(a: Optional[dict], b: Optional[dict]) -> dict:
    """dict 병합 리듀서 — 병렬 분기(파싱 ∥ 프로필 빌드)가 같은 스텝에서 다른 키를
    갱신해도 충돌하지 않게 한다. 노드는 기존 값을 복사해 반환하므로 병합=교체와 동치."""

    return {**(a or {}), **(b or {})}


def last_value(a, b):
    """마지막 값 리듀서 — status 처럼 표시용 스칼라가 병렬 스텝에서 두 번 갱신돼도
    에러 대신 나중 값을 취한다(진행 표시는 어느 쪽이든 무방)."""

    return b if b is not None else a


class Status:
    """진행 상태 코드 (설계 17.1). 프론트 진행 표시/에이전트 시각화에 사용."""

    PARSING_JOB = "parsing_job"          # 채용공고 분석 중
    BUILDING_PROFILE = "building_profile"  # 사용자 경험 조회 중
    NEED_INFO = "need_info"              # 부족한 정보 확인 중
    ANALYZING_GAP = "analyzing_gap"      # 강점·부족 역량 분석 중
    FETCHING_COMPANY = "fetching_company"  # 기업 정보 검색 중
    PLANNING_ROADMAP = "planning_roadmap"  # 준비 로드맵 생성 중
    FINDING_ALTERNATIVES = "finding_alternatives"  # 유사 공고 비교 중
    VERIFYING = "verifying"              # 최종 결과 검증 중
    COMPLETED = "completed"              # 완료


class GraphState(TypedDict, total=False):
    """LangGraph 공유 상태 (설계 15.1).

    total=False: 노드가 부분 갱신(partial update)만 반환해도 되도록 모든 키를 optional 로 둔다.
    """

    # --- 입력 (요청 시 확정) ---
    analysisId: str
    userId: int
    jobPostingInput: dict            # { sourceType: "url|text|file", value: str }
    selectedExperienceIds: list[int]
    preparationPeriodWeeks: int
    availableHoursPerWeek: int
    includeAlternatives: bool

    # 이력서/포트폴리오 원천 (설계 9.3 resume/portfolio text).
    # API 계약(AnalyzeRequest)에는 없고, 실서비스는 selectedExperienceIds 로 백엔드 DB 를 읽는다.
    # 로컬 테스트에서는 이 내부 필드에 { sourceType, value } 를 직접 주입해 .docx 등을 먹인다.
    resumeInput: dict

    # --- 중간 산출물 (노드가 채움) ---
    normalizedJobPosting: Optional[dict]
    normalizedUserProfile: Optional[dict]
    gapAnalysisResult: Optional[dict]
    roadmapResult: Optional[dict]
    alternativeJobs: Optional[list[dict]]
    verification: Optional[dict]      # Result Verifier 판정 (라우팅에 사용)
    # 정보 충분성 판정 (check_sufficiency 산출, route_sufficiency 가 읽음).
    # { sufficient: bool, evidenceCount: int, undecidableRequiredCount: int, reasons: list[str] }
    sufficiency: Optional[dict]
    # 프로필 결측(enum) 보완 질문 (check_profile_completeness 산출). **비블로킹** —
    # followUpQuestions 와 달리 라우팅에 쓰이지 않고 assemble_output 이 그대로 실어 내보낸다.
    profileCompletionQuestions: Optional[list[dict]]

    # --- 제어/누적 (리듀서로 병합) ---
    followUpQuestions: list[dict]
    sources: Annotated[list[dict], add]
    toolLog: Annotated[list[dict], add]
    warnings: Annotated[list[dict], add]
    retryCount: Annotated[dict, merge_dicts]    # { nodeName: count }
    nodeFailed: Annotated[dict, merge_dicts]    # { nodeName: 생성 실패 여부 } — 오케스트라의 노드별 재지시 판단용
    status: Annotated[str, last_value]          # 현재 진행 단계 코드
    isComplete: bool

    # --- 조립 결과 (assemble_output 산출; 설계 상태 스키마의 구현 확장) ---
    analysisResult: Optional[dict]    # AnalyzeResponse 형태
