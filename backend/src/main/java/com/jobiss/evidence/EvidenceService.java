package com.jobiss.evidence;

import com.jobiss.common.ApiException;
import com.jobiss.db.RlsTransactionExecutor;
import com.jobiss.analysis.AiUsageLimitService;
import com.jobiss.repository.RepositoryEvidenceCollector;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

@Service
public class EvidenceService {

    private final RlsTransactionExecutor rls;
    private final ObjectMapper objectMapper;
    private final AiUsageLimitService usageLimit;
    private final RepositoryEvidenceCollector repositoryCollector;

    public EvidenceService(
            RlsTransactionExecutor rls,
            ObjectMapper objectMapper,
            AiUsageLimitService usageLimit,
            RepositoryEvidenceCollector repositoryCollector
    ) {
        this.rls = rls;
        this.objectMapper = objectMapper;
        this.usageLimit = usageLimit;
        this.repositoryCollector = repositoryCollector;
    }

    public EvidenceView submit(UUID userId, UUID nodeId, SubmitEvidence command) {
        String nodeKind = rls.read(userId, jdbc -> jdbc.sql("""
                            select kind
                            from career_nodes
                            where id = :nodeId
                              and kind in ('PROJECT', 'CREDENTIAL', 'EXPERIENCE')
                              and archived_at is null
                            """)
                    .param("nodeId", nodeId)
                    .query(String.class)
                    .optional()
                    .orElse(null));
        if (nodeKind == null) {
            throw new ApiException(
                    HttpStatus.BAD_REQUEST,
                    "NODE_NOT_EVIDENCE_VERIFIABLE",
                    "기술 역량은 AI 문제로 검증하고, 프로젝트·자격·경력 단계에만 결과물 증거를 제출할 수 있습니다."
            );
        }
        if ("PROJECT".equals(nodeKind) && !repositoryCollector.supports(command.sourceUrl())) {
            throw new ApiException(
                    HttpStatus.BAD_REQUEST,
                    "REPOSITORY_URL_REQUIRED",
                    "프로젝트 검증에는 GitHub 또는 설정된 GitLab 저장소 URL이 필요합니다."
            );
        }
        usageLimit.consume(userId, AiUsageLimitService.Kind.EVIDENCE);
        return rls.write(userId, jdbc -> {
            UUID id = jdbc.sql("""
                            insert into evidence (
                                user_id,
                                node_id,
                                evidence_type,
                                title,
                                source_url,
                                content
                            )
                            values (
                                :userId,
                                :nodeId,
                                :evidenceType,
                                :title,
                                :sourceUrl,
                                cast(:content as jsonb)
                            )
                            returning id
                            """)
                    .param("userId", userId)
                    .param("nodeId", nodeId)
                    .param("evidenceType", command.evidenceType())
                    .param("title", command.title().trim())
                    .param("sourceUrl", command.sourceUrl())
                    .param("content", objectMapper.writeValueAsString(command.content()))
                    .query(UUID.class)
                    .single();
            return load(jdbc, id);
        });
    }

    public List<EvidenceView> list(UUID userId, UUID nodeId) {
        return rls.read(userId, jdbc -> jdbc.sql("""
                        select
                            id,
                            node_id,
                            evidence_type,
                            title,
                            source_url,
                            content::text,
                            verification_status,
                            verification_result::text,
                            attempt_count,
                            error_message,
                            created_at,
                            completed_at
                        from evidence
                        where node_id = :nodeId
                        order by created_at desc
                        limit 50
                        """)
                .param("nodeId", nodeId)
                .query((rs, rowNum) -> map(rs))
                .list());
    }

    public EvidenceView get(UUID userId, UUID evidenceId) {
        return rls.read(userId, jdbc -> load(jdbc, evidenceId));
    }

    public void retry(UUID userId, UUID evidenceId) {
        usageLimit.consume(userId, AiUsageLimitService.Kind.EVIDENCE);
        rls.write(userId, jdbc -> {
            int updated = jdbc.sql("""
                            update evidence
                            set
                                verification_status = 'PENDING',
                                error_message = null,
                                completed_at = null
                            where id = :evidenceId
                              and verification_status = 'FAILED'
                              and attempt_count < 3
                            """)
                    .param("evidenceId", evidenceId)
                    .update();
            if (updated == 0) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "EVIDENCE_NOT_RETRYABLE",
                        "현재 상태에서는 검증을 재시도할 수 없습니다."
                );
            }
            jdbc.sql("select requeue_evidence_verification(:evidenceId, :userId)")
                    .param("evidenceId", evidenceId)
                    .param("userId", userId)
                    .query(Object.class)
                    .optional();
            return null;
        });
    }

    private EvidenceView load(
            org.springframework.jdbc.core.simple.JdbcClient jdbc,
            UUID evidenceId
    ) {
        return jdbc.sql("""
                        select
                            id,
                            node_id,
                            evidence_type,
                            title,
                            source_url,
                            content::text,
                            verification_status,
                            verification_result::text,
                            attempt_count,
                            error_message,
                            created_at,
                            completed_at
                        from evidence
                        where id = :evidenceId
                        """)
                .param("evidenceId", evidenceId)
                .query((rs, rowNum) -> map(rs))
                .optional()
                .orElseThrow(() -> new ApiException(
                        HttpStatus.NOT_FOUND,
                        "EVIDENCE_NOT_FOUND",
                        "제출 증거를 찾을 수 없습니다."
                ));
    }

    private EvidenceView map(java.sql.ResultSet rs) throws java.sql.SQLException {
        return new EvidenceView(
                rs.getObject("id", UUID.class),
                rs.getObject("node_id", UUID.class),
                rs.getString("evidence_type"),
                rs.getString("title"),
                rs.getString("source_url"),
                readJson(rs.getString("content")),
                rs.getString("verification_status"),
                readJson(rs.getString("verification_result")),
                rs.getInt("attempt_count"),
                rs.getString("error_message"),
                rs.getObject("created_at", OffsetDateTime.class),
                rs.getObject("completed_at", OffsetDateTime.class)
        );
    }

    private JsonNode readJson(String value) {
        return value == null ? null : objectMapper.readTree(value);
    }

    public record SubmitEvidence(
            String evidenceType,
            String title,
            String sourceUrl,
            JsonNode content
    ) {
    }

    public record EvidenceView(
            UUID id,
            UUID nodeId,
            String evidenceType,
            String title,
            String sourceUrl,
            JsonNode content,
            String verificationStatus,
            JsonNode verificationResult,
            int attemptCount,
            String errorMessage,
            OffsetDateTime createdAt,
            OffsetDateTime completedAt
    ) {
    }
}
