package com.jobiss.analysis.v3;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDate;
import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("/api/v3/employment")
public class V3EmploymentController {
    private final V3EmploymentService service;
    public V3EmploymentController(V3EmploymentService service) { this.service = service; }

    @GetMapping
    List<V3EmploymentService.EmploymentView> list(@AuthenticationPrincipal UUID userId) {
        return service.list(userId);
    }

    @PostMapping
    V3EmploymentService.EmploymentView submit(
            @AuthenticationPrincipal UUID userId,
            @Valid @RequestBody SubmitRequest request
    ) {
        return service.submit(userId, new V3EmploymentService.Submit(
                request.canonicalRoleId(), request.roleFamily(), request.roleSpecialization(),
                request.employer(), request.roleTitle(), request.startedOn(), request.endedOn(),
                request.evidenceUrl(), request.description()
        ));
    }

    record SubmitRequest(
            @Size(max = 160) String canonicalRoleId,
            @NotBlank @Size(max = 120) String roleFamily,
            @NotBlank @Size(max = 160) String roleSpecialization,
            @NotBlank @Size(max = 200) String employer,
            @NotBlank @Size(max = 200) String roleTitle,
            @NotNull LocalDate startedOn,
            LocalDate endedOn,
            @NotBlank @Size(max = 2000) String evidenceUrl,
            @NotBlank @Size(max = 4000) String description
    ) {}
}
