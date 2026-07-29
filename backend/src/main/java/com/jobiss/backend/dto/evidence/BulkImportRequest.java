package com.jobiss.backend.dto.evidence;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotEmpty;

import java.util.List;

/**
 * 사용자가 확인·선택한 조각들을 저장소에 등록.
 * resumeDocumentId: 이 조각들이 나온 이력서 원문 id(V6). 원문을 보관하지 않았으면 null.
 */
public record BulkImportRequest(
        @NotEmpty @Valid List<EvidenceCreateRequest> items,
        Long resumeDocumentId
) {
}
