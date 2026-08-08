package com.jobiss.analysis;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionTemplate;

@Component
@ConditionalOnProperty(name = "jobiss.ai.worker-enabled", havingValue = "true")
public class AuxiliaryAiJobRecovery {

    private static final Logger log = LoggerFactory.getLogger(AuxiliaryAiJobRecovery.class);

    private final JdbcClient jdbc;
    private final TransactionTemplate transactions;

    public AuxiliaryAiJobRecovery(JdbcClient jdbc, TransactionTemplate transactions) {
        this.jdbc = jdbc;
        this.transactions = transactions;
    }

    @Scheduled(fixedDelayString = "${jobiss.ai.recovery-delay-ms:30000}")
    public void recover() {
        try {
            Integer recovered = transactions.execute(status -> jdbc.sql(
                            "select recover_stale_auxiliary_ai_jobs()"
                    )
                    .query(Integer.class)
                    .single());
            if (recovered != null && recovered > 0) {
                log.warn("Recovered {} stale auxiliary AI jobs", recovered);
            }
        } catch (RuntimeException exception) {
            log.warn("Could not recover stale auxiliary AI jobs: {}", exception.getMessage());
        }
    }
}
