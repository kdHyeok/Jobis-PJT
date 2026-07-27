package com.jobiss.backend.dto.submission;

import jakarta.validation.constraints.NotBlank;

/** 산출물 제출 요청. */
public record SubmissionCreateRequest(
        @NotBlank String githubUrl,
        String deployUrl,
        String note
) {
}
