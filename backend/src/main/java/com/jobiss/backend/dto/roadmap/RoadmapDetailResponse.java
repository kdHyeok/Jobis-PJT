package com.jobiss.backend.dto.roadmap;

import com.fasterxml.jackson.annotation.JsonRawValue;

import java.util.List;

/**
 * 로드맵 페이지 단건 응답. 저장된 로드맵 + 스텝별 진행 상태(progress)를 함께 내보내
 * 페이지가 한 번의 호출로 "요건 × 증거" 매트릭스와 제출 상태를 그릴 수 있게 한다.
 * roadmap 은 가짜 AI가 만든 JSON 문자열을 이스케이프 없이 그대로 내보낸다.
 */
public record RoadmapDetailResponse(
        Long id,
        String analysisId,
        String routeId,
        String goalLabel,
        @JsonRawValue String roadmap,
        boolean representative,
        List<StepProgressResponse> progress
) {
}
