package com.jobiss.operator;

import com.jobiss.common.ApiException;
import com.jobiss.db.RlsTransactionExecutor;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

@Service
public class OperatorPostingService {

    private final RlsTransactionExecutor rls;
    private final ObjectMapper objectMapper;

    public OperatorPostingService(
            RlsTransactionExecutor rls,
            ObjectMapper objectMapper
    ) {
        this.rls = rls;
        this.objectMapper = objectMapper;
    }

    public List<DuplicateCandidateView> list(UUID operatorId, String status) {
        return rls.read(operatorId, jdbc -> {
            ensureOperator(jdbc);
            String normalizedStatus = status == null || status.isBlank()
                    ? "OPEN"
                    : status.trim().toUpperCase();
            return jdbc.sql("""
                            select
                                candidate.id,
                                candidate.match_kind,
                                candidate.similarity_score,
                                candidate.proposed_action,
                                candidate.proposal_reason,
                                candidate.status,
                                candidate.created_at,
                                left_posting.id as left_id,
                                left_posting.company_name as left_company,
                                left_posting.role_title as left_role,
                                left_posting.source_url as left_url,
                                left_posting.lifecycle_status as left_lifecycle,
                                right_posting.id as right_id,
                                right_posting.company_name as right_company,
                                right_posting.role_title as right_role,
                                right_posting.source_url as right_url,
                                right_posting.lifecycle_status as right_lifecycle
                            from posting_duplicate_candidates candidate
                            join posting_catalog left_posting
                              on left_posting.id = candidate.left_posting_id
                            join posting_catalog right_posting
                              on right_posting.id = candidate.right_posting_id
                            where candidate.status = :status
                            order by
                                candidate.similarity_score desc,
                                candidate.created_at
                            limit 200
                            """)
                    .param("status", normalizedStatus)
                    .query((rs, rowNum) -> new DuplicateCandidateView(
                            rs.getObject("id", UUID.class),
                            rs.getString("match_kind"),
                            rs.getBigDecimal("similarity_score"),
                            rs.getString("proposed_action"),
                            rs.getString("proposal_reason"),
                            rs.getString("status"),
                            new PostingSide(
                                    rs.getObject("left_id", UUID.class),
                                    rs.getString("left_company"),
                                    rs.getString("left_role"),
                                    rs.getString("left_url"),
                                    rs.getString("left_lifecycle")
                            ),
                            new PostingSide(
                                    rs.getObject("right_id", UUID.class),
                                    rs.getString("right_company"),
                                    rs.getString("right_role"),
                                    rs.getString("right_url"),
                                    rs.getString("right_lifecycle")
                            ),
                            rs.getObject("created_at", OffsetDateTime.class)
                    ))
                    .list();
        });
    }

