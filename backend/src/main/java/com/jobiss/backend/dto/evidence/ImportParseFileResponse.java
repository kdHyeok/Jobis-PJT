package com.jobiss.backend.dto.evidence;

import java.util.List;

/**
 * 이력서 파일 파싱 결과.
 * text  — 추출한 이력서 원문. 대화 중 분석에 판정 근거로 바로 넘긴다.
 * fragments — 커리어 저장소에 등록할 조각 후보(사용자 확인 후 /import).
 */
public record ImportParseFileResponse(
        String text,
        List<ParsedFragment> fragments
) {
}
