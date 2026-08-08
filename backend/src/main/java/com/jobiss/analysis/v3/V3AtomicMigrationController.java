package com.jobiss.analysis.v3;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
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
@RequestMapping("/api/v3/capability-migrations")
public class V3AtomicMigrationController {

    private final V3AtomicMigrationService service;

    public V3AtomicMigrationController(V3AtomicMigrationService service) {
        this.service = service;
    }

    @GetMapping
    List<V3AtomicMigrationService.MigrationCandidateView> candidates(
            @AuthenticationPrincipal UUID userId,
            @RequestParam(required = false) String canonicalKey
    ) {
        return service.candidates(userId, canonicalKey);
    }

    @PostMapping("/{candidateId}/resolve")
    V3AtomicMigrationService.MigrationCandidateView resolve(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID candidateId,
            @Valid @RequestBody ResolveRequest request
    ) {
        return service.resolve(userId, candidateId, "CONFIRM".equals(request.action()));
    }

    public record ResolveRequest(
            @NotBlank @Pattern(regexp = "CONFIRM|REJECT") String action
    ) {
    }
}
