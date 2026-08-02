package com.jobiss.evidence;

import com.jobiss.analysis.AiAnalysisClient;
import com.jobiss.analysis.AiContracts;
import com.jobiss.db.RlsTransactionExecutor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.math.BigDecimal;
import java.net.InetAddress;
import java.util.UUID;

@Component
@ConditionalOnProperty(name = "jobiss.ai.worker-enabled", havingValue = "true")
public class EvidenceVerificationWorker {

    private static final Logger log = LoggerFactory.getLogger(EvidenceVerificationWorker.class);

    private final JdbcClient jdbcClient;
    private final RlsTransactionExecutor rls;
    private final AiAnalysisClient aiClient;
    private final ObjectMapper objectMapper;
    private final String workerId;

    public EvidenceVerificationWorker(
            JdbcClient jdbcClient,
            RlsTransactionExecutor rls,
            AiAnalysisClient aiClient,
            ObjectMapper objectMapper
    ) {
        this.jdbcClient = jdbcClient;
        this.rls = rls;
        this.aiClient = aiClient;
        this.objectMapper = objectMapper;
        this.workerId = hostName() + "-evidence-" + UUID.randomUUID();
    }

    @Scheduled(fixedDelayString = "${jobiss.ai.poll-delay-ms:3000}", initialDelay = 1500)
    public void processOne() {
        ClaimedEvidence claimed = claim();
        if (claimed == null) {
            return;
        }
        try {
            AiContracts.EvidenceVerificationRequest request = load(claimed);
            AiContracts.EvidenceVerificationResponse response = aiClient.verifyEvidence(request);
            complete(claimed, response);
        } catch (Exception exception) {
            log.warn("Evidence verification {} failed: {}", claimed.id(), exception.getMessage());
            fail(claimed, exception);
        }
    }

    private ClaimedEvidence claim() {
        return jdbcClient.sql("""
                        select id, user_id, attempt_count
                        from claim_evidence_verification(:workerId)
                        """)
                .param("workerId", workerId)
                .query((rs, rowNum) -> new ClaimedEvidence(
                        rs.getObject("id", UUID.class),
                        rs.getObject("user_id", UUID.class),
                        rs.getInt("attempt_count")
                ))
                .optional()
                .orElse(null);
    }

    private AiContracts.EvidenceVerificationRequest load(ClaimedEvidence claimed) {
        return rls.write(claimed.userId(), jdbc -> {
            jdbc.sql("""
                            update evidence
                            set
                                verification_status = 'RUNNING',
                                attempt_count = :attemptCount,
                                error_message = null
                            where id = :evidenceId
                            """)
                    .param("attemptCount", claimed.attemptCount())
                    .param("evidenceId", claimed.id())
                    .update();
            return jdbc.sql("""
                            select
                                e.id,
                                e.evidence_type,
                                e.title as evidence_title,
                                e.source_url,
                                e.content::text,
                                n.id as node_id,
                                n.title as node_title,
                                n.domain,
                                n.kind,
                                n.scope_definition,
                                n.level
                            from evidence e
                            join career_nodes n on n.id = e.node_id
                            where e.id = :evidenceId
                            """)
                    .param("evidenceId", claimed.id())
                    .query((rs, rowNum) -> new AiContracts.EvidenceVerificationRequest(
                            new AiContracts.EvidencePayload(
                                    rs.getObject("id", UUID.class),
                                    rs.getString("evidence_type"),
                                    rs.getString("evidence_title"),
                                    rs.getString("source_url"),
                                    objectMapper.readTree(rs.getString("content"))
                            ),
                            new AiContracts.EvidenceNode(
                                    rs.getObject("node_id", UUID.class),
                                    rs.getString("node_title"),
                                    rs.getString("domain"),
                                    rs.getString("kind"),
                                    rs.getString("scope_definition"),
                                    rs.getInt("level")
                            )
                    ))
                    .single();
        });
    }

    private void complete(
            ClaimedEvidence claimed,
            AiContracts.EvidenceVerificationResponse response
    ) {
        rls.write(claimed.userId(), jdbc -> {
            String verdict = normalizeVerdict(response);
            JsonNode result = objectMapper.valueToTree(response);
            UUID nodeId = jdbc.sql("""
                            update evidence
                            set
                                verification_status = :verdict,
                                verification_result = cast(:result as jsonb),
                                completed_at = now()
                            where id = :evidenceId
                            returning node_id
                            """)
                    .param("verdict", verdict)
                    .param("result", objectMapper.writeValueAsString(result))
                    .param("evidenceId", claimed.id())
                    .query(UUID.class)
                    .single();
            if ("VERIFIED".equals(verdict)) {
                jdbc.sql("""
                                update node_progress
                                set
                                    status = 'COMPLETED',
                                    completion_method = 'AI_EVIDENCE',
                                    completed_at = now()
                                where node_id = :nodeId
                                """)
                        .param("nodeId", nodeId)
                        .update();
            }
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
                                'EVIDENCE_VERIFIED',
                                :title,
                                :body,
                                jsonb_build_object(
                                    'evidenceId', cast(:evidenceId as text),
                                    'nodeId', cast(:nodeId as text),
                                    'verdict', :verdict
                                )
                            )
                            """)
                    .param("userId", claimed.userId())
                    .param("title", "VERIFIED".equals(verdict)
                            ? "단계 검증을 통과했어요"
                            : "제출 증거 검토가 끝났어요")
                    .param("body", response.summary())
                    .param("evidenceId", claimed.id())
                    .param("nodeId", nodeId)
                    .param("verdict", verdict)
                    .update();
            finish(jdbc, claimed);
            return null;
        });
    }

    private void fail(ClaimedEvidence claimed, Exception exception) {
        rls.write(claimed.userId(), jdbc -> {
            jdbc.sql("""
                            update evidence
                            set
                                verification_status = 'FAILED',
                                error_message = :message,
                                completed_at = now()
                            where id = :evidenceId
                            """)
                    .param("message", safeMessage(exception))
                    .param("evidenceId", claimed.id())
                    .update();
            finish(jdbc, claimed);
            return null;
        });
    }

    private void finish(JdbcClient jdbc, ClaimedEvidence claimed) {
        jdbc.sql("select finish_evidence_verification(:evidenceId, :userId)")
                .param("evidenceId", claimed.id())
                .param("userId", claimed.userId())
                .query(Object.class)
                .optional();
    }

    private String normalizeVerdict(AiContracts.EvidenceVerificationResponse response) {
        if ("VERIFIED".equals(response.verdict())
                && (response.confidence() == null
                || response.confidence().compareTo(new BigDecimal("0.75")) < 0)) {
            return "NEEDS_WORK";
        }
        return switch (response.verdict()) {
            case "VERIFIED", "NEEDS_WORK", "REJECTED" -> response.verdict();
            default -> "NEEDS_WORK";
        };
    }

    private String safeMessage(Exception exception) {
        String message = exception.getMessage();
        if (message == null || message.isBlank()) {
            return "증거 검증을 완료하지 못했습니다.";
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

    private record ClaimedEvidence(UUID id, UUID userId, int attemptCount) {
    }
}
