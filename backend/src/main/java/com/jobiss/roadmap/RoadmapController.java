package com.jobiss.roadmap;

import jakarta.validation.Valid;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.UUID;
import java.util.List;

@RestController
@RequestMapping("/api/roadmap")
public class RoadmapController {

    private final RoadmapService service;

    public RoadmapController(RoadmapService service) {
        this.service = service;
    }

    @GetMapping
    RoadmapService.Workspace get(@AuthenticationPrincipal UUID userId) {
        return service.get(userId);
    }

    @GetMapping("/versions")
    List<RoadmapService.VersionSummary> versions(@AuthenticationPrincipal UUID userId) {
        return service.versions(userId);
    }

    @PostMapping("/versions/{versionId}/restore")
    RoadmapService.DraftResult restoreVersion(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID versionId
    ) {
        return service.restoreVersion(userId, versionId);
    }

    @PostMapping("/draft")
    RoadmapService.DraftResult regenerate(
            @AuthenticationPrincipal UUID userId
    ) {
        return service.regenerate(userId);
    }

    @PostMapping("/draft/apply")
    RoadmapService.ApplyResult apply(
            @AuthenticationPrincipal UUID userId,
            @Valid @RequestBody ApplyDraftRequest request
    ) {
        return service.applyDraft(userId, request.draftId(), request.expectedVersion());
    }

    @PostMapping("/draft/discard")
    RoadmapService.DraftDiscardResult discard(
            @AuthenticationPrincipal UUID userId,
            @Valid @RequestBody ApplyDraftRequest request
    ) {
        return service.discardDraft(userId, request.draftId(), request.expectedVersion());
    }

    @DeleteMapping("/targets/{postingId}")
    RoadmapService.DraftResult removeTarget(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID postingId
    ) {
        return service.removeTarget(userId, postingId);
    }

    @PostMapping("/reset")
    RoadmapService.DraftResult reset(
            @AuthenticationPrincipal UUID userId
    ) {
        return service.resetTargets(userId);
    }

    public record ApplyDraftRequest(
            @NotNull UUID draftId,
            @Min(1) long expectedVersion
    ) {
    }
}
