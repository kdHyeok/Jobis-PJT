package com.jobiss.backend.dto.roadmap;

import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

/**
 * 스텝 재진단 요청. 저장된 로드맵(analysisId + routeId)의 stepNo 스텝에 대해
 * 산출물 링크(url)를 제출한다. url 은 submitted_url VARCHAR(500)과 맞춰 최대 500자.
 */
public record ReassessRequest(
        @NotBlank String analysisId,
        @NotBlank String routeId,
        @Min(1) int stepNo,
        @NotBlank @Size(max = 500) String url
) {
}
