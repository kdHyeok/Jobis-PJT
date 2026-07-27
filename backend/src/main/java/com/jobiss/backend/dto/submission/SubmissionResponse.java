package com.jobiss.backend.dto.submission;

/** 산출물 제출 접수 응답. */
public record SubmissionResponse(
        Long submissionId,
        String status
) {
}
