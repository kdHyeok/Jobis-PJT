package com.jobiss.backend.dto.job;

import com.fasterxml.jackson.annotation.JsonRawValue;
import com.jobiss.backend.domain.JobPosting;

/**
 * 샘플 공고 응답. stack 은 DB에 JSON 문자열로 저장돼 있으므로
 * @JsonRawValue 로 이스케이프 없이 JSON 배열 그대로 내보낸다.
 */
public record JobSampleResponse(
        String code,
        String company,
        String role,
        String career,
        String due,
        String url,
        @JsonRawValue String stack
) {
    public static JobSampleResponse from(JobPosting j) {
        return new JobSampleResponse(
                j.getCode(), j.getCompany(), j.getRole(), j.getCareer(), j.getDue(), j.getUrl(), j.getStack());
    }
}
