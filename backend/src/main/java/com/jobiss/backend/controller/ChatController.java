package com.jobiss.backend.controller;

import com.jobiss.backend.dto.chat.ChatAskRequest;
import com.jobiss.backend.dto.chat.ChatAskResponse;
import com.jobiss.backend.dto.chat.ConversationMessageResponse;
import com.jobiss.backend.dto.chat.ConversationResponse;
import com.jobiss.backend.service.ConversationService;
import com.jobiss.backend.exception.ApiException;
import com.jobiss.backend.service.ChatService;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/** 일반 대화("JOBIS에게 물어보기"). 공고 판정은 /api/analyses 쪽 실시간 경로가 담당한다. */
@RestController
@RequestMapping("/api/chat")
public class ChatController {

    private final ChatService chatService;
    private final ConversationService conversationService;

    public ChatController(ChatService chatService, ConversationService conversationService) {
        this.chatService = chatService;
        this.conversationService = conversationService;
    }

    /** 사이드바 대화 목록(최근 활동 순). */
    @GetMapping("/conversations")
    public List<ConversationResponse> conversations(@AuthenticationPrincipal Long userId) {
        return conversationService.list(userId);
    }

    /** 대화 열기 — 지난 발화 복원. */
    @GetMapping("/conversations/{conversationId}")
    public List<ConversationMessageResponse> messages(@AuthenticationPrincipal Long userId,
                                                     @PathVariable Long conversationId) {
        return conversationService.messages(userId, conversationId);
    }

    @DeleteMapping("/conversations/{conversationId}")
    public Map<String, String> deleteConversation(@AuthenticationPrincipal Long userId,
                                                  @PathVariable Long conversationId) {
        conversationService.delete(userId, conversationId);
        return Map.of("status", "deleted");
    }

    @PostMapping
    public ChatAskResponse ask(@AuthenticationPrincipal Long userId,
                               @RequestBody ChatAskRequest request) {
        // 메시지 없이 자료만 보내는 턴은 허용한다 — 셋 다 비었을 때만 거부.
        if (request == null || request.isEmpty()) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "EMPTY_MESSAGE",
                    "메시지나 자료(이력서·공고) 중 하나는 있어야 해요.");
        }
        return chatService.ask(userId, request);
    }
}