    public void resolve(
            UUID operatorId,
            UUID candidateId,
            String action,
            UUID canonicalPostingId,
            String reason
    ) {
        rls.write(operatorId, jdbc -> {
            ensureOperator(jdbc);
            Candidate candidate = jdbc.sql("""
                            select
                                id,
                                left_posting_id,
                                right_posting_id,
                                status
                            from posting_duplicate_candidates
                            where id = :candidateId
                            for update
                            """)
                    .param("candidateId", candidateId)
                    .query((rs, rowNum) -> new Candidate(
                            rs.getObject("id", UUID.class),
                            rs.getObject("left_posting_id", UUID.class),
                            rs.getObject("right_posting_id", UUID.class),
                            rs.getString("status")
                    ))
                    .optional()
                    .orElseThrow(() -> new ApiException(
                            HttpStatus.NOT_FOUND,
                            "DUPLICATE_CANDIDATE_NOT_FOUND",
                            "중복 검토 항목을 찾을 수 없습니다."
                    ));
            if (!"OPEN".equals(candidate.status())
                    && !"ON_HOLD".equals(candidate.status())) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "DUPLICATE_CANDIDATE_RESOLVED",
                        "이미 최종 처리된 중복 검토 항목입니다."
                );
            }

            String normalizedAction = action.trim().toUpperCase();
            if ("MERGE".equals(normalizedAction)) {
                UUID canonical = canonicalPostingId == null
                        ? candidate.leftId()
                        : canonicalPostingId;
                if (!canonical.equals(candidate.leftId())
                        && !canonical.equals(candidate.rightId())) {
                    throw new ApiException(
                            HttpStatus.BAD_REQUEST,
                            "INVALID_CANONICAL_POSTING",
                            "두 공고 중 유지할 정본을 선택해 주세요."
                    );
                }
                UUID duplicate = canonical.equals(candidate.leftId())
                        ? candidate.rightId()
                        : candidate.leftId();
                merge(jdbc, operatorId, candidate, canonical, duplicate, reason);
            } else if ("SEPARATE".equals(normalizedAction)) {
                updateCandidate(
                        jdbc,
                        operatorId,
                        candidate,
                        "SEPARATED",
                        "SEPARATE",
                        reason
                );
            } else if ("HOLD".equals(normalizedAction)) {
                updateCandidate(
                        jdbc,
                        operatorId,
                        candidate,
                        "ON_HOLD",
                        "HOLD",
                        reason
                );
            } else {
                throw new ApiException(
                        HttpStatus.BAD_REQUEST,
                        "INVALID_OPERATOR_ACTION",
                        "MERGE, SEPARATE, HOLD 중 하나를 선택해 주세요."
                );
            }
            return null;
        });
    }

    public void rollback(UUID operatorId, UUID auditId, String reason) {
        rls.write(operatorId, jdbc -> {
            ensureOperator(jdbc);
            AuditRow audit = jdbc.sql("""
                            select
                                id,
                                action_kind,
                                target_id,
                                before_state::text,
                                rolled_back_at
                            from operator_action_audit
                            where id = :auditId
                            for update
                            """)
                    .param("auditId", auditId)
                    .query((rs, rowNum) -> new AuditRow(
                            rs.getObject("id", UUID.class),
                            rs.getString("action_kind"),
                            rs.getObject("target_id", UUID.class),
                            objectMapper.readTree(rs.getString("before_state")),
                            rs.getObject("rolled_back_at", OffsetDateTime.class)
                    ))
                    .optional()
                    .orElseThrow(() -> new ApiException(
                            HttpStatus.NOT_FOUND,
                            "OPERATOR_AUDIT_NOT_FOUND",
                            "되돌릴 운영 기록을 찾을 수 없습니다."
                    ));
            if (audit.rolledBackAt() != null || !"MERGE".equals(audit.actionKind())) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "OPERATOR_ACTION_NOT_ROLLBACKABLE",
                        "이 작업은 되돌릴 수 없거나 이미 되돌렸습니다."
                );
            }
            UUID canonical = UUID.fromString(
                    audit.beforeState().path("canonicalId").stringValue("")
            );
            UUID duplicate = UUID.fromString(
                    audit.beforeState().path("duplicateId").stringValue("")
            );
            jdbc.sql("""
                            update posting_catalog_observations
                            set posting_catalog_id = :duplicateId
                            where posting_catalog_id = :canonicalId
                              and id in (
                                select cast(value #>> '{}' as uuid)
                                from jsonb_array_elements(
                                    cast(:observationIds as jsonb)
                                )
                              )
                            """)
                    .param("canonicalId", canonical)
                    .param("duplicateId", duplicate)
                    .param(
                            "observationIds",
                            audit.beforeState().path("observationIds").toString()
                    )
                    .update();
            jdbc.sql("""
                            update job_postings posting
                            set canonical_posting_id = observation.posting_catalog_id
                            from posting_catalog_observations observation
                            where observation.private_posting_id = posting.id
                              and observation.posting_catalog_id = :duplicateId
                            """)
                    .param("duplicateId", duplicate)
                    .update();
            jdbc.sql("""
                            update posting_catalog
                            set
                                moderation_status = 'VERIFIED',
                                active = true,
                                updated_at = now()
                            where id = :duplicateId
                            """)
                    .param("duplicateId", duplicate)
                    .update();
            jdbc.sql("""
                            update posting_duplicate_candidates
                            set
                                status = 'OPEN',
                                resolved_by = null,
                                resolved_at = null
                            where id = :candidateId
                            """)
                    .param("candidateId", audit.targetId())
                    .update();
            jdbc.sql("""
                            update operator_action_audit
                            set
                                rolled_back_at = now(),
                                reason = concat_ws(E'\n', reason, :reason)
                            where id = :auditId
                            """)
                    .param("reason", reason)
                    .param("auditId", auditId)
                    .update();
            return null;
        });
    }

    private void merge(
            org.springframework.jdbc.core.simple.JdbcClient jdbc,
            UUID operatorId,
            Candidate candidate,
            UUID canonical,
            UUID duplicate,
            String reason
    ) {
        List<UUID> observationIds = jdbc.sql("""
                        select id
                        from posting_catalog_observations
                        where posting_catalog_id = :duplicateId
                        order by id
                        """)
                .param("duplicateId", duplicate)
                .query(UUID.class)
                .list();
        var before = objectMapper.createObjectNode();
        before.put("canonicalId", canonical.toString());
        before.put("duplicateId", duplicate.toString());
        var ids = before.putArray("observationIds");
        observationIds.forEach(id -> ids.add(id.toString()));

        jdbc.sql("""
                        insert into posting_catalog_requirements (
                            posting_catalog_id,
                            catalog_competency_id,
                            relation_kind,
                            required_scope,
                            required_level,
                            confidence
                        )
                        select
                            :canonicalId,
                            catalog_competency_id,
                            relation_kind,
                            required_scope,
                            required_level,
                            confidence
                        from posting_catalog_requirements
                        where posting_catalog_id = :duplicateId
                        on conflict (
                            posting_catalog_id,
                            catalog_competency_id,
                            relation_kind
                        )
                        do update set
                            required_scope = excluded.required_scope,
                            required_level = greatest(
                                posting_catalog_requirements.required_level,
                                excluded.required_level
                            ),
                            confidence = greatest(
                                posting_catalog_requirements.confidence,
                                excluded.confidence
                            )
                        """)
                .param("canonicalId", canonical)
                .param("duplicateId", duplicate)
                .update();
        jdbc.sql("""
                        update posting_catalog_observations
                        set posting_catalog_id = :canonicalId
                        where posting_catalog_id = :duplicateId
                        """)
                .param("canonicalId", canonical)
                .param("duplicateId", duplicate)
                .update();
        jdbc.sql("""
                        update job_postings
                        set canonical_posting_id = :canonicalId
                        where canonical_posting_id = :duplicateId
                        """)
                .param("canonicalId", canonical)
                .param("duplicateId", duplicate)
                .update();
        jdbc.sql("""
                        update posting_catalog
                        set
                            moderation_status = 'MERGED',
                            active = false,
                            updated_at = now()
                        where id = :duplicateId
                        """)
                .param("duplicateId", duplicate)
                .update();
        jdbc.sql("""
                        update posting_duplicate_candidates
                        set
                            status = 'MERGED',
                            resolved_by = :operatorId,
                            resolved_at = now()
                        where id = :candidateId
                        """)
                .param("operatorId", operatorId)
                .param("candidateId", candidate.id())
                .update();
        insertAudit(
                jdbc,
                operatorId,
                candidate.id(),
                "MERGE",
                before,
                reason
        );
    }

    private void updateCandidate(
            org.springframework.jdbc.core.simple.JdbcClient jdbc,
            UUID operatorId,
            Candidate candidate,
            String status,
            String action,
            String reason
    ) {
        jdbc.sql("""
                        update posting_duplicate_candidates
                        set
                            status = :status,
                            resolved_by = case
                                when :status = 'ON_HOLD' then null
                                else :operatorId
                            end,
                            resolved_at = case
                                when :status = 'ON_HOLD' then null
                                else now()
                            end
                        where id = :candidateId
                        """)
                .param("status", status)
                .param("operatorId", operatorId)
                .param("candidateId", candidate.id())
                .update();
        var before = objectMapper.createObjectNode();
        before.put("status", candidate.status());
        insertAudit(jdbc, operatorId, candidate.id(), action, before, reason);
    }

    private void insertAudit(
            org.springframework.jdbc.core.simple.JdbcClient jdbc,
            UUID operatorId,
            UUID candidateId,
            String action,
            JsonNode before,
            String reason
    ) {
        jdbc.sql("""
                        insert into operator_action_audit (
                            operator_user_id,
                            action_kind,
                            target_type,
                            target_id,
                            before_state,
                            after_state,
                            reason
                        )
                        values (
                            :operatorId,
                            :action,
                            'POSTING_DUPLICATE',
                            :candidateId,
                            cast(:beforeState as jsonb),
                            jsonb_build_object('status', :action),
                            :reason
                        )
                        """)
                .param("operatorId", operatorId)
                .param("action", action)
                .param("candidateId", candidateId)
                .param("beforeState", before.toString())
                .param("reason", reason)
                .update();
    }

    private void ensureOperator(
            org.springframework.jdbc.core.simple.JdbcClient jdbc
    ) {
        boolean operator = jdbc.sql("""
                        select exists (
                            select 1
                            from users
                            where id = app_current_user_id()
                              and account_role = 'OPERATOR'
                        )
                        """)
                .query(Boolean.class)
                .single();
        if (!operator) {
            throw new ApiException(
                    HttpStatus.FORBIDDEN,
                    "OPERATOR_REQUIRED",
                    "운영자 권한이 필요합니다."
            );
        }
    }

    public record DuplicateCandidateView(
            UUID id,
            String matchKind,
            BigDecimal similarityScore,
            String proposedAction,
            String proposalReason,
            String status,
            PostingSide left,
            PostingSide right,
            OffsetDateTime createdAt
    ) {
    }

    public record PostingSide(
            UUID id,
            String companyName,
            String roleTitle,
            String sourceUrl,
            String lifecycleStatus
    ) {
    }

    private record Candidate(
            UUID id,
            UUID leftId,
            UUID rightId,
            String status
    ) {
    }

    private record AuditRow(
            UUID id,
            String actionKind,
            UUID targetId,
            JsonNode beforeState,
            OffsetDateTime rolledBackAt
    ) {
    }
}
