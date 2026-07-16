package com.jobiss.backend.exception;

import org.springframework.http.HttpStatus;

/**
 * 애플리케이션 레벨 예외. 상태코드 + 에러코드 + 메시지를 담아
 * GlobalExceptionHandler 가 일관된 형식으로 응답한다.
 */
public class ApiException extends RuntimeException {

    private final HttpStatus status;
    private final String code;

    public ApiException(HttpStatus status, String code, String message) {
        super(message);
        this.status = status;
        this.code = code;
    }

    public HttpStatus getStatus() {
        return status;
    }

    public String getCode() {
        return code;
    }
}
