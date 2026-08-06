package com.jobiss.analysis;

import com.jobiss.common.ApiException;
import com.jobiss.db.RlsTransactionExecutor;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;

import java.util.UUID;

@Component
public class AiUsageLimitService {

    public enum Kind {
        CHAT(60),
        ANALYSIS(20),
        EVIDENCE(30),
        CAREER(20),
        ASSESSMENT(40),
        LEARNING(20);

        private final int hourlyLimit;

        Kind(int hourlyLimit) {
            this.hourlyLimit = hourlyLimit;
        }
    }

    private final RlsTransactionExecutor rls;

    public AiUsageLimitService(RlsTransactionExecutor rls) {
        this.rls = rls;
    }

    public void consume(UUID userId, Kind kind) {
        rls.write(userId, jdbc -> {
            consume(jdbc, userId, kind);
            return null;
        });
    }

    public void consume(JdbcClient jdbc, UUID userId, Kind kind) {
        jdbc.sql("""
                        delete from ai_usage_hourly
                        where hour_start < date_trunc('hour', now()) - interval '30 days'
                        """)
                .update();
        boolean accepted = jdbc.sql("""
                        insert into ai_usage_hourly (
                            user_id,
                            usage_kind,
                            hour_start,
                            usage_count
                        )
                        values (
                            :userId,
                            :usageKind,
                            date_trunc('hour', now()),
                            1
                        )
                        on conflict (user_id, usage_kind, hour_start)
                        do update set
                            usage_count = ai_usage_hourly.usage_count + 1,
                            updated_at = now()
                        where ai_usage_hourly.usage_count < :maxCount
                        returning usage_count
                        """)
                .param("userId", userId)
                .param("usageKind", kind.name())
                .param("maxCount", kind.hourlyLimit)
                .query(Integer.class)
                .optional()
                .isPresent();
        if (!accepted) {
            throw new ApiException(
                    HttpStatus.TOO_MANY_REQUESTS,
                    "AI_USAGE_LIMITED",
                    "시간당 AI 사용 한도에 도달했습니다. 잠시 후 다시 시도해 주세요."
            );
        }
    }
}
