package com.jobiss.backend.dto.roadmap;

import jakarta.validation.constraints.NotBlank;

/** 로드맵 생성(저장) 요청. analysisId + 그 안에서 고른 routeId(as_is|reinforce). */
public record GenerateRoadmapRequest(
        @NotBlank String analysisId,
        @NotBlank String routeId
) {
}
