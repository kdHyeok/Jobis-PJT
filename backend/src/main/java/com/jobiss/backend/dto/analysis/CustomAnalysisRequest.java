package com.jobiss.backend.dto.analysis;

import jakarta.validation.constraints.NotBlank;

import java.util.List;

/**
 * 자유 입력 공고로 실시간(에이전트) 분석 시작.
 * 웹백엔드는 공고를 파싱하지 않는다 — 사용자가 올린 원문(content)을 그대로 AI 에이전트에 전달만 한다.
 * 회사·직무·요구스택 구조화는 AI 에이전트가 분석 중에 수행한다(JOB_CONTEXT 신호).
 *
 * evidenceIds 는 비어 있어도 된다. 저장소가 빈 신규 사용자를 막지 않기 위해서다 —
 * 자료가 없으면 에이전트가 대화 중에 이력서를 요청한다(REQUEST_RESUME).
 */
public record CustomAnalysisRequest(
        String sourceType,               // URL | TEXT | FILE
        @NotBlank String content,        // 공고 URL/원문/파일텍스트 (그대로 전달)
        List<Long> evidenceIds,          // 비어 있으면 대화에서 이력서를 요청한다
        String parentAnalysisId          // 대체 공고 재분석이면 원래 분석 id, 아니면 null
) {
}
