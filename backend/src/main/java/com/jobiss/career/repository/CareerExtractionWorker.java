package com.jobiss.career.repository;

import com.jobiss.analysis.AiAnalysisClient;
import com.jobiss.analysis.AiContracts;
import com.jobiss.analysis.AiServiceException;
import com.jobiss.db.RlsTransactionExecutor;
import com.jobiss.security.SensitiveTextCipher;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import tools.jackson.databind.ObjectMapper;

import java.net.InetAddress;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

@Component
@ConditionalOnProperty(name = "jobiss.ai.worker-enabled", havingValue = "true")
public class CareerExtractionWorker {

    private static final Logger log = LoggerFactory.getLogger(CareerExtractionWorker.class);

    private final JdbcClient jdbcClient;
    private final RlsTransactionExecutor rls;
    private final AiAnalysisClient aiClient;
    private final ObjectMapper objectMapper;
    private final SensitiveTextCipher sensitiveText;
    private final String workerId;
    private final ExecutorService executor;
    private final AtomicBoolean active = new AtomicBoolean();

    public CareerExtractionWorker(
            JdbcClient jdbcClient,
            RlsTransactionExecutor rls,
            AiAnalysisClient aiClient,
            ObjectMapper objectMapper,
            SensitiveTextCipher sensitiveText
    ) {
        this.jdbcClient = jdbcClient;
        this.rls = rls;
        this.aiClient = aiClient;
        this.objectMapper = objectMapper;
        this.sensitiveText = sensitiveText;
        this.workerId = hostName() + "-career-" + UUID.randomUUID();
        this.executor = Executors.newSingleThreadExecutor(runnable -> {
            Thread thread = new Thread(runnable);
            thread.setName("jobiss-career-worker");
            thread.setDaemon(true);
            return thread;
        });
    }

    @Scheduled(fixedDelayString = "${jobiss.ai.poll-delay-ms:3000}")
    public void processOne() {
        if (!active.compareAndSet(false, true)) {
            return;
        }
        ClaimedSource claimed = claim();
        if (claimed == null) {
            active.set(false);
            return;
        }
        executor.execute(() -> {
            try {
                process(claimed);
            } finally {
                active.set(false);
            }
        });
    }

    private void process(ClaimedSource claimed) {
        try {
            AiContracts.CareerExtractionRequest request = loadRequest(claimed);
            AiContracts.CareerExtractionResponse response = aiClient.extractCareer(request);
            if (response == null || response.fragments() == null || response.fragments().isEmpty()) {
                throw new IllegalStateException("AI response did not include career fragments");
            }
            complete(claimed, response);
        } catch (Exception exception) {
            log.warn("Career extraction {} failed: {}", claimed.id(), exception.getMessage());
            fail(claimed, exception);
        }
    }

    @PreDestroy
    void shutdown() {
        interruptActiveJob();
        executor.shutdownNow();
    }

    private void interruptActiveJob() {
        try {
            jdbcClient.sql("select interrupt_auxiliary_ai_jobs(:workerId)")
                    .param("workerId", workerId)
                    .query(Integer.class)
                    .single();
        } catch (RuntimeException exception) {
            log.warn("Could not release active career job during shutdown: {}", exception.getMessage());
        }
    }

    private ClaimedSource claim() {
        return jdbcClient.sql("""
                        select id, user_id, attempt_count
                        from claim_career_source(:workerId)
                        """)
                .param("workerId", workerId)
                .query((rs, rowNum) -> new ClaimedSource(
                        rs.getObject("id", UUID.class),
                        rs.getObject("user_id", UUID.class),
                        rs.getInt("attempt_count")
                ))
                .optional()
                .orElse(null);
    }

    private AiContracts.CareerExtractionRequest loadRequest(ClaimedSource claimed) {
        return rls.write(claimed.userId(), jdbc -> {
            int updated = jdbc.sql("""
                            update career_sources
                            set
                                status = 'RUNNING',
                                stage = 'EXTRACTING',
                                stage_message = '이력과 경험을 커리어 조각으로 나누고 있어요',
                                worker_id = :workerId,
                                locked_until = now() + interval '15 minutes',
                                attempt_count = :attemptCount,
                                error_code = null,
                                error_message = null
                            where id = :sourceId
                              and status = 'QUEUED'
                            """)
                    .param("workerId", workerId)
                    .param("attemptCount", claimed.attemptCount())
                    .param("sourceId", claimed.id())
                    .update();
            if (updated == 0) {
                throw new IllegalStateException("career source is no longer queued");
            }
            return jdbc.sql("""
                            select id, source_type, title, source_url, raw_text
                            from career_sources
                            where id = :sourceId
                            """)
                    .param("sourceId", claimed.id())
                    .query((rs, rowNum) -> new AiContracts.CareerExtractionRequest(
                            rs.getObject("id", UUID.class),
                            rs.getString("source_type"),
                            rs.getString("title"),
                            rs.getString("source_url"),
                            sensitiveText.decrypt(rs.getString("raw_text"))
                    ))
                    .single();
        });
    }

