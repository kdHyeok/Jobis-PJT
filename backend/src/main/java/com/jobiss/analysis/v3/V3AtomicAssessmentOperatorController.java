package com.jobiss.analysis.v3;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
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

import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("/api/operator/atomic-assessment-reviews")
public class V3AtomicAssessmentOperatorController {

    private final V3AtomicAssessmentService service;

    public V3AtomicAssessmentOperatorController(V3AtomicAssessmentService service) {
        this.service = service;
    }

    @GetMapping
    List<V3AtomicAssessmentService.AssessmentReviewView> list(
            @AuthenticationPrincipal UUID operatorId,
            @RequestParam(defaultValue = "PENDING") String status
    ) {
        return service.operatorReviews(operatorId, status);
    }

    @GetMapping("/{sessionId}")
    V3AtomicAssessmentService.AssessmentView detail(
            @AuthenticationPrincipal UUID operatorId,
            @PathVariable UUID sessionId
    ) {
        return service.operatorReview(operatorId, sessionId);
    }

    @PostMapping("/{sessionId}/resolve")
    ResponseEntity<Void> resolve(
            @AuthenticationPrincipal UUID operatorId,
            @PathVariable UUID sessionId,
            @Valid @RequestBody ResolveRequest request
    ) {
        service.resolveReview(
                operatorId,
                sessionId,
                "APPROVE".equals(request.action()),
                request.comment()
        );
        return ResponseEntity.noContent().build();
    }

    public record ResolveRequest(
            @NotBlank @Pattern(regexp = "APPROVE|REJECT") String action,
            @Size(max = 4_000) String comment
    ) {
    }
}
