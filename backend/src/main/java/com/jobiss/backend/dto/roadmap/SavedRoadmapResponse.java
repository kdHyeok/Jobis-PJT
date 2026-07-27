package com.jobiss.backend.dto.roadmap;

import com.fasterxml.jackson.annotation.JsonRawValue;

/**
 * 저장된 로드맵 응답. roadmap 은 가짜 AI가 만든 JSON 문자열을 이스케이프 없이 그대로 내보낸다.
 * goalLabel = 목표 맥락(디딤돌이면 목표 회사·직무, 독립 목표면 null).
 */
public record SavedRoadmapResponse(
        Long id,
        String analysisId,
        String routeId,
        String goalLabel,
        @JsonRawValue String roadmap,
        boolean representative
) {
}
