package com.jobiss.backend.dto.analysis;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;

import java.util.List;

/** 분석 시작 요청. 샘플 공고 코드 + 이번 분석에 쓸 자료 id 목록. */
public record AnalysisCreateRequest(
        @NotBlank String jobPostingCode,
        @NotEmpty(message = "자료를 1건 이상 선택해야 합니다.") List<Long> evidenceIds
) {
}
