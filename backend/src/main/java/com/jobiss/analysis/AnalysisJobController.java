package com.jobiss.analysis;

import com.jobiss.roadmap.RoadmapService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.UUID;
import java.util.List;

@RestController
@RequestMapping("/api/analysis-jobs")
public class AnalysisJobController {

    private final AnalysisJobService service;
    private final GraphMergeService graphMergeService;
    private final RoadmapService roadmapService;

    public AnalysisJobController(
            AnalysisJobService service,
            GraphMergeService graphMergeService,
            RoadmapService roadmapService
    ) {
        this.service = service;
        this.graphMergeService = graphMergeService;
        this.roadmapService = roadmapService;
    }

    @GetMapping
    List<AnalysisJobService.AnalysisJobView> list(
            @AuthenticationPrincipal UUID userId,
            @RequestParam(defaultValue = "") String status,
            @RequestParam(defaultValue = "30") int limit
    ) {
        return service.list(userId, status, limit);
    }

    @GetMapping("/{jobId}")
    AnalysisJobService.AnalysisJobView get(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID jobId
    ) {
        return service.get(userId, jobId);
    }

    @PostMapping("/{jobId}/retry")
    ResponseEntity<Void> retry(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID jobId
    ) {
        service.retry(userId, jobId);
        return ResponseEntity.accepted().build();
    }

    @PostMapping("/{jobId}/cancel")
    ResponseEntity<Void> cancel(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID jobId
    ) {
        service.cancel(userId, jobId);
        return ResponseEntity.noContent().build();
    }

    @PostMapping("/{jobId}/questions/{questionId}/answer")
    ResponseEntity<Void> answerQuestion(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID jobId,
            @PathVariable UUID questionId,
            @Valid @RequestBody AnswerQuestionRequest request
    ) {
        service.answerQuestion(
                userId,
                jobId,
                questionId,
                request.value(),
                request.answerStatus()
        );
        return ResponseEntity.accepted().build();
    }

    @PostMapping("/{jobId}/approve")
    RoadmapService.DraftResult approve(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID jobId
    ) {
        return roadmapService.addTarget(userId, jobId);
    }

    @PostMapping("/{jobId}/reject")
    ResponseEntity<Void> reject(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID jobId
    ) {
        graphMergeService.reject(userId, jobId);
        return ResponseEntity.noContent().build();
    }

    record AnswerQuestionRequest(
            @NotBlank @Size(max = 2000) String value,
            String answerStatus
    ) {
    }
}
