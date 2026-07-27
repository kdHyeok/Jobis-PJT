package com.jobiss.backend.dto.evidence;

import jakarta.validation.constraints.NotBlank;

/**
 * 이력서 파일 파싱 요청.
 * 브라우저가 읽을 수 없는 형식(pdf·docx)을 위해 파일 바이트를 base64 로 실어 보낸다.
 * 텍스트 파일이면 프론트가 직접 읽어 {@link ImportParseRequest} 로 보내도 된다.
 */
public record ImportParseFileRequest(
        @NotBlank String filename,
        @NotBlank String contentBase64
) {
}
