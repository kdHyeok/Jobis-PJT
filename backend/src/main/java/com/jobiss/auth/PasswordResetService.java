package com.jobiss.auth;

import com.jobiss.common.ApiException;
import com.jobiss.config.RecoveryProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.time.OffsetDateTime;
import java.util.Base64;

@Service
public class PasswordResetService {

    private static final Logger log = LoggerFactory.getLogger(PasswordResetService.class);
    private static final SecureRandom SECURE_RANDOM = new SecureRandom();
    private final JdbcClient jdbc;
    private final PasswordEncoder passwordEncoder;
    private final JavaMailSender mailSender;
    private final RecoveryProperties properties;

    public PasswordResetService(
            JdbcClient jdbc,
            PasswordEncoder passwordEncoder,
            JavaMailSender mailSender,
            RecoveryProperties properties
    ) {
        this.jdbc = jdbc;
        this.passwordEncoder = passwordEncoder;
        this.mailSender = mailSender;
        this.properties = properties;
    }

    public void request(String email) {
        byte[] tokenBytes = new byte[32];
        SECURE_RANDOM.nextBytes(tokenBytes);
        String token = Base64.getUrlEncoder().withoutPadding().encodeToString(tokenBytes);
        String tokenHash = sha256(token);
        OffsetDateTime expiresAt = OffsetDateTime.now()
                .plusMinutes(Math.max(10, Math.min(properties.tokenMinutes(), 120)));
        ResetRecipient recipient = jdbc.sql("""
                        select email, display_name
                        from issue_password_reset_token(
                            cast(:email as citext),
                            :tokenHash,
                            :expiresAt
                        )
                        """)
                .param("email", email.trim().toLowerCase())
                .param("tokenHash", tokenHash)
                .param("expiresAt", expiresAt)
                .query((rs, rowNum) -> new ResetRecipient(
                        rs.getString("email"),
                        rs.getString("display_name")
                ))
                .optional()
                .orElse(null);
        if (recipient == null) {
            return;
        }

        String baseUrl = properties.publicBaseUrl().replaceAll("/+$", "");
        String resetUrl = baseUrl + "/reset-password?token="
                + URLEncoder.encode(token, StandardCharsets.UTF_8);
        if (properties.consoleDelivery()) {
            log.warn("Development password reset link for {}: {}", recipient.email(), resetUrl);
            return;
        }

        try {
            SimpleMailMessage message = new SimpleMailMessage();
            message.setFrom(properties.mailFrom());
            message.setTo(recipient.email());
            message.setSubject("[JOBIS] 비밀번호 재설정");
            message.setText("""
                    %s님, JOBIS 비밀번호 재설정 요청을 받았습니다.

                    아래 주소에서 새 비밀번호를 설정해 주세요.
                    %s

                    이 링크는 %d분 뒤 만료됩니다. 본인이 요청하지 않았다면 이 메일을 무시해 주세요.
                    """.formatted(
                    recipient.displayName(),
                    resetUrl,
                    Math.max(10, Math.min(properties.tokenMinutes(), 120))
            ));
            mailSender.send(message);
        } catch (RuntimeException exception) {
            log.error("Password reset email delivery failed for configured mail provider", exception);
        }
    }

    public void reset(String token, String newPassword) {
        boolean consumed = jdbc.sql("""
                        select consume_password_reset_token(:tokenHash, :passwordHash)
                        """)
                .param("tokenHash", sha256(token.trim()))
                .param("passwordHash", passwordEncoder.encode(newPassword))
                .query(Boolean.class)
                .single();
        if (!consumed) {
            throw new ApiException(
                    HttpStatus.BAD_REQUEST,
                    "PASSWORD_RESET_TOKEN_INVALID",
                    "재설정 링크가 만료되었거나 이미 사용되었습니다. 새 링크를 요청해 주세요."
            );
        }
    }

    static String sha256(String value) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(value.getBytes(StandardCharsets.UTF_8));
            return java.util.HexFormat.of().formatHex(digest);
        } catch (Exception exception) {
            throw new IllegalStateException("SHA-256 is unavailable", exception);
        }
    }

    private record ResetRecipient(String email, String displayName) {
    }
}
