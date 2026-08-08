package com.jobiss.security;

import com.jobiss.config.JobissProperties;
import org.junit.jupiter.api.Test;

import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class JwtServiceTest {

    @Test
    void roundTripsAuthenticatedUserId() {
        JwtService service = new JwtService(properties(
                "a-secure-development-secret-with-more-than-32-bytes"
        ));
        UUID userId = UUID.randomUUID();

        String token = service.createAccessToken(userId, 3);

        assertThat(service.parsePrincipal(token).userId()).isEqualTo(userId);
        assertThat(service.parsePrincipal(token).authVersion()).isEqualTo(3);
    }

    @Test
    void rejectsShortSigningSecret() {
        assertThatThrownBy(() -> new JwtService(properties("too-short")))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("32 bytes");
    }

    private JobissProperties properties(String secret) {
        return new JobissProperties(
                new JobissProperties.Auth(secret, 3600, 1209600, 2592000, false),
                new JobissProperties.Ai(
                        "http://localhost:8000",
                        "test-secret",
                        false,
                        3000,
                        200,
                        2
                )
        );
    }
}
