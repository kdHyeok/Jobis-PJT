package com.jobiss.backend.dto.evidence;

import com.jobiss.backend.domain.EvidenceKind;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

public record EvidenceCreateRequest(
        @NotNull EvidenceKind kind,
        @NotBlank String label,
        String description
) {
}
