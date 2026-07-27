package com.jobiss.backend.dto.analysis;

import jakarta.validation.constraints.NotBlank;

/** 경로 비교에서 주 경로 선택 요청. routeId = 결과 JSON의 routes[].id. */
public record SelectRouteRequest(
        @NotBlank String routeId
) {
}
