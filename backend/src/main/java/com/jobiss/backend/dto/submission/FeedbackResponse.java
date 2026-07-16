package com.jobiss.backend.dto.submission;

import com.fasterxml.jackson.annotation.JsonRawValue;

import java.time.LocalDateTime;

/**
 * 피드백 리포트 응답. report 는 DB의 JSON 문자열을 그대로 내보낸다.
 */
public record FeedbackResponse(
        Long submissionId,
        String status,
        LocalDateTime reviewedAt,
        @JsonRawValue String report
) {
}
