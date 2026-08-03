package com.jobiss.posting;

import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("/api/job-postings")
public class PostingRecommendationController {

    private final PostingRecommendationService service;

    public PostingRecommendationController(PostingRecommendationService service) {
        this.service = service;
    }

    @GetMapping("/{postingId}/alternatives")
    List<PostingRecommendationService.AlternativePosting> alternatives(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID postingId,
            @RequestParam(defaultValue = "5") int limit
    ) {
        return service.recommend(userId, postingId, limit);
    }
}
