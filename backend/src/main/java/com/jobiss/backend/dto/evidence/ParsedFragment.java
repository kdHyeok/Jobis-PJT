package com.jobiss.backend.dto.evidence;

import com.jobiss.backend.domain.EvidenceKind;

/**
 * (가짜)AI가 올린 자료에서 뽑아낸 "조각" 후보 한 개.
 * duplicate=true 면 이미 저장소에 같은 게 있어 등록해도 새로 안 생기는 항목(주로 STACK).
 */
public record ParsedFragment(
        EvidenceKind kind,
        String label,
        String description,
        boolean duplicate
) {
}
