package com.jobiss.backend.dto.chat;

/**
 * 에이전트가 이번 턴에 요청한 자료.
 * field — "resume" | "job_posting" | "preferences" …  (AI 의 followUpQuestions.field)
 * question — 사용자에게 보여줄 요청 문구
 *
 * 프론트는 이 값을 보고 **그때만** 입력 카드를 띄우고, 다음 발화를 어느 칸으로 보낼지 정한다.
 * 입력칸을 화면에 상시 붙여두지 않는 이유다.
 */
public record AskedFor(
        String field,
        String question
) {
}
