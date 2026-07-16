package com.jobiss.backend.dto.analysis;

import com.fasterxml.jackson.annotation.JsonRawValue;

/**
 * 결과 보고서 응답. result 는 DB에 저장된 §B JSON 문자열을
 * 이스케이프 없이 JSON 객체 그대로 내보낸다.
 */
public record ResultResponse(
        JobPostingBrief jobPosting,
        @JsonRawValue String result
) {
}
