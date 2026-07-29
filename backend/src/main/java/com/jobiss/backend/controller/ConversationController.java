package com.jobiss.backend.controller;

import com.jobiss.backend.dto.conversation.ConversationDtos;
import com.jobiss.backend.service.ConversationService;
import jakarta.validation.Valid;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 대화 — 목록의 단위. 공고 없이도 시작할 수 있고, 분석은 이 안에서 일어난다.
 */
@RestController
@RequestMapping("/api/conversations")
public class ConversationController {

    private final ConversationService service;

    public ConversationController(ConversationService service) {
        this.service = service;
    }

    /** 사이드바 목록(최근 활동 순). */
    @GetMapping
    public List<ConversationDtos.Summary> list(@AuthenticationPrincipal Long userId) {
        return service.list(userId);
    }

    /** 대화 열기 — 저장된 메시지 전체. */
    @GetMapping("/{conversationId}")
    public ConversationDtos.Detail get(@AuthenticationPrincipal Long userId,
                                       @PathVariable String conversationId) {
        return service.get(userId, conversationId);
    }

    @PostMapping
    public ConversationDtos.Summary create(@AuthenticationPrincipal Long userId,
                                           @Valid @RequestBody(required = false) ConversationDtos.CreateRequest request) {
        return service.create(userId, request == null ? null : request.title());
    }

    /**
     * 대화 안에서 한마디. 경로 id 가 'new' 면 이 요청이 대화를 만든다 —
     * ChatGPT 처럼 "말을 걸어야 목록에 생긴다".
     */
    @PostMapping("/{conversationId}/messages")
    public ConversationDtos.SendResponse send(@AuthenticationPrincipal Long userId,
                                              @PathVariable String conversationId,
                                              @Valid @RequestBody ConversationDtos.SendRequest request) {
        String cid = "new".equals(conversationId) ? null : conversationId;
        return service.send(userId, cid, request.text());
    }

    @DeleteMapping("/{conversationId}")
    public void delete(@AuthenticationPrincipal Long userId, @PathVariable String conversationId) {
        service.delete(userId, conversationId);
    }
}
