package com.jobiss.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "jobiss")
public record JobissProperties(Auth auth, Ai ai) {

    public record Auth(
            String jwtSecret,
            long accessTokenSeconds,
            long refreshTokenSeconds,
            long rememberMeRefreshTokenSeconds,
            boolean cookieSecure
    ) {
    }

    public record Ai(
            String baseUrl,
            String sharedSecret,
            boolean workerEnabled,
            long pollDelayMs,
            long requestTimeoutSeconds,
            int maxConcurrentAnalyses
    ) {
    }
}
