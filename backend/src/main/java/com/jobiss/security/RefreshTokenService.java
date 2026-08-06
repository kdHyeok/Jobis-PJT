package com.jobiss.security;

import com.jobiss.common.ApiException;
import com.jobiss.config.JobissProperties;
import com.jobiss.db.RlsTransactionExecutor;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.time.OffsetDateTime;
import java.util.Base64;
import java.util.HexFormat;
import java.util.UUID;

@Service
public class RefreshTokenService {

    private static final SecureRandom RANDOM = new SecureRandom();

    private final RlsTransactionExecutor rls;
    private final JobissProperties properties;

    public RefreshTokenService(RlsTransactionExecutor rls, JobissProperties properties) {
        this.rls = rls;
        this.properties = properties;
    }

    public IssuedRefreshToken issue(UUID userId, boolean rememberMe) {
        return rls.write(userId, jdbc -> insert(jdbc, userId, UUID.randomUUID(), rememberMe));
    }

    public IssuedRefreshToken rotate(String rawToken) {
        UUID userId = tokenUser(rawToken);
        String tokenHash = hash(rawToken);
        RotationOutcome outcome = rls.write(userId, jdbc -> {
            StoredToken current = jdbc.sql("""
                            select id, family_id, remember_me, expires_at, revoked_at
                            from auth_refresh_tokens token
                            where token.user_id = :userId and token.token_hash = :tokenHash
                              and current_auth_version(token.user_id) is not null
                            for update
                            """)
                    .param("userId", userId)
                    .param("tokenHash", tokenHash)
                    .query((rs, rowNum) -> new StoredToken(
                            rs.getObject("id", UUID.class),
                            rs.getObject("family_id", UUID.class),
                            rs.getBoolean("remember_me"),
                            rs.getObject("expires_at", OffsetDateTime.class),
                            rs.getObject("revoked_at", OffsetDateTime.class)
                    ))
                    .optional()
                    .orElseThrow(this::invalid);

            if (current.revokedAt() != null) {
                revokeFamily(jdbc, userId, current.familyId());
                return RotationOutcome.reuseDetected();
            }
            if (!current.expiresAt().isAfter(OffsetDateTime.now())) {
                revokeFamily(jdbc, userId, current.familyId());
                return RotationOutcome.expiredToken();
            }

            IssuedRefreshToken replacement = insert(
                    jdbc,
                    userId,
                    current.familyId(),
                    current.rememberMe()
            );
            jdbc.sql("""
                            update auth_refresh_tokens
                            set revoked_at = now(), last_used_at = now(), replaced_by = :replacementId
                            where id = :id and user_id = :userId
                            """)
                    .param("replacementId", replacement.id())
                    .param("id", current.id())
                    .param("userId", userId)
                    .update();
            return RotationOutcome.success(replacement);
        });
        if (outcome.reused()) {
            throw new ApiException(
                    HttpStatus.UNAUTHORIZED,
                    "REFRESH_TOKEN_REUSE_DETECTED",
                    "로그인 세션을 안전하게 종료했습니다. 다시 로그인해 주세요."
            );
        }
        if (outcome.expired()) throw invalid();
        return outcome.token();
    }

    public void revokeFamily(String rawToken) {
        if (rawToken == null || rawToken.isBlank()) return;
        UUID userId;
        try {
            userId = tokenUser(rawToken);
        } catch (ApiException ignored) {
            return;
        }
        String tokenHash = hash(rawToken);
        rls.write(userId, jdbc -> {
            jdbc.sql("""
                            update auth_refresh_tokens target
                            set revoked_at = coalesce(target.revoked_at, now())
                            where target.user_id = :userId
                              and target.family_id = (
                                  select source.family_id
                                  from auth_refresh_tokens source
                                  where source.user_id = :userId and source.token_hash = :tokenHash
                              )
                            """)
                    .param("userId", userId)
                    .param("tokenHash", tokenHash)
                    .update();
            return null;
        });
    }

    public void revokeAll(UUID userId) {
        rls.write(userId, jdbc -> {
            jdbc.sql("""
                            update auth_refresh_tokens
                            set revoked_at = coalesce(revoked_at, now())
                            where user_id = :userId and revoked_at is null
                            """)
                    .param("userId", userId)
                    .update();
            return null;
        });
    }

    private IssuedRefreshToken insert(
            JdbcClient jdbc,
            UUID userId,
            UUID familyId,
            boolean rememberMe
    ) {
        byte[] random = new byte[48];
        RANDOM.nextBytes(random);
        String raw = userId + "." + Base64.getUrlEncoder().withoutPadding().encodeToString(random);
        long lifetime = rememberMe
                ? properties.auth().rememberMeRefreshTokenSeconds()
                : properties.auth().refreshTokenSeconds();
        OffsetDateTime expiresAt = OffsetDateTime.now().plusSeconds(lifetime);
        UUID id = jdbc.sql("""
                        insert into auth_refresh_tokens (
                            user_id, family_id, token_hash, remember_me, expires_at
                        ) values (
                            :userId, :familyId, :tokenHash, :rememberMe, :expiresAt
                        ) returning id
                        """)
                .param("userId", userId)
                .param("familyId", familyId)
                .param("tokenHash", hash(raw))
                .param("rememberMe", rememberMe)
                .param("expiresAt", expiresAt)
                .query(UUID.class)
                .single();
        return new IssuedRefreshToken(id, userId, familyId, raw, expiresAt, rememberMe);
    }

    private void revokeFamily(JdbcClient jdbc, UUID userId, UUID familyId) {
        jdbc.sql("""
                        update auth_refresh_tokens
                        set revoked_at = coalesce(revoked_at, now())
                        where user_id = :userId and family_id = :familyId
                        """)
                .param("userId", userId)
                .param("familyId", familyId)
                .update();
    }

    private UUID tokenUser(String rawToken) {
        if (rawToken == null || rawToken.isBlank()) throw invalid();
        int separator = rawToken.indexOf('.');
        if (separator <= 0) throw invalid();
        try {
            return UUID.fromString(rawToken.substring(0, separator));
        } catch (IllegalArgumentException exception) {
            throw invalid();
        }
    }

    private String hash(String value) {
        try {
            return HexFormat.of().formatHex(
                    MessageDigest.getInstance("SHA-256")
                            .digest(value.getBytes(StandardCharsets.UTF_8))
            );
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is unavailable", exception);
        }
    }

    private ApiException invalid() {
        return new ApiException(
                HttpStatus.UNAUTHORIZED,
                "REFRESH_TOKEN_INVALID",
                "로그인 세션이 만료되었습니다. 다시 로그인해 주세요."
        );
    }

    private record StoredToken(
            UUID id,
            UUID familyId,
            boolean rememberMe,
            OffsetDateTime expiresAt,
            OffsetDateTime revokedAt
    ) {
    }

    private record RotationOutcome(
            IssuedRefreshToken token,
            boolean reused,
            boolean expired
    ) {
        static RotationOutcome success(IssuedRefreshToken token) {
            return new RotationOutcome(token, false, false);
        }

        static RotationOutcome reuseDetected() {
            return new RotationOutcome(null, true, false);
        }

        static RotationOutcome expiredToken() {
            return new RotationOutcome(null, false, true);
        }
    }

    public record IssuedRefreshToken(
            UUID id,
            UUID userId,
            UUID familyId,
            String rawToken,
            OffsetDateTime expiresAt,
            boolean rememberMe
    ) {
    }
}
