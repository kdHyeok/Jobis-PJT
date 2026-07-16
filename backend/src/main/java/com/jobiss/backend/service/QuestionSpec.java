package com.jobiss.backend.service;

/** 분석 엔진이 만들어내는 추가 질문 1건의 명세(DB 저장 전 형태). */
public record QuestionSpec(
        int seq,
        String field,
        String title,
        String why,
        String defaultAnswer,
        String effect
) {
}
