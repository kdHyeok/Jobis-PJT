package com.jobiss.conversation;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("/api/conversations")
public class ConversationController {

    private final ConversationService service;

    public ConversationController(ConversationService service) {
        this.service = service;
    }

    @GetMapping
    List<ConversationService.ConversationSummary> list(
            @AuthenticationPrincipal UUID userId
    ) {
        return service.list(userId);
    }

    @PostMapping
    ConversationService.ConversationView create(
            @AuthenticationPrincipal UUID userId
    ) {
        return service.create(userId);
    }

    @GetMapping("/{conversationId}")
    ConversationService.ConversationView get(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID conversationId
    ) {
        return service.get(userId, conversationId);
    }

    @PostMapping("/{conversationId}/messages")
    ConversationService.SendResult send(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID conversationId,
            @Valid @RequestBody SendMessageRequest request
    ) {
        ConversationService.PostingAttachment posting = request.posting() == null
                ? null
                : new ConversationService.PostingAttachment(
                        request.posting().sourceType(),
                        request.posting().sourceUrl(),
                        request.posting().rawText()
                );
        return service.send(
                userId,
                conversationId,
                new ConversationService.SendCommand(
                        request.clientMessageId(),
                        request.content(),
                        posting
                )
        );
    }

    @PostMapping("/{conversationId}/archive")
    ResponseEntity<Void> archive(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID conversationId
    ) {
        service.archive(userId, conversationId);
        return ResponseEntity.noContent().build();
    }

    @DeleteMapping("/{conversationId}")
    ResponseEntity<Void> delete(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID conversationId
    ) {
        service.delete(userId, conversationId);
        return ResponseEntity.noContent().build();
    }

    public record SendMessageRequest(
            UUID clientMessageId,
            @NotBlank @Size(max = 20_000) String content,
            @Valid PostingAttachmentRequest posting
    ) {
    }

    public record PostingAttachmentRequest(
            @NotBlank @Pattern(regexp = "TEXT|URL") String sourceType,
            @Size(max = 2_000) String sourceUrl,
            @NotBlank @Size(max = 100_000) String rawText
    ) {
    }
}
