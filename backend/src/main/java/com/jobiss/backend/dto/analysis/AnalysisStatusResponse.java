package com.jobiss.backend.dto.analysis;

/**
 * 분석 시작/상태 폴링 응답. status = 상태머신 값. parent* = 대체 재분석이면 원래 분석(breadcrumb용).
 * selectedRoute = 경로 비교에서 고른 주 경로 id(없으면 null) → 복원 시 선택 표시.
 */
public record AnalysisStatusResponse(
        String analysisId,
        String status,
        JobPostingBrief jobPosting,
        String message,
        String parentAnalysisId,
        String parentLabel,
        String selectedRoute
) {
}
