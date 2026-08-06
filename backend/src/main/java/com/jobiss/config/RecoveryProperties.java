package com.jobiss.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "jobiss.recovery")
public record RecoveryProperties(
        String publicBaseUrl,
        int tokenMinutes,
        String mailFrom,
        boolean consoleDelivery
) {
}
