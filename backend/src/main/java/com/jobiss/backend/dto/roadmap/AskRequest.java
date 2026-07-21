package com.jobiss.backend.dto.roadmap;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

/**
 * 로드맵에 물어보기 요청. 저장된 로드맵(analysisId + routeId) 맥락에서 자유 질문을 던진다.
 */
public record AskRequest(
        @NotBlank String analysisId,
        @NotBlank String routeId,
        @NotBlank @Size(max = 500) String question
) {
}
