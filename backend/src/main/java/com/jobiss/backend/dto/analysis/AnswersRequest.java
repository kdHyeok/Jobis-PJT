package com.jobiss.backend.dto.analysis;

import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;

import java.util.List;

/** 추가 질문 답변 제출(3개 한 번에). */
public record AnswersRequest(
        @NotEmpty List<AnswerItem> answers
) {
    public record AnswerItem(
            @NotNull Long questionId,
            String answer
    ) {
    }
}
