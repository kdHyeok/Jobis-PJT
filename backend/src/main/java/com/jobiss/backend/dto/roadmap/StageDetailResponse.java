package com.jobiss.backend.dto.roadmap;

/**
 * 단계형 로드맵의 한 단계 상세 응답. detailJson = 가짜 AI가 생성한 단계 상세 JSON 문자열
 * (lessons·practice·artifact·criteria·questions·lessonDetails). 프론트가 JSON.parse 해서 렌더한다.
 */
public record StageDetailResponse(int stageNo, String detailJson) {
}
