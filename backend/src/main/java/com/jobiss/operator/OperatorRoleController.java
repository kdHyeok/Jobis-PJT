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
@RequestMapping("/api/operator/role-reviews")
public class OperatorRoleController {

    private final OperatorRoleService service;

    public OperatorRoleController(OperatorRoleService service) {
        this.service = service;
    }

    @GetMapping
    List<OperatorRoleService.RoleCandidateView> list(
            @AuthenticationPrincipal UUID operatorId,
            @RequestParam(defaultValue = "PENDING") String status
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
                request.canonicalRoleId(),
                request.reason()
        );
        return ResponseEntity.noContent().build();
    }

    @PostMapping("/releases")
    OperatorRoleService.RoleReleaseView publish(
            @AuthenticationPrincipal UUID operatorId,
            @Valid @RequestBody PublishRequest request
    ) {
        return service.publish(operatorId, request.notes());
    }

    record ResolveRequest(
            @NotBlank @Pattern(regexp = "APPROVE_NEW|LINK_EXISTING|REJECT|HOLD") String action,
            @Pattern(regexp = "^[a-z0-9][a-z0-9._:-]{2,159}$") String canonicalRoleId,
            @NotBlank @Size(max = 4000) String reason
    ) {
    }

    record PublishRequest(@NotBlank @Size(max = 4000) String notes) {}
}
