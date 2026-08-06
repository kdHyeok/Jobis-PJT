package com.jobiss.operator;

import com.jobiss.common.ApiException;
import com.jobiss.db.RlsTransactionExecutor;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Locale;
import java.util.UUID;

@Service
public class OperatorCapabilityService {

    private final RlsTransactionExecutor rls;

    public OperatorCapabilityService(RlsTransactionExecutor rls) {
        this.rls = rls;
    }

    public List<CandidateView> list(UUID operatorId, String status) {
        return rls.read(operatorId, jdbc -> {
            ensureOperator(jdbc);
            String normalized = status == null || status.isBlank() ? "PENDING" : status.trim().toUpperCase(Locale.ROOT);
            return jdbc.sql("""
                            select id, analysis_job_id, requirement_id, candidate_id, decision_kind,
                                   display_name, proposed_kind, scope_definition, aliases::text,
                                   evidence_ids::text, match_candidates::text, confidence, reason,
                                   status, selected_canonical_key, operator_reason, created_at, decided_at
                            from capability_review_candidates
                            where status = :status
                            order by created_at
                            limit 250
                            """)
                    .param("status", normalized)
                    .query((rs, rowNum) -> new CandidateView(
                            rs.getObject("id", UUID.class),
                            rs.getObject("analysis_job_id", UUID.class),
                            rs.getString("requirement_id"),
                            rs.getString("candidate_id"),
                            rs.getString("decision_kind"),
                            rs.getString("display_name"),
                            rs.getString("proposed_kind"),
                            rs.getString("scope_definition"),
                            rs.getString("aliases"),
                            rs.getString("evidence_ids"),
                            rs.getString("match_candidates"),
                            rs.getBigDecimal("confidence"),
                            rs.getString("reason"),
                            rs.getString("status"),
                            rs.getString("selected_canonical_key"),
                            rs.getString("operator_reason"),
                            rs.getObject("created_at", OffsetDateTime.class),
                            rs.getObject("decided_at", OffsetDateTime.class)
                    ))
                    .list();
        });
    }

