package com.jobiss.assessment;

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
import org.springframework.web.bind.annotation.RestController;

import java.util.UUID;

@RestController
@RequestMapping("/api")
public class CompetencyAssessmentController {

    private final CompetencyAssessmentService service;

    public CompetencyAssessmentController(CompetencyAssessmentService service) {
        this.service = service;
    }

    @GetMapping("/career-map/nodes/{nodeId}/assessment")
    ResponseEntity<CompetencyAssessmentService.AssessmentView> latest(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID nodeId
    ) {
        CompetencyAssessmentService.AssessmentView result =
                service.latest(userId, nodeId);
        return result == null
                ? ResponseEntity.noContent().build()
                : ResponseEntity.ok(result);
    }

    @PostMapping("/career-map/nodes/{nodeId}/assessment")
    CompetencyAssessmentService.AssessmentView start(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID nodeId,
            @Valid @RequestBody StartAssessmentRequest request
    ) {
        return service.start(userId, nodeId, request.targetPostingId());
    }

    @PostMapping("/competency-assessments/{sessionId}/answers")
    CompetencyAssessmentService.AssessmentView answer(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID sessionId,
            @Valid @RequestBody AnswerAssessmentRequest request
    ) {
        return service.answer(userId, sessionId, request.answer());
    }

    @PostMapping("/competency-assessments/{sessionId}/review")
    CompetencyAssessmentService.AssessmentView requestReview(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID sessionId,
            @Valid @RequestBody ReviewRequest request
    ) {
        return service.requestReview(userId, sessionId, request.reason());
    }

    public record StartAssessmentRequest(UUID targetPostingId) {
    }

    public record AnswerAssessmentRequest(
            @NotBlank @Size(max = 12_000) String answer
    ) {
    }

    public record ReviewRequest(
            @NotBlank @Size(max = 4_000) String reason
    ) {
    }
}
