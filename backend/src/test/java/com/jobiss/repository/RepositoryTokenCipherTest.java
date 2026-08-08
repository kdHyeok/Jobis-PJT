package com.jobiss.repository;

import com.jobiss.config.RepositoryProperties;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class RepositoryTokenCipherTest {

    @Test
    void encryptsWithRandomizedAuthenticatedCiphertext() {
        RepositoryProperties properties = new RepositoryProperties(
                "test-only-repository-encryption-key-32-characters",
                null,
                null
        );
        RepositoryTokenCipher cipher = new RepositoryTokenCipher(properties);

        String first = cipher.encrypt("secret-access-token");
        String second = cipher.encrypt("secret-access-token");

        assertThat(first).isNotEqualTo(second);
        assertThat(first).doesNotContain("secret-access-token");
        assertThat(cipher.decrypt(first)).isEqualTo("secret-access-token");
        assertThat(cipher.decrypt(second)).isEqualTo("secret-access-token");
    }
}
