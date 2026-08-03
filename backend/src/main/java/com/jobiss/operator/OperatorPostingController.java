package com.jobiss.operator;

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
@RequestMapping("/api/operator/posting-duplicates")
public class OperatorPostingController {

    private final OperatorPostingService service;

    public OperatorPostingController(OperatorPostingService service) {
        this.service = service;
    }

    @GetMapping
    List<OperatorPostingService.DuplicateCandidateView> list(
            @AuthenticationPrincipal UUID operatorId,
            @RequestParam(defaultValue = "OPEN") String status
    ) {
        return service.list(operatorId, status);
    }

    @PostMapping("/{candidateId}/resolve")
    ResponseEntity<Void> resolve(
            @AuthenticationPrincipal UUID operatorId,
            @PathVariable UUID candidateId,
            @Valid @RequestBody ResolveRequest request
    ) {
        service.resolve(
                operatorId,
                candidateId,
                request.action(),
                request.canonicalPostingId(),
                request.reason()
        );
        return ResponseEntity.noContent().build();
    }

    @PostMapping("/audit/{auditId}/rollback")
    ResponseEntity<Void> rollback(
            @AuthenticationPrincipal UUID operatorId,
            @PathVariable UUID auditId,
            @Valid @RequestBody RollbackRequest request
    ) {
        service.rollback(operatorId, auditId, request.reason());
        return ResponseEntity.noContent().build();
    }

    public record ResolveRequest(
            @NotBlank
            @Pattern(regexp = "MERGE|SEPARATE|HOLD")
            String action,
            UUID canonicalPostingId,
            @Size(max = 2_000) String reason
    ) {
    }

    public record RollbackRequest(
            @NotBlank @Size(max = 2_000) String reason
    ) {
    }
}
