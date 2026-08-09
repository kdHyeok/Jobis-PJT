package com.jobiss.config;

import org.junit.jupiter.api.Test;
import org.springframework.mock.env.MockEnvironment;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class ProductionConfigurationValidatorTest {

    @Test
    void rejectsDevelopmentSecuritySettingsInProduction() {
        MockEnvironment environment = new MockEnvironment()
                .withProperty("jobiss.web.allowed-origins", "http://localhost:5173");
        environment.setActiveProfiles("prod");
        JobissProperties properties = new JobissProperties(
                new JobissProperties.Auth(
                        "local-development-secret-change-this-before-production",
                        3600,
                        1209600,
                        2592000,
                        false
                , "jobiss_access"),
                new JobissProperties.Ai(
                        "http://ai-server:8000",
                        "local-ai-secret",
                        true,
                        3000,
                        200,
                        2
                )
        );

        ProductionConfigurationValidator validator =
                new ProductionConfigurationValidator(environment, properties, repositoryProperties(
                        "local-repository-token-key-change-before-production"
                ), recoveryProperties(true));

        assertThatThrownBy(() -> validator.run(null))
                .isInstanceOf(IllegalStateException.class);
    }

    @Test
    void acceptsExplicitSecureProductionSettings() {
        MockEnvironment environment = new MockEnvironment()
                .withProperty("jobiss.web.allowed-origins", "https://jobiss.example.com")
                .withProperty("spring.mail.host", "smtp.example.com")
                .withProperty("jobiss.data-protection.encryption-key", "a-production-sensitive-encryption-key-that-is-long")
                .withProperty("jobiss.data-protection.fingerprint-key", "a-different-production-sensitive-hmac-key-that-is-long")
                .withProperty("spring.datasource.password", "unique-application-database-password")
                .withProperty("spring.flyway.password", "unique-migrator-database-password");
        environment.setActiveProfiles("prod");
        JobissProperties properties = new JobissProperties(
                new JobissProperties.Auth(
                        "a-production-jwt-secret-that-is-long-and-random",
                        3600,
                        1209600,
                        2592000,
                        true
                , "jobiss_access"),
                new JobissProperties.Ai(
                        "http://ai-server:8000",
                        "a-production-ai-secret-that-is-long-and-random",
                        true,
                        3000,
                        200,
                        2
                )
        );

        ProductionConfigurationValidator validator =
                new ProductionConfigurationValidator(environment, properties, repositoryProperties(
                        "a-separate-production-repository-key-32-characters"
                ), recoveryProperties(false));

        assertThatCode(() -> validator.run(null)).doesNotThrowAnyException();
    }

    @Test
    void rejectsDefaultRepositoryTokenKeyInProduction() {
        MockEnvironment environment = new MockEnvironment()
                .withProperty("jobiss.web.allowed-origins", "https://jobiss.example.com")
                .withProperty("spring.mail.host", "smtp.example.com")
                .withProperty("spring.datasource.password", "unique-application-database-password")
                .withProperty("spring.flyway.password", "unique-migrator-database-password");
        environment.setActiveProfiles("prod");
        JobissProperties properties = new JobissProperties(
                new JobissProperties.Auth(
                        "a-production-jwt-secret-that-is-long-and-random",
                        3600,
                        1209600,
                        2592000,
                        true
                , "jobiss_access"),
                new JobissProperties.Ai(
                        "http://ai-server:8000",
                        "a-production-ai-secret-that-is-long-and-random",
                        true,
                        3000,
                        200,
                        2
                )
        );

        ProductionConfigurationValidator validator =
                new ProductionConfigurationValidator(environment, properties, repositoryProperties(
                        "local-repository-token-key-change-before-production"
                ), recoveryProperties(false));

        assertThatThrownBy(() -> validator.run(null))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("repository token encryption key");
    }

    private static RepositoryProperties repositoryProperties(String encryptionKey) {
        return new RepositoryProperties(
                encryptionKey,
                new RepositoryProperties.GitHub(
                        "https://api.github.com", "", "", "", "https://jobiss.example.com/settings"
                ),
                new RepositoryProperties.GitLab(
                        "https://gitlab.com", "", "", "https://jobiss.example.com/settings"
                )
        );
    }

    private static RecoveryProperties recoveryProperties(boolean consoleDelivery) {
        return new RecoveryProperties(
                "https://jobiss.example.com",
                30,
                "no-reply@jobiss.example.com",
                consoleDelivery
        );
    }
}
