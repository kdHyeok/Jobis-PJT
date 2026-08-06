package com.jobiss.analysis.v3;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import tools.jackson.databind.JsonNode;

import java.util.UUID;

@RestController
@RequestMapping("/api/v3")
public class V3AtomicAssessmentController {

    private final V3AtomicAssessmentService service;

    public V3AtomicAssessmentController(V3AtomicAssessmentService service) {
        this.service = service;
    }

    @GetMapping("/capabilities/{canonicalKey}/assessment")
    V3AtomicAssessmentService.AssessmentView latest(
            @AuthenticationPrincipal UUID userId,
            @PathVariable String canonicalKey
    ) {
        return service.latest(userId, canonicalKey);
    }

    @PostMapping("/capabilities/{canonicalKey}/assessment")
    V3AtomicAssessmentService.AssessmentView start(
            @AuthenticationPrincipal UUID userId,
            @PathVariable String canonicalKey,
            @RequestBody(required = false) V3AtomicAssessmentService.TargetContextRequest request
    ) {
        return service.start(userId, canonicalKey, request);
    }

    @PostMapping("/capabilities/{canonicalKey}/self-confirm")
    JsonNode selfConfirm(
            @AuthenticationPrincipal UUID userId,
            @PathVariable String canonicalKey
    ) {
        return service.selfConfirm(userId, canonicalKey);
    }

    @PostMapping("/assessments/{sessionId}/answers")
    V3AtomicAssessmentService.AssessmentView answer(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID sessionId,
            @Valid @RequestBody AnswerRequest request
    ) {
        return service.answer(userId, sessionId, request.answer());
    }

    @PostMapping("/assessments/{sessionId}/abandon")
    V3AtomicAssessmentService.AssessmentView abandon(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID sessionId
    ) {
        return service.abandon(userId, sessionId);
    }

    @PostMapping("/assessments/{sessionId}/review")
    V3AtomicAssessmentService.AssessmentView requestReview(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID sessionId,
            @Valid @RequestBody ReviewRequest request
    ) {
        return service.requestReview(userId, sessionId, request.reason());
    }

    public record AnswerRequest(@NotBlank String answer) {
    }

    public record ReviewRequest(@NotBlank String reason) {
    }
}
