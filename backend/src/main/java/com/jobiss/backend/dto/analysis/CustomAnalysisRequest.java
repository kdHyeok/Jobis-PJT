package com.jobiss.backend.dto.analysis;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;

import java.util.List;

/**
 * 자유 입력 공고로 실시간(에이전트) 분석 시작.
 * 웹백엔드는 공고를 파싱하지 않는다 — 사용자가 올린 원문(content)을 그대로 AI 에이전트에 전달만 한다.
 * 회사·직무·요구스택 구조화는 AI 에이전트가 분석 중에 수행한다(JOB_CONTEXT 신호).
 */
public record CustomAnalysisRequest(
        String sourceType,               // URL | TEXT | FILE
        @NotBlank String content,        // 공고 URL/원문/파일텍스트 (그대로 전달)
        @NotEmpty(message = "자료를 1건 이상 선택해야 합니다.") List<Long> evidenceIds,
        String parentAnalysisId,         // 대체 공고 재분석이면 원래 분석 id, 아니면 null
        String conversationId            // 이 분석이 시작된 대화. 없으면 대화를 새로 만들어 담는다.
) {
}
