package com.jobiss.backend.dto.evidence;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotEmpty;

import java.util.List;

/** 사용자가 확인·선택한 조각들을 저장소에 등록. */
public record BulkImportRequest(
        @NotEmpty @Valid List<EvidenceCreateRequest> items
) {
}
