package com.jobiss.conversation;

import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("/api/chat-reply-jobs")
public class ChatReplyJobController {

    private final ChatReplyJobService service;

    public ChatReplyJobController(ChatReplyJobService service) {
        this.service = service;
    }

    @GetMapping("/{jobId}")
    ChatReplyJobService.ChatReplyJobView get(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID jobId
    ) {
        return service.get(userId, jobId);
    }

    @GetMapping("/conversation/{conversationId}")
    List<ChatReplyJobService.ChatReplyJobView> list(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID conversationId
    ) {
        return service.list(userId, conversationId);
    }

    @PostMapping("/{jobId}/retry")
    ResponseEntity<Void> retry(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID jobId
    ) {
        service.retry(userId, jobId);
        return ResponseEntity.accepted().build();
    }
}
