package com.jobiss.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "jobiss.data-protection")
public record DataProtectionProperties(String encryptionKey, String fingerprintKey) {
}
