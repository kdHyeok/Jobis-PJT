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

    public ProductionConfigurationValidator(
            Environment environment,
            JobissProperties properties
    ) {
        this.environment = environment;
        this.properties = properties;
    }

    @Override
    public void run(ApplicationArguments args) {
        boolean production = Arrays.asList(environment.getActiveProfiles()).contains("prod");
        if (!production) {
            return;
        }
        if (properties.auth().jwtSecret().contains("local-development")
                || properties.ai().sharedSecret().startsWith("local-")
                || !properties.auth().cookieSecure()) {
            throw new IllegalStateException(
                    "Production requires unique JWT/AI secrets and secure cookies"
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
    }
}
