package com.jobiss.analysis;

import org.springframework.web.client.RestClientException;

public class AiServiceException extends RestClientException {

    private final String code;

    public AiServiceException(String code, String message) {
        super(message);
        this.code = code;
    }

    public AiServiceException(String code, String message, Throwable cause) {
        super(message, cause);
        this.code = code;
    }

    public String code() {
        return code;
    }
}
