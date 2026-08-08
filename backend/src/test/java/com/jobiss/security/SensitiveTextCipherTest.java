package com.jobiss.security;

import com.jobiss.config.DataProtectionProperties;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class SensitiveTextCipherTest {

    private final SensitiveTextCipher cipher = new SensitiveTextCipher(
            new DataProtectionProperties(
                    "test-sensitive-encryption-key-with-enough-length",
                    "different-sensitive-fingerprint-key-with-enough-length"
            )
    );

    @Test
    void encryptsWithRandomNonceAndDecryptsLegacyPlaintext() {
        String plaintext = "이력서와 채용 공고의 민감한 원문";
        String first = cipher.encrypt(plaintext);
        String second = cipher.encrypt(plaintext);

        assertThat(first).startsWith("enc:v1:").isNotEqualTo(second);
        assertThat(cipher.decrypt(first)).isEqualTo(plaintext);
        assertThat(cipher.decrypt(plaintext)).isEqualTo(plaintext);
    }

    @Test
    void fingerprintIsStableButDoesNotExposePlaintext() {
        String first = cipher.fingerprint("normalized posting");
        assertThat(first).hasSize(64).isEqualTo(cipher.fingerprint("normalized posting"));
        assertThat(first).doesNotContain("normalized");
    }
}
