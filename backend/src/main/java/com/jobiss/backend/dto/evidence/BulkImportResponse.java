package com.jobiss.backend.dto.evidence;

import java.util.List;

/** 등록 결과: 새로 만들어진 조각 + 중복으로 건너뛴 개수. */
public record BulkImportResponse(
        List<EvidenceResponse> created,
        int skipped
) {
}
