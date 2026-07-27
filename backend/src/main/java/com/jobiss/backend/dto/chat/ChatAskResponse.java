package com.jobiss.backend.dto.chat;

import java.util.List;

/**
 * 대화 응답.
 * conversationId — 이 턴이 속한 대화(새로 만들어졌으면 그 id). 프론트가 사이드바에 바로 반영한다.
 * title      — 대화 제목(사이드바 표시용)
 * reply      — 사용자에게 보일 답변
 * intent     — 오케스트레이터가 이해한 의도(오해했을 때 사용자가 정정할 수 있게 노출)
 * dispatched — 실제로 실행된 에이전트 이름들
 * askedFor   — 이번 턴에 에이전트가 요청한 자료(있을 때만). 프론트가 그때 입력 카드를 띄운다.
 */
public record ChatAskResponse(
        Long conversationId,
        String title,
        String reply,
        String intent,
        List<String> dispatched,
        List<AskedFor> askedFor
) {
}
