package com.jobiss.backend.dto.evidence;

import jakarta.validation.constraints.NotBlank;

/**
 * 커리어 저장소 자료 파싱 요청.
 * sourceType: TEXT(이력서 본문) | GITHUB(저장소 URL) | FILE(파일에서 뽑은 텍스트).
 * content: 실제 텍스트/URL. (파일은 프론트에서 텍스트로 읽어 보낸다)
 */
public record ImportParseRequest(
        @NotBlank String sourceType,
        @NotBlank String content
) {
}
