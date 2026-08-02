package com.jobiss.db;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionTemplate;

import java.util.UUID;
import java.util.function.Function;

@Component
public class RlsTransactionExecutor {

    private final JdbcClient jdbcClient;
    private final TransactionTemplate transactionTemplate;

    public RlsTransactionExecutor(JdbcClient jdbcClient, TransactionTemplate transactionTemplate) {
        this.jdbcClient = jdbcClient;
        this.transactionTemplate = transactionTemplate;
    }

    public <T> T read(UUID userId, Function<JdbcClient, T> work) {
        return execute(userId, work);
    }

    public <T> T write(UUID userId, Function<JdbcClient, T> work) {
        return execute(userId, work);
    }

    private <T> T execute(UUID userId, Function<JdbcClient, T> work) {
        if (userId == null) {
            throw new IllegalArgumentException("RLS user id is required");
        }
        return transactionTemplate.execute(status -> {
            jdbcClient.sql("select set_config('app.current_user_id', :userId, true)")
                    .param("userId", userId.toString())
                    .query(String.class)
                    .single();
            return work.apply(jdbcClient);
        });
    }
}
