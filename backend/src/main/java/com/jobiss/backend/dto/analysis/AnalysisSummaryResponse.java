package com.jobiss.backend.dto.analysis;

import com.jobiss.backend.domain.AnalysisRun;

/**
 * 사이드바 "최근 분석" 목록 항목. 회사·직무는 AI가 파악해 채워진 값(없으면 '분석').
 */
public record AnalysisSummaryResponse(
        String analysisId,
        String company,
        String role,
        String status,
        String createdAt,
        String parentAnalysisId,
        String conversationId    // 이 분석이 들어 있는 대화 — 눌렀을 때 대화째로 열기 위해
) {
    public static AnalysisSummaryResponse from(AnalysisRun run) {
        var job = run.getJobPosting();
        String company = (job.getCompany() == null || job.getCompany().isBlank()) ? "분석" : job.getCompany();
        return new AnalysisSummaryResponse(
                run.getAnalysisId(),
                company,
                job.getRole(),
                run.getStatus().name(),
                run.getCreatedAt() == null ? null : run.getCreatedAt().toString(),
                run.getParentAnalysisId(),
                run.getConversation() == null ? null : run.getConversation().getConversationId());
    }
}
