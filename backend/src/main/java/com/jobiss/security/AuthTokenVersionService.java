package com.jobiss.security;

import com.jobiss.db.RlsTransactionExecutor;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;

import java.util.UUID;

@Component
public class AuthTokenVersionService {

    private final JdbcClient jdbc;
    private final RlsTransactionExecutor rls;

    public AuthTokenVersionService(JdbcClient jdbc, RlsTransactionExecutor rls) {
        this.jdbc = jdbc;
        this.rls = rls;
    }

    public long current(UUID userId) {
        return jdbc.sql("select current_auth_version(:userId)")
                .param("userId", userId)
                .query(Long.class)
                .optional()
                .orElse(-1L);
    }

    public boolean isCurrent(UUID userId, long tokenVersion) {
        return tokenVersion > 0 && current(userId) == tokenVersion;
    }

    public void invalidateAll(UUID userId) {
        rls.write(userId, scopedJdbc -> {
            scopedJdbc.sql("select invalidate_current_auth_tokens(:userId)")
                    .param("userId", userId)
                    .query(Long.class)
                    .single();
            return null;
        });
    }
}
