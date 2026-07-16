package com.jobiss.backend.dto.common;

/**
 * 공통 에러 응답 형식: { "error": { "code": "...", "message": "..." } }
 * (연동 계약 §D 에러 규약과 동일)
 */
public record ErrorResponse(ErrorDetail error) {

    public record ErrorDetail(String code, String message) {
    }

    public static ErrorResponse of(String code, String message) {
        return new ErrorResponse(new ErrorDetail(code, message));
    }
}
