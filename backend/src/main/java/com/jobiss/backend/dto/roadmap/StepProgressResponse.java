package com.jobiss.backend.dto.roadmap;

import com.fasterxml.jackson.annotation.JsonRawValue;

/**
 * 스텝 진행/재진단 결과 응답. verdict 는 가짜 AI가 만든 판정 JSON을 그대로 내보낸다(없으면 null).
 */
public record StepProgressResponse(
        int stepNo,
        String status,
        String submittedUrl,
        @JsonRawValue String verdict
) {
}
