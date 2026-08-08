package com.jobiss.posting;

import com.jobiss.common.WebUrls;

import jakarta.validation.Valid;
import jakarta.validation.constraints.AssertTrue;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("/api/job-postings")
public class JobPostingController {

    private final JobPostingService service;
    private final AgentPostingUrlImportService urlImportService;

    public JobPostingController(
            JobPostingService service,
            AgentPostingUrlImportService urlImportService
    ) {
        this.service = service;
        this.urlImportService = urlImportService;
    }

    @PostMapping("/import-url")
    AgentPostingUrlImportService.ImportedPosting importUrl(
            @Valid @RequestBody ImportUrlRequest request
    ) {
        return urlImportService.importUrl(request.sourceUrl());
    }

    @PostMapping
    JobPostingService.CreatedPosting create(
            @AuthenticationPrincipal UUID userId,
            @Valid @RequestBody CreatePostingRequest request
    ) {
        return service.create(
                userId,
                new JobPostingService.CreatePosting(
                        request.sourceType(),
                        request.sourceUrl(),
                        request.rawText(),
                        request.conversationId()
                )
        );
    }

    @GetMapping
    List<JobPostingService.PostingSummary> list(@AuthenticationPrincipal UUID userId) {
        return service.list(userId);
    }

    @GetMapping("/search")
    JobPostingService.PostingPage search(
            @AuthenticationPrincipal UUID userId,
            @RequestParam(defaultValue = "") String query,
            @RequestParam(defaultValue = "") String status,
            @RequestParam(defaultValue = "createdAt") String sort,
            @RequestParam(defaultValue = "desc") String direction,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size,
            @RequestParam(defaultValue = "false") boolean archived
    ) {
        return service.search(userId, query, status, sort, direction, page, size, archived);
    }

    @GetMapping("/{postingId}")
    JobPostingService.PostingDetail get(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID postingId
    ) {
        return service.get(userId, postingId);
    }

    @PatchMapping("/{postingId}")
    JobPostingService.CreatedPosting update(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID postingId,
            @Valid @RequestBody UpdatePostingRequest request
    ) {
        return service.update(userId, postingId, request.sourceUrl(), request.rawText());
    }

    @PostMapping("/{postingId}/archive")
    ResponseEntity<Void> archive(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID postingId
    ) {
        service.archive(userId, postingId);
        return ResponseEntity.noContent().build();
    }

    @PostMapping("/{postingId}/restore")
    ResponseEntity<Void> restore(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID postingId
    ) {
        service.restore(userId, postingId);
        return ResponseEntity.noContent().build();
    }

    @DeleteMapping("/{postingId}")
    ResponseEntity<Void> delete(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID postingId
    ) {
        service.delete(userId, postingId);
        return ResponseEntity.noContent().build();
    }

    public record CreatePostingRequest(
            @NotBlank
            @Pattern(regexp = "TEXT|URL|FILE")
            String sourceType,
            @Size(max = 2000)
            String sourceUrl,
            @NotBlank
            @Size(max = 100_000)
            String rawText,
            UUID conversationId
    ) {
        @AssertTrue(message = "URL 방식에서는 sourceUrl이 필요합니다.")
        public boolean isSourceConsistent() {
            return !"URL".equals(sourceType) || (sourceUrl != null && !sourceUrl.isBlank());
        }

        @AssertTrue(message = "공고 URL은 http 또는 https 주소여야 합니다.")
        public boolean isSourceUrlSafe() {
            return WebUrls.isBlankOrHttpUrl(sourceUrl);
        }
    }

    public record ImportUrlRequest(@NotBlank @Size(max = 2_000) String sourceUrl) {
        @AssertTrue(message = "공고 URL은 http 또는 https 주소여야 합니다.")
        public boolean isSourceUrlSafe() {
            return WebUrls.isHttpUrl(sourceUrl);
        }
    }

    public record UpdatePostingRequest(
            @Size(max = 2000) String sourceUrl,
            @NotBlank @Size(max = 100_000) String rawText
    ) {
        @AssertTrue(message = "공고 URL은 http 또는 https 주소여야 합니다.")
        public boolean isSourceUrlSafe() {
            return WebUrls.isBlankOrHttpUrl(sourceUrl);
        }
    }
}
