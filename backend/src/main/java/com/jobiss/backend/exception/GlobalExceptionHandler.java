package com.jobiss.backend.exception;

import com.jobiss.backend.dto.common.ErrorResponse;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.servlet.resource.NoResourceFoundException;

/**
 * 모든 컨트롤러의 예외를 잡아 { error: { code, message } } 형식으로 통일.
 */
@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(ApiException.class)
    public ResponseEntity<ErrorResponse> handleApiException(ApiException e) {
        return ResponseEntity.status(e.getStatus())
                .body(ErrorResponse.of(e.getCode(), e.getMessage()));
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ErrorResponse> handleValidation(MethodArgumentNotValidException e) {
        String message = e.getBindingResult().getFieldErrors().stream()
                .findFirst()
                .map(fe -> fe.getField() + ": " + fe.getDefaultMessage())
                .orElse("요청 값이 올바르지 않습니다.");
        return ResponseEntity.badRequest().body(ErrorResponse.of("VALIDATION_ERROR", message));
    }

    /**
     * 정적 리소스 없음(없는 .html/.css/favicon 등). 스프링 6.1+ 는 이때 NoResourceFoundException 을 던지는데,
     * 아래 catch-all 이 이를 삼키면 404 여야 할 응답이 500 이 되고 오류 페이지도 못 뜬다.
     * 같은 예외 인스턴스를 그대로 되던져 "이건 내가 처리 안 함"을 알린다
     * (ExceptionHandlerExceptionResolver 는 원본과 동일한 예외면 경고 없이 기본 처리로 넘긴다).
     * → 브라우저(Accept: text/html)에는 error/404.html, API 클라이언트에는 JSON 404 가 나간다.
     */
    @ExceptionHandler(NoResourceFoundException.class)
    public void handleNoResource(NoResourceFoundException e) throws NoResourceFoundException {
        throw e;
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ErrorResponse> handleUnexpected(Exception e) {
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(ErrorResponse.of("INTERNAL_ERROR", "서버 내부 오류가 발생했습니다."));
    }
}
