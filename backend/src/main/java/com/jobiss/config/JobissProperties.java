package com.jobiss.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "jobiss")
public record JobissProperties(Auth auth, Ai ai) {

    public record Auth(
            String jwtSecret,
            long accessTokenSeconds,
            long refreshTokenSeconds,
            long rememberMeRefreshTokenSeconds,
            boolean cookieSecure,
            // 브라우저 쿠키는 포트를 구분하지 않는다 — 같은 localhost 에 다른 스택을
            // 띄우면 같은 이름의 세션 쿠키가 서로를 덮는다(08-07 실측: 다른 키로 서명된
            // 토큰이 덮여 SignatureException 즉시 로그아웃). 스택마다 다른 이름을 주면
            // 충돌 자체가 불가능하다. 리프레시 쿠키는 접미사로 짝을 맞춘다.
            String cookieName
    ) {
        public Auth {
            if (cookieName == null || cookieName.isBlank()) {
                cookieName = "jobiss_access";
            }
        }

        public String refreshCookieName() {
            return cookieName + "_refresh";
        }
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