    public void resolve(UUID operatorId, UUID candidateId, String action, String canonicalKey, String reason) {
        rls.write(operatorId, jdbc -> {
            ensureOperator(jdbc);
            String normalized = action.trim().toUpperCase(Locale.ROOT);
            if (("APPROVE_NEW".equals(normalized) || "LINK_EXISTING".equals(normalized))
                    && (canonicalKey == null || !canonicalKey.matches("^[a-z0-9][a-z0-9._:-]{2,159}$"))) {
                throw new ApiException(HttpStatus.BAD_REQUEST, "CAPABILITY_CANONICAL_KEY_REQUIRED", "승인하거나 기존 역량에 연결하려면 canonical key가 필요합니다.");
            }
            ReviewState before = jdbc.sql("""
                            select status, selected_canonical_key
                            from capability_review_candidates
                            where id = :candidateId
                            for update
                            """)
                    .param("candidateId", candidateId)
                    .query((rs, rowNum) -> new ReviewState(rs.getString("status"), rs.getString("selected_canonical_key")))
                    .optional()
                    .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "CAPABILITY_REVIEW_NOT_FOUND", "역량 검토 후보를 찾을 수 없습니다."));
            if (!List.of("PENDING", "ON_HOLD").contains(before.status())) {
                throw new ApiException(HttpStatus.CONFLICT, "CAPABILITY_REVIEW_ALREADY_RESOLVED", "이미 최종 처리된 역량 후보입니다.");
            }
            String nextStatus = switch (normalized) {
                case "APPROVE_NEW" -> "APPROVED_STAGED";
                case "LINK_EXISTING" -> "LINKED";
                case "SPLIT" -> "NEEDS_SPLIT";
                case "REJECT" -> "REJECTED";
                case "HOLD" -> "ON_HOLD";
                default -> throw new ApiException(HttpStatus.BAD_REQUEST, "CAPABILITY_REVIEW_ACTION_INVALID", "지원하지 않는 역량 검토 판정입니다.");
            };
            jdbc.sql("""
                            update capability_review_candidates
                            set status = :status,
                                selected_canonical_key = :canonicalKey,
                                operator_user_id = :operatorId,
                                operator_reason = :reason,
                                decided_at = case when :status = 'ON_HOLD' then null else now() end
                            where id = :candidateId
                            """)
                    .param("status", nextStatus)
                    .param("canonicalKey", ("APPROVE_NEW".equals(normalized) || "LINK_EXISTING".equals(normalized)) ? canonicalKey : null)
                    .param("operatorId", operatorId)
                    .param("reason", reason.trim())
                    .param("candidateId", candidateId)
                    .update();
            jdbc.sql("""
                            insert into capability_review_actions (
                                candidate_id, operator_user_id, action, before_state, after_state, reason
                            ) values (
                                :candidateId, :operatorId, :action,
                                jsonb_build_object('status', :beforeStatus, 'canonicalKey', :beforeKey),
                                jsonb_build_object('status', :afterStatus, 'canonicalKey', :afterKey),
                                :reason
                            )
                            """)
                    .param("candidateId", candidateId)
                    .param("operatorId", operatorId)
                    .param("action", normalized)
                    .param("beforeStatus", before.status())
                    .param("beforeKey", before.canonicalKey())
                    .param("afterStatus", nextStatus)
                    .param("afterKey", canonicalKey)
                    .param("reason", reason.trim())
                    .update();
            return null;
        });
    }

    public ReleaseView publish(UUID operatorId, String graphVersion, String notes) {
        return rls.write(operatorId, jdbc -> {
            ensureOperator(jdbc);
            if (!graphVersion.matches("^\\d+\\.\\d+\\.\\d+(?:-[0-9A-Za-z.-]+)?$")) {
                throw new ApiException(HttpStatus.BAD_REQUEST, "GRAPH_VERSION_INVALID", "그래프 버전은 SemVer 형식이어야 합니다.");
            }
            int staged = jdbc.sql("select count(*) from capability_review_candidates where status = 'APPROVED_STAGED'")
                    .query(Integer.class)
                    .single();
            if (staged == 0) {
                throw new ApiException(HttpStatus.CONFLICT, "CAPABILITY_RELEASE_EMPTY", "발행할 승인 대기 역량이 없습니다.");
            }
            UUID releaseId = jdbc.sql("""
                            insert into capability_graph_releases (
                                graph_version, candidate_snapshot, published_by, release_notes
                            )
                            select :graphVersion,
                                   coalesce(jsonb_agg(to_jsonb(candidate) order by candidate.created_at), '[]'::jsonb),
                                   :operatorId,
                                   :notes
                            from capability_review_candidates candidate
                            where candidate.status = 'APPROVED_STAGED'
                            returning id
                            """)
                    .param("graphVersion", graphVersion)
                    .param("operatorId", operatorId)
                    .param("notes", notes.trim())
                    .query(UUID.class)
                    .single();
            int published = jdbc.sql("""
                            update capability_review_candidates
                            set status = 'PUBLISHED'
                            where status = 'APPROVED_STAGED'
                            """).update();
            return new ReleaseView(releaseId, graphVersion, published);
        });
    }

    private void ensureOperator(org.springframework.jdbc.core.simple.JdbcClient jdbc) {
        boolean operator = jdbc.sql("select exists (select 1 from users where id = app_current_user_id() and account_role = 'OPERATOR')")
                .query(Boolean.class).single();
        if (!operator) throw new ApiException(HttpStatus.FORBIDDEN, "OPERATOR_REQUIRED", "운영자 권한이 필요합니다.");
    }

    public record CandidateView(UUID id, UUID analysisJobId, String requirementId, String candidateId,
                                String decisionKind, String displayName, String proposedKind, String scopeDefinition,
                                String aliases, String evidenceIds, String matchCandidates, BigDecimal confidence,
                                String reason, String status, String selectedCanonicalKey, String operatorReason,
                                OffsetDateTime createdAt, OffsetDateTime decidedAt) {}
    public record ReleaseView(UUID id, String graphVersion, int publishedCandidates) {}
    private record ReviewState(String status, String canonicalKey) {}
}
