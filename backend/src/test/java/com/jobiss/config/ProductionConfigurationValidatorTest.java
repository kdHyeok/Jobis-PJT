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
                        false
                ),
                new JobissProperties.Ai(
                        "http://127.0.0.1:8000",
                        "local-ai-secret",
                        true,
                        3000,
                        200,
                        2
                )
        );

        ProductionConfigurationValidator validator =
                new ProductionConfigurationValidator(environment, properties);

        assertThatThrownBy(() -> validator.run(null))
                .isInstanceOf(IllegalStateException.class);
    }

    @Test
    void acceptsExplicitSecureProductionSettings() {
        MockEnvironment environment = new MockEnvironment()
                .withProperty("jobiss.web.allowed-origins", "https://jobiss.example.com");
        environment.setActiveProfiles("prod");
        JobissProperties properties = new JobissProperties(
                new JobissProperties.Auth(
                        "a-production-jwt-secret-that-is-long-and-random",
                        3600,
                        true
                ),
                new JobissProperties.Ai(
                        "http://127.0.0.1:8000",
                        "a-production-ai-secret-that-is-long-and-random",
                        true,
                        3000,
                        200,
                        2
                )
        );

        ProductionConfigurationValidator validator =
                new ProductionConfigurationValidator(environment, properties);

        assertThatCode(() -> validator.run(null)).doesNotThrowAnyException();
    }
}
