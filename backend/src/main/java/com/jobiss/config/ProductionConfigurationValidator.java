package com.jobiss.config;

import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;

import java.util.Arrays;

@Component
public class ProductionConfigurationValidator implements ApplicationRunner {

    private final Environment environment;
    private final JobissProperties properties;
    private final RepositoryProperties repositoryProperties;
    private final RecoveryProperties recoveryProperties;

    public ProductionConfigurationValidator(
            Environment environment,
            JobissProperties properties,
            RepositoryProperties repositoryProperties,
            RecoveryProperties recoveryProperties
    ) {
        this.environment = environment;
        this.properties = properties;
        this.repositoryProperties = repositoryProperties;
        this.recoveryProperties = recoveryProperties;
    }

    @Override
    public void run(ApplicationArguments args) {
        boolean production = Arrays.asList(environment.getActiveProfiles()).contains("prod");
        if (!production) {
            return;
        }
        String jwtSecret = properties.auth().jwtSecret();
        String aiSecret = properties.ai().sharedSecret();
        if (jwtSecret == null
                || jwtSecret.length() < 32
                || jwtSecret.contains("local-development")
                || aiSecret == null
                || aiSecret.length() < 24
                || aiSecret.startsWith("local-")
                || properties.auth().accessTokenSeconds() < 300
                || properties.auth().accessTokenSeconds() > 7200
                || properties.auth().refreshTokenSeconds() < 86400
                || properties.auth().refreshTokenSeconds() > 1209600
                || properties.auth().rememberMeRefreshTokenSeconds()
                    < properties.auth().refreshTokenSeconds()
                || properties.auth().rememberMeRefreshTokenSeconds() > 2592000
                || !properties.auth().cookieSecure()) {
            throw new IllegalStateException(
                    "Production requires unique JWT/AI secrets and secure cookies"
            );
        }
        String datasourcePassword = environment.getProperty("spring.datasource.password", "");
        String migratorPassword = environment.getProperty("spring.flyway.password", "");
        if (datasourcePassword.isBlank()
                || migratorPassword.isBlank()
                || datasourcePassword.contains("_dev")
                || migratorPassword.contains("_dev")
                || datasourcePassword.equals(migratorPassword)) {
            throw new IllegalStateException(
                    "Production requires distinct non-development database application and migration credentials"
            );
        }
        String repositoryEncryptionKey = repositoryProperties.tokenEncryptionKey();
        String sensitiveEncryptionKey = environment.getProperty(
                "jobiss.data-protection.encryption-key", ""
        );
        String sensitiveFingerprintKey = environment.getProperty(
                "jobiss.data-protection.fingerprint-key", ""
        );
        if (repositoryEncryptionKey == null
                || repositoryEncryptionKey.isBlank()
                || repositoryEncryptionKey.contains("local-repository-token-key")
                || repositoryEncryptionKey.length() < 32) {
            throw new IllegalStateException(
                    "Production requires a unique repository token encryption key of at least 32 characters"
            );
        }
        if (sensitiveEncryptionKey.length() < 32
                || sensitiveFingerprintKey.length() < 32
                || sensitiveEncryptionKey.contains("local-sensitive")
                || sensitiveFingerprintKey.contains("local-sensitive")
                || sensitiveEncryptionKey.equals(sensitiveFingerprintKey)
                || sensitiveEncryptionKey.equals(repositoryEncryptionKey)
                || sensitiveFingerprintKey.equals(repositoryEncryptionKey)) {
            throw new IllegalStateException(
                    "Production requires separate encryption and HMAC keys for sensitive user data"
            );
        }
        String allowedOrigins = environment.getProperty("jobiss.web.allowed-origins", "");
        if (allowedOrigins.isBlank()
                || allowedOrigins.contains("localhost")
                || allowedOrigins.contains("*")) {
            throw new IllegalStateException(
                    "Production requires explicit non-local CORS origins"
            );
        }
        String mailHost = environment.getProperty("spring.mail.host", "");
        if (recoveryProperties.consoleDelivery()
                || mailHost.isBlank()
                || "localhost".equalsIgnoreCase(mailHost)
                || recoveryProperties.mailFrom() == null
                || recoveryProperties.mailFrom().endsWith(".local")
                || recoveryProperties.publicBaseUrl() == null
                || !recoveryProperties.publicBaseUrl().startsWith("https://")) {
            throw new IllegalStateException(
                    "Production requires HTTPS password-reset URLs and a real mail delivery provider"
            );
        }
    }
}
