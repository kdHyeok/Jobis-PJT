package com.jobiss.analysis.v3;

import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import tools.jackson.databind.node.ArrayNode;

import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("/api/v3/sources")
public class V3SourceController {

    private final V3SourceService service;

    public V3SourceController(V3SourceService service) {
        this.service = service;
    }

    @PostMapping
    V3SourceService.SourceView acquire(
            @AuthenticationPrincipal UUID userId,
            @Valid @RequestBody AcquireRequest request
    ) {
        return service.acquire(userId, new V3SourceService.AcquireCommand(
                request.inputType(),
                request.entryPoint(),
                request.extractionRevision(),
                request.postingId(),
                request.text(),
                request.url(),
                request.imageBase64(),
                request.imageMediaType(),
                request.originalFilename()
        ));
    }

    @PostMapping("/{sourceId}/verify")
    V3SourceService.SourceView verify(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID sourceId,
            @Valid @RequestBody VerifyRequest request
    ) {
        return service.verify(userId, sourceId, new V3SourceService.VerifyCommand(
                request.verifiedText(),
                request.corrections(),
                request.verifiedBy(),
                request.previousSnapshotId()
        ));
    }

    @GetMapping("/{sourceId}")
    V3SourceService.SourceView get(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID sourceId
    ) {
        return service.get(userId, sourceId);
    }

    @PostMapping("/{sourceId}/analyses")
    V3SourceService.AnalysisStart startAnalysis(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID sourceId,
            @RequestBody(required = false) StartAnalysisRequest request
    ) {
        return service.startAnalysis(
                userId,
                sourceId,
                request == null ? null : request.conversationId()
        );
    }

    @GetMapping
    List<V3SourceService.SourceSummary> list(
            @AuthenticationPrincipal UUID userId
    ) {
        return service.list(userId);
    }

    public record AcquireRequest(
            @NotBlank String inputType,
            @NotBlank String entryPoint,
            @Min(1) @Max(1000) int extractionRevision,
            UUID postingId,
            @Size(max = 200_000) String text,
            @Size(max = 2_000) String url,
            @Size(max = 20_000_000) String imageBase64,
            @Size(max = 80) String imageMediaType,
            @Size(max = 255) String originalFilename
    ) {
    }

    public record VerifyRequest(
            @NotBlank @Size(max = 200_000) String verifiedText,
            ArrayNode corrections,
            @NotBlank String verifiedBy,
            @Size(max = 160) String previousSnapshotId
    ) {
    }

    public record StartAnalysisRequest(UUID conversationId) {
    }
}
