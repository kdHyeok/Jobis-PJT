package com.jobiss.operator;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("/api/operator/capability-reviews")
public class OperatorCapabilityController {
    private final OperatorCapabilityService service;

    public OperatorCapabilityController(OperatorCapabilityService service) {
        this.service = service;
    }

    @GetMapping
    List<OperatorCapabilityService.CandidateView> list(@AuthenticationPrincipal UUID operatorId,
                                                       @RequestParam(defaultValue = "PENDING") String status) {
        return service.list(operatorId, status);
    }

    @PostMapping("/{candidateId}/resolve")
    ResponseEntity<Void> resolve(@AuthenticationPrincipal UUID operatorId, @PathVariable UUID candidateId,
                                 @Valid @RequestBody ResolveRequest request) {
        service.resolve(operatorId, candidateId, request.action(), request.canonicalKey(), request.reason());
        return ResponseEntity.noContent().build();
    }

    @PostMapping("/releases")
    OperatorCapabilityService.ReleaseView publish(@AuthenticationPrincipal UUID operatorId,
                                                   @Valid @RequestBody PublishRequest request) {
        return service.publish(operatorId, request.graphVersion(), request.notes());
    }

    public record ResolveRequest(
            @NotBlank @Pattern(regexp = "APPROVE_NEW|LINK_EXISTING|SPLIT|REJECT|HOLD") String action,
            @Pattern(regexp = "^[a-z0-9][a-z0-9._:-]{2,159}$") String canonicalKey,
            @NotBlank @Size(max = 4000) String reason) {}

    public record PublishRequest(
            @NotBlank @Pattern(regexp = "^\\d+\\.\\d+\\.\\d+(?:-[0-9A-Za-z.-]+)?$") String graphVersion,
            @NotBlank @Size(max = 4000) String notes) {}
}
