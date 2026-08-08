package com.jobiss.account;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
public class AccountPurgeWorker {

    private final JdbcClient jdbc;

    public AccountPurgeWorker(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    @Scheduled(fixedDelayString = "${jobiss.account.purge-delay-ms:60000}")
    public void purgeDueAccounts() {
        jdbc.sql("select purge_due_withdrawn_accounts(25)")
                .query(Integer.class)
                .optional();
    }
}
