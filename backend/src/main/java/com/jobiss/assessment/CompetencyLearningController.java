package com.jobiss.assessment;

import com.jobiss.analysis.AiContracts;
import jakarta.validation.Valid;
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

@RestController
@RequestMapping("/api/career-map/nodes/{nodeId}/learning")
public class CompetencyLearningController {

    private final CompetencyLearningService service;

    public CompetencyLearningController(CompetencyLearningService service) {
        this.service = service;
    }

    @GetMapping
    ResponseEntity<AiContracts.CompetencyLearningResponse> latest(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID nodeId,
            @RequestParam(required = false) UUID targetPostingId
    ) {
        AiContracts.CompetencyLearningResponse response =
                service.latest(userId, nodeId, targetPostingId);
        return response == null
                ? ResponseEntity.noContent().build()
                : ResponseEntity.ok(response);
    }

    @PostMapping
    AiContracts.CompetencyLearningResponse generate(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID nodeId,
            @Valid @RequestBody GenerateLearningRequest request
    ) {
        return service.generate(
                userId,
                nodeId,
                request.targetPostingId(),
                request.refresh()
        );
    }

    public record GenerateLearningRequest(
            UUID targetPostingId,
            boolean refresh
    ) {
    }
}
