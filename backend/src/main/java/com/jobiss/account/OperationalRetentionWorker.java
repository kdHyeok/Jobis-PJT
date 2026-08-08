package com.jobiss.account;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
public class OperationalRetentionWorker {
    private final JdbcClient jdbc;
    public OperationalRetentionWorker(JdbcClient jdbc) { this.jdbc = jdbc; }

    @Scheduled(
            initialDelayString = "${jobiss.retention.initial-delay-ms:120000}",
            fixedDelayString = "${jobiss.retention.cleanup-delay-ms:86400000}"
    )
    public void cleanup() {
        jdbc.sql("select purge_expired_operational_data()::text")
                .query(String.class)
                .optional();
    }
}
