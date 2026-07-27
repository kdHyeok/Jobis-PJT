package com.jobiss.backend.dto.analysis;

import com.fasterxml.jackson.annotation.JsonRawValue;
import com.jobiss.backend.domain.JobPosting;

/** 상태/결과 화면 헤더에 쓰는 공고 요약. stack 은 JSON 배열 그대로 내보낸다. */
public record JobPostingBrief(
        String code,
        String company,
        String role,
        String career,
        String due,
        @JsonRawValue String stack
) {
    public static JobPostingBrief from(JobPosting j) {
        return new JobPostingBrief(j.getCode(), j.getCompany(), j.getRole(), j.getCareer(), j.getDue(), j.getStack());
    }
}
