package com.jobiss.account;

import com.jobiss.auth.AuthService;
import com.jobiss.common.ApiException;
import com.jobiss.db.RlsTransactionExecutor;
import com.jobiss.security.SensitiveTextCipher;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.time.OffsetDateTime;
import java.util.UUID;

@Service
public class AccountService {

    private final RlsTransactionExecutor rls;
    private final PasswordEncoder passwordEncoder;
    private final ObjectMapper objectMapper;
    private final AuthService authService;
    private final SensitiveTextCipher sensitiveText;

    public AccountService(
            RlsTransactionExecutor rls,
            PasswordEncoder passwordEncoder,
            ObjectMapper objectMapper,
            AuthService authService,
            SensitiveTextCipher sensitiveText
    ) {
        this.rls = rls;
        this.passwordEncoder = passwordEncoder;
        this.objectMapper = objectMapper;
        this.authService = authService;
        this.sensitiveText = sensitiveText;
    }

    public AuthService.UserView updateProfile(UUID userId, String email, String displayName) {
        String normalizedEmail = email.trim().toLowerCase();
        try {
            rls.write(userId, jdbc -> {
                jdbc.sql("""
                                update users
                                set email = cast(:email as citext), display_name = :displayName
                                where id = :userId
                                """)
                        .param("email", normalizedEmail)
                        .param("displayName", displayName.trim())
                        .param("userId", userId)
                        .update();
                jdbc.sql("select update_current_auth_identity(:userId, cast(:email as citext), cast(null as text))")
                        .param("userId", userId)
                        .param("email", normalizedEmail)
                        .query(Object.class)
                        .optional();
                return null;
            });
        } catch (DataIntegrityViolationException exception) {
            throw new ApiException(HttpStatus.CONFLICT, "EMAIL_ALREADY_EXISTS", "이미 사용 중인 이메일입니다.");
        }
        return authService.me(userId);
    }

    public void changePassword(UUID userId, String currentPassword, String newPassword) {
        rls.write(userId, jdbc -> {
            requirePassword(jdbc, userId, currentPassword);
            jdbc.sql("select update_current_auth_identity(:userId, cast(null as citext), :passwordHash)")
                    .param("userId", userId)
                    .param("passwordHash", passwordEncoder.encode(newPassword))
                    .query(Object.class)
                    .optional();
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

    public JsonNode exportData(UUID userId) {
        String json = rls.read(userId, jdbc -> jdbc.sql("""
                        select jsonb_build_object(
                            'schemaVersion', 1,
                            'exportedAt', now(),
                            'profile', (select to_jsonb(u) - 'id' from users u where u.id = :userId),
                            'goals', (select to_jsonb(g) - 'user_id' from user_goal_profiles g where g.user_id = :userId),
                            'postings', coalesce((select jsonb_agg(to_jsonb(p) - 'user_id' order by p.created_at) from job_postings p where p.user_id = :userId), '[]'::jsonb),
                            'careerSources', coalesce((select jsonb_agg(to_jsonb(s) - 'user_id' order by s.created_at) from career_sources s where s.user_id = :userId), '[]'::jsonb),
                            'careerFragments', coalesce((select jsonb_agg(to_jsonb(f) - 'user_id' order by f.created_at) from career_fragments f where f.user_id = :userId), '[]'::jsonb),
                            'conversations', coalesce((select jsonb_agg(to_jsonb(c) - 'user_id' order by c.created_at) from conversations c where c.user_id = :userId), '[]'::jsonb),
                            'messages', coalesce((select jsonb_agg(to_jsonb(m) - 'user_id' order by m.created_at) from conversation_messages m where m.user_id = :userId), '[]'::jsonb),
                            'roadmaps', coalesce((select jsonb_agg(to_jsonb(r) - 'user_id' order by r.version) from roadmap_versions r where r.user_id = :userId), '[]'::jsonb),
                            'notifications', coalesce((select jsonb_agg(to_jsonb(n) - 'user_id' order by n.created_at) from notifications n where n.user_id = :userId), '[]'::jsonb)
                        )::text
                        """)
                .param("userId", userId)
                .query(String.class)
                .single());
        try {
            JsonNode result = objectMapper.readTree(json);
            decryptExportArray(result.path("postings"));
            decryptExportArray(result.path("careerSources"));
            return result;
        } catch (Exception exception) {
            throw new ApiException(HttpStatus.INTERNAL_SERVER_ERROR, "EXPORT_FAILED", "내 데이터를 내보내지 못했습니다.");
        }
    }

    private void decryptExportArray(JsonNode items) {
        if (!items.isArray()) return;
        for (JsonNode item : items) {
            if (item instanceof tools.jackson.databind.node.ObjectNode object
                    && object.path("raw_text").isString()) {
                object.put("raw_text", sensitiveText.decrypt(object.path("raw_text").stringValue("")));
            }
        }
    }

    public DeletionReceipt deleteAccount(UUID userId, String password) {
        return rls.write(userId, jdbc -> {
            requirePassword(jdbc, userId, password);
            jdbc.sql("select delete_current_account(:userId)")
                    .param("userId", userId)
                    .query(Object.class)
                    .optional();
            return jdbc.sql("""
                            select request_id, deletion_status, requested_at, purge_after
                            from current_account_deletion_receipt(:userId)
                            """)
                    .param("userId", userId)
                    .query((rs, rowNum) -> new DeletionReceipt(
                            rs.getObject("request_id", UUID.class),
                            rs.getString("deletion_status"),
                            rs.getObject("requested_at", OffsetDateTime.class),
                            rs.getObject("purge_after", OffsetDateTime.class)
                    ))
                    .single();
        });
    }

    public record DeletionReceipt(
            UUID requestId,
            String status,
            OffsetDateTime requestedAt,
            OffsetDateTime purgeAfter
    ) {}

    private void requirePassword(JdbcClient jdbc, UUID userId, String password) {
        String email = jdbc.sql("select email::text from users where id = :userId")
                .param("userId", userId)
                .query(String.class)
                .single();
        String hash = jdbc.sql("select password_hash from auth_lookup_user(cast(:email as citext))")
                .param("email", email)
                .query(String.class)
                .single();
        if (!passwordEncoder.matches(password, hash)) {
            throw new ApiException(HttpStatus.UNAUTHORIZED, "INVALID_PASSWORD", "현재 비밀번호가 올바르지 않습니다.");
        }
    }
}
