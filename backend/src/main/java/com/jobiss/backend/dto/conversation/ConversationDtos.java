package com.jobiss.backend.dto.conversation;

import com.jobiss.backend.domain.Conversation;
import com.jobiss.backend.domain.ConversationMessage;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

import java.time.LocalDateTime;
import java.util.List;

/** 대화 API 의 요청·응답 묶음. */
public final class ConversationDtos {

    private ConversationDtos() {
    }

    /** 사이드바 한 줄. analysisId 가 있으면 이 대화 안에서 분석이 돌았다는 뜻. */
    public record Summary(
            String conversationId,
            String title,
            LocalDateTime updatedAt,
            String analysisId,      // 대화 안 마지막 분석(없으면 null)
            String analysisStatus   // 그 분석의 상태(없으면 null)
    ) {
    }

    public record Message(
            int seq,
            String role,            // USER | ASSISTANT | ANALYSIS
            String content,
            String analysisId
    ) {
        public static Message from(ConversationMessage m) {
            return new Message(m.getSeq(), m.getRole().name(), m.getContent(), m.getAnalysisId());
        }
    }

    public record Detail(
            String conversationId,
            String title,
            LocalDateTime updatedAt,
            List<Message> messages
    ) {
        public static Detail of(Conversation c, List<ConversationMessage> messages) {
            return new Detail(c.getConversationId(), c.getTitle(), c.getUpdatedAt(),
                    messages.stream().map(Message::from).toList());
        }
    }

    /** 새 대화 만들기. 제목은 생략 가능(첫 발화로 채워진다). */
    public record CreateRequest(@Size(max = 200) String title) {
    }

    /** 대화에 한마디 보내기 → 저장 + AI 응답 + 저장. */
    public record SendRequest(@NotBlank @Size(max = 20000) String text) {
    }

    /** 보낸 결과. reply 는 AI 답변, action 은 다음 단계 제안. */
    public record SendResponse(
            String conversationId,
            String title,
            String reply,
            String action,
            String actionLabel
    ) {
    }
}