    private void complete(
            ClaimedSource claimed,
            AiContracts.CareerExtractionResponse response
    ) {
        rls.write(claimed.userId(), jdbc -> {
            boolean active = jdbc.sql("""
                            select exists (
                                select 1 from career_sources
                                where id = :sourceId and status = 'RUNNING'
                            )
                            """)
                    .param("sourceId", claimed.id())
                    .query(Boolean.class)
                    .single();
            if (!active) {
                finish(jdbc, claimed);
                return null;
            }
            jdbc.sql("""
                            update career_sources
                            set
                                stage = 'VALIDATING',
                                stage_message = '추출 결과를 검토 가능한 형태로 정리하고 있어요'
                            where id = :sourceId
                            """)
                    .param("sourceId", claimed.id())
                    .update();
            jdbc.sql("""
                            delete from career_fragments
                            where source_id = :sourceId
                              and review_status <> 'CONFIRMED'
                            """)
                    .param("sourceId", claimed.id())
                    .update();
            for (AiContracts.CareerFragmentSuggestion fragment : response.fragments()) {
                jdbc.sql("""
                                insert into career_fragments (
                                    user_id,
                                    source_id,
                                    kind,
                                    title,
                                    description,
                                    canonical_key,
                                    detail
                                )
                                values (
                                    :userId,
                                    :sourceId,
                                    :kind,
                                    :title,
                                    :description,
                                    :canonicalKey,
                                    cast(:detail as jsonb)
                                )
                                """)
                        .param("userId", claimed.userId())
                        .param("sourceId", claimed.id())
                        .param("kind", fragment.kind())
                        .param("title", fragment.title())
                        .param("description", fragment.description())
                        .param("canonicalKey", fragment.canonicalKey())
                        .param("detail", objectMapper.writeValueAsString(fragment.detail()))
                        .update();
            }
            jdbc.sql("""
                            update career_sources
                            set
                                status = 'REVIEW_READY',
                                stage = 'REVIEW_READY',
                                stage_message = '저장할 조각을 확인해 주세요',
                                summary = :summary,
                                completed_at = now(),
                                locked_until = null
                            where id = :sourceId
                            """)
                    .param("summary", response.summary())
                    .param("sourceId", claimed.id())
                    .update();
            jdbc.sql("""
                            insert into notifications (
                                user_id,
                                notification_type,
                                title,
                                body,
                                payload
                            )
                            values (
                                :userId,
                                'CAREER_EXTRACTION_COMPLETED',
                                '커리어 자료 분석이 끝났어요',
                                :body,
                                jsonb_build_object('careerSourceId', cast(:sourceId as text))
                            )
                            """)
                    .param("userId", claimed.userId())
                    .param("body", response.fragments().size() + "개의 조각을 확인해 주세요.")
                    .param("sourceId", claimed.id())
                    .update();
            finish(jdbc, claimed);
            return null;
        });
    }

    private void fail(ClaimedSource claimed, Exception exception) {
        rls.write(claimed.userId(), jdbc -> {
            jdbc.sql("""
                            update career_sources
                            set
                                status = 'FAILED',
                                stage = 'FAILED',
                                stage_message = '자료를 분석하지 못했어요',
                                error_code = :errorCode,
                                error_message = :errorMessage,
                                completed_at = now(),
                                locked_until = null
                            where id = :sourceId
                              and status = 'RUNNING'
                            """)
                    .param("errorCode", classify(exception))
                    .param("errorMessage", safeMessage(exception))
                    .param("sourceId", claimed.id())
                    .update();
            finish(jdbc, claimed);
            return null;
        });
    }

    private void finish(JdbcClient jdbc, ClaimedSource claimed) {
        jdbc.sql("select finish_career_source(:sourceId, :userId)")
                .param("sourceId", claimed.id())
                .param("userId", claimed.userId())
                .query(Object.class)
                .optional();
    }

    private String classify(Exception exception) {
        if (exception instanceof AiServiceException aiException) {
            return aiException.code();
        }
        return "CAREER_EXTRACTION_FAILED";
    }

    private String safeMessage(Exception exception) {
        String message = exception.getMessage();
        if (message == null || message.isBlank()) {
            return "커리어 자료를 분석하지 못했습니다.";
        }
        return message.length() > 1000 ? message.substring(0, 1000) : message;
    }

    private static String hostName() {
        try {
            return InetAddress.getLocalHost().getHostName();
        } catch (Exception ignored) {
            return "jobiss-worker";
        }
    }

    private record ClaimedSource(UUID id, UUID userId, int attemptCount) {
    }
}
