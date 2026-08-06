package com.jobiss.conversation;

import com.jobiss.common.WebUrls;

import jakarta.validation.Valid;
import jakarta.validation.constraints.AssertTrue;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.RequestParam;

import java.time.OffsetDateTime;
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

    @GetMapping("/search")
    ConversationService.ConversationPage search(
            @AuthenticationPrincipal UUID userId,
            @RequestParam(defaultValue = "") String query,
            @RequestParam(defaultValue = "ACTIVE") String status,
            @RequestParam(defaultValue = "0") @Min(0) int page,
            @RequestParam(defaultValue = "30") @Min(1) @Max(100) int size
    ) {
        return service.search(userId, query, status, page, size);
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

    @GetMapping("/{conversationId}/messages")
    ConversationService.MessagePage messages(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID conversationId,
            @RequestParam OffsetDateTime beforeCreatedAt,
            @RequestParam UUID beforeId,
            @RequestParam(defaultValue = "100") @Min(1) @Max(200) int limit
    ) {
        return service.messagesBefore(
                userId,
                conversationId,
                beforeCreatedAt,
                beforeId,
                limit
        );
    }

    @PatchMapping("/{conversationId}")
    ConversationService.ConversationSummary rename(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID conversationId,
            @Valid @RequestBody RenameConversationRequest request
    ) {
        return service.rename(userId, conversationId, request.title());
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
                        posting,
                        request.context() == null
                                ? ConversationService.AgentContext.automatic()
                                : new ConversationService.AgentContext(
                                        request.context().mode(),
                                        request.context().postingIds() == null
                                                ? List.of()
                                                : request.context().postingIds(),
                                        request.context().careerSourceIds() == null
                                                ? List.of()
                                                : request.context().careerSourceIds()
                                )
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

    @PostMapping("/{conversationId}/restore")
    ResponseEntity<Void> restore(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID conversationId
    ) {
        service.restore(userId, conversationId);
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
            @Valid PostingAttachmentRequest posting,
            @Valid AgentContextRequest context
    ) {
    }

    public record RenameConversationRequest(
            @NotBlank @Size(max = 120) String title
    ) {
    }

    public record AgentContextRequest(
            @NotBlank @Pattern(regexp = "AUTO|CAREER_CHAT|POSTING_QA|RESUME_DIAGNOSIS|POSTING_COMPARE|RESUME_COMPARE|INTERVIEW_PREP|COVER_LETTER|APPLICATION_PLAN|JOB_DISCOVERY")
            String mode,
            @Size(max = 5) List<UUID> postingIds,
            @Size(max = 5) List<UUID> careerSourceIds
    ) {
    }

    public record PostingAttachmentRequest(
            @NotBlank @Pattern(regexp = "TEXT|URL") String sourceType,
            @Size(max = 2_000) String sourceUrl,
            @NotBlank @Size(max = 100_000) String rawText
    ) {
        @AssertTrue(message = "URL 방식에서는 http 또는 https 공고 주소가 필요합니다.")
        public boolean isSourceUrlSafe() {
            return !"URL".equals(sourceType) || WebUrls.isHttpUrl(sourceUrl);
        }
    }
}
