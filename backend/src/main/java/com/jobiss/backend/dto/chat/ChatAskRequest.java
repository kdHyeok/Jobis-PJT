package com.jobiss.backend.dto.chat;

/**
 * "JOBIS에게 물어보기" 한 턴.
 *
 * conversationId 가 없으면 새 대화를 만든다 — 그래서 첫 발화만으로 사이드바에 대화가 생긴다.
 * 매 턴에 이력서·공고를 함께 실을 수 있다(프로토타입과 같은 구조). 무엇을 할지는 오케스트레이터가 정한다.
 */
public record ChatAskRequest(
        Long conversationId,    // 없으면 새 대화 생성
        String message,
        String resumeText,      // 이력서 원문(선택). 파일은 /api/evidences/parse-file 로 텍스트를 얻어 넣는다
        String postingText,     // 공고 원문 또는 URL(선택)
        String resumeExtraText  // 기존 이력서에 덧붙일 추가 정보(빈 섹션 보완 입력 등, 선택)
) {
    public boolean isEmpty() {
        return blank(message) && blank(resumeText) && blank(postingText) && blank(resumeExtraText);
    }

    private static boolean blank(String s) {
        return s == null || s.isBlank();
    }
}
