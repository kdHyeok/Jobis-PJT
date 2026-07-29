package com.jobiss.backend.dto.analysis;

import com.jobiss.backend.domain.AnalysisQuestion;

public record QuestionResponse(
        Long id,
        int seq,
        String field,
        String title,
        String why,
        String defaultAnswer,
        String effect
) {
    public static QuestionResponse from(AnalysisQuestion q) {
        return new QuestionResponse(q.getId(), q.getSeq(), q.getField(), q.getTitle(),
                q.getWhy(), q.getDefaultAnswer(), q.getEffect());
    }
}
