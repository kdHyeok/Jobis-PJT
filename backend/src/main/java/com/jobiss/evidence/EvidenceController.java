package com.jobiss.evidence;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import tools.jackson.databind.JsonNode;

import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("/api")
public class EvidenceController {

    private final EvidenceService service;

    public EvidenceController(EvidenceService service) {
        this.service = service;
    }

    @PostMapping("/career-map/nodes/{nodeId}/evidence")
    EvidenceService.EvidenceView submit(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID nodeId,
            @Valid @RequestBody SubmitEvidenceRequest request
    ) {
        return service.submit(
                userId,
                nodeId,
                new EvidenceService.SubmitEvidence(
                        request.evidenceType(),
                        request.title(),
                        request.sourceUrl(),
                        request.content()
                )
        );
    }

    @GetMapping("/career-map/nodes/{nodeId}/evidence")
    List<EvidenceService.EvidenceView> list(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID nodeId
    ) {
        return service.list(userId, nodeId);
    }

    @GetMapping("/evidence/{evidenceId}")
    EvidenceService.EvidenceView get(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID evidenceId
    ) {
        return service.get(userId, evidenceId);
    }

    @PostMapping("/evidence/{evidenceId}/retry")
    ResponseEntity<Void> retry(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID evidenceId
    ) {
        service.retry(userId, evidenceId);
        return ResponseEntity.accepted().build();
    }

    public record SubmitEvidenceRequest(
            @NotBlank
            @Pattern(regexp = "PROJECT|CODE|CERTIFICATE|EXPERIENCE|DOCUMENT")
            String evidenceType,
            @NotBlank @Size(max = 180) String title,
            @Size(max = 2_000) String sourceUrl,
            @NotNull JsonNode content
    ) {
    }
}
