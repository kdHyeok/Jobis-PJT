package com.jobiss.roadmap;

import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.UUID;

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

    @PostMapping("/draft")
    RoadmapService.DraftResult regenerate(
            @AuthenticationPrincipal UUID userId
    ) {
        return service.regenerate(userId);
    }

    @PostMapping("/draft/apply")
    RoadmapService.ApplyResult apply(
            @AuthenticationPrincipal UUID userId
    ) {
        return service.applyDraft(userId);
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
}
