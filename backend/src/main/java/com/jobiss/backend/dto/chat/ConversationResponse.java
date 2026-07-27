package com.jobiss.backend.dto.chat;

import com.jobiss.backend.domain.Conversation;

import java.time.LocalDateTime;

/** 사이드바 대화 목록의 한 줄. */
public record ConversationResponse(
        Long id,
        String title,
        LocalDateTime updatedAt
) {
    public static ConversationResponse from(Conversation c) {
        return new ConversationResponse(c.getId(), c.getTitle(), c.getUpdatedAt());
    }
}
