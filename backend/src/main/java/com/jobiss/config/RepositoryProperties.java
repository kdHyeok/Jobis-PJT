package com.jobiss.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "jobiss.repositories")
public record RepositoryProperties(
        String tokenEncryptionKey,
        GitHub github,
        GitLab gitlab
) {
    public record GitHub(
            String apiBaseUrl,
            String appId,
            String appSlug,
            String privateKey,
            String redirectUri
    ) {
    }

    public record GitLab(
            String baseUrl,
            String clientId,
            String clientSecret,
            String redirectUri
    ) {
    }
}
