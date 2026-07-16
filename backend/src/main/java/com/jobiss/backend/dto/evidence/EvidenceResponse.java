package com.jobiss.backend.dto.evidence;

import com.jobiss.backend.domain.Evidence;
import com.jobiss.backend.domain.EvidenceKind;
import com.jobiss.backend.domain.EvidenceStatus;

public record EvidenceResponse(
        Long id,
        EvidenceKind kind,
        String label,
        String description,
        EvidenceStatus status
) {
    public static EvidenceResponse from(Evidence e) {
        return new EvidenceResponse(e.getId(), e.getKind(), e.getLabel(), e.getDescription(), e.getStatus());
    }
}
