package com.jobiss.backend.dto.evidence;

import java.util.List;

/** 파싱 결과: 조각 후보 목록. 사용자가 확인·수정 후 골라서 등록한다. */
public record ImportParseResponse(
        List<ParsedFragment> fragments
) {
}
