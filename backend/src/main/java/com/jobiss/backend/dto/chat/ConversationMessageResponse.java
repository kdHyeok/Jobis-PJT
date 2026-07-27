package com.jobiss.backend.dto.chat;

import com.jobiss.backend.domain.ConversationMessage;

import java.time.LocalDateTime;
import java.util.List;

/** 대화 열었을 때 복원할 발화 한 줄. */
public record ConversationMessageResponse(
        String role,
        String content,
        List<String> agents,
        LocalDateTime createdAt
) {
    public static ConversationMessageResponse from(ConversationMessage m) {
        List<String> agents = (m.getAgents() == null || m.getAgents().isBlank())
                ? List.of() : List.of(m.getAgents().split(","));
        return new ConversationMessageResponse(m.getRole().name(), m.getContent(), agents, m.getCreatedAt());
    }
}
