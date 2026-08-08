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
public class OperatorRoleService {

    private final RlsTransactionExecutor rls;

    public OperatorRoleService(RlsTransactionExecutor rls) {
        this.rls = rls;
    }

    public List<RoleCandidateView> list(UUID operatorId, String status) {
        return rls.read(operatorId, jdbc -> {
            ensureOperator(jdbc);
            String normalized = status == null || status.isBlank()
                    ? "PENDING"
                    : status.trim().toUpperCase(Locale.ROOT);
            return jdbc.sql("""
                            select id, analysis_job_id, position_id, source_title,
                                   proposed_family, proposed_specialization,
                                   evidence_ids::text, confidence, status,
                                   selected_canonical_role_id, operator_reason,
                                   created_at, decided_at
                            from role_review_candidates
                            where status = :status
                            order by created_at
                            limit 250
                            """)
                    .param("status", normalized)
                    .query((rs, rowNum) -> new RoleCandidateView(
                            rs.getObject("id", UUID.class),
                            rs.getObject("analysis_job_id", UUID.class),
                            rs.getString("position_id"),
                            rs.getString("source_title"),
                            rs.getString("proposed_family"),
                            rs.getString("proposed_specialization"),
                            rs.getString("evidence_ids"),
                            rs.getBigDecimal("confidence"),
                            rs.getString("status"),
                            rs.getString("selected_canonical_role_id"),
                            rs.getString("operator_reason"),
                            rs.getObject("created_at", OffsetDateTime.class),
                            rs.getObject("decided_at", OffsetDateTime.class)
                    ))
                    .list();
        });
    }

    public void resolve(
            UUID operatorId,
            UUID candidateId,
            String action,
            String canonicalRoleId,
            String reason
    ) {
        rls.write(operatorId, jdbc -> {
            ensureOperator(jdbc);
            String normalized = action.trim().toUpperCase(Locale.ROOT);
            if (("APPROVE_NEW".equals(normalized) || "LINK_EXISTING".equals(normalized))
                    && (canonicalRoleId == null
                    || !canonicalRoleId.matches("^[a-z0-9][a-z0-9._:-]{2,159}$"))) {
                throw new ApiException(
                        HttpStatus.BAD_REQUEST,
                        "ROLE_CANONICAL_ID_REQUIRED",
                        "직무를 승인하거나 연결하려면 canonical role ID가 필요합니다."
                );
            }
            ReviewState before = jdbc.sql("""
                            select status, selected_canonical_role_id
                            from role_review_candidates
                            where id = :candidateId
                            for update
                            """)
                    .param("candidateId", candidateId)
                    .query((rs, rowNum) -> new ReviewState(
                            rs.getString("status"),
                            rs.getString("selected_canonical_role_id")
                    ))
                    .optional()
                    .orElseThrow(() -> new ApiException(
                            HttpStatus.NOT_FOUND,
                            "ROLE_REVIEW_NOT_FOUND",
                            "직무 검토 후보를 찾을 수 없습니다."
                    ));
            if (!List.of("PENDING", "ON_HOLD").contains(before.status())) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "ROLE_REVIEW_ALREADY_RESOLVED",
                        "이미 처리한 직무 후보입니다."
                );
            }
            String nextStatus = switch (normalized) {
                case "APPROVE_NEW" -> "APPROVED_STAGED";
                case "LINK_EXISTING" -> "LINKED";
                case "REJECT" -> "REJECTED";
                case "HOLD" -> "ON_HOLD";
                default -> throw new ApiException(
                        HttpStatus.BAD_REQUEST,
                        "ROLE_REVIEW_ACTION_INVALID",
                        "지원하지 않는 직무 검토 판정입니다."
                );
            };
            String selected = List.of("APPROVE_NEW", "LINK_EXISTING").contains(normalized)
                    ? canonicalRoleId
                    : null;
            jdbc.sql("""
                            update role_review_candidates
                            set status = :status,
                                selected_canonical_role_id = :canonicalRoleId,
                                operator_user_id = :operatorId,
                                operator_reason = :reason,
                                decided_at = case when :status = 'ON_HOLD' then null else now() end
                            where id = :candidateId
                            """)
                    .param("status", nextStatus)
                    .param("canonicalRoleId", selected)
                    .param("operatorId", operatorId)
                    .param("reason", reason.trim())
                    .param("candidateId", candidateId)
                    .update();
            jdbc.sql("""
                            insert into role_review_actions (
                                candidate_id, operator_user_id, action,
                                before_state, after_state, reason
                            ) values (
                                :candidateId, :operatorId, :action,
                                jsonb_build_object('status', :beforeStatus, 'canonicalRoleId', :beforeKey),
                                jsonb_build_object('status', :afterStatus, 'canonicalRoleId', :afterKey),
                                :reason
                            )
                            """)
                    .param("candidateId", candidateId)
                    .param("operatorId", operatorId)
                    .param("action", normalized)
                    .param("beforeStatus", before.status())
                    .param("beforeKey", before.canonicalRoleId())
                    .param("afterStatus", nextStatus)
                    .param("afterKey", selected)
                    .param("reason", reason.trim())
                    .update();
            return null;
        });
    }

    public RoleReleaseView publish(UUID operatorId, String notes) {
        return rls.write(operatorId, jdbc -> {
            ensureOperator(jdbc);
            long version = jdbc.sql("select coalesce(max(version_number), 0) + 1 from role_catalog_releases")
                    .query(Long.class).single();
            List<RolePublishRow> staged = jdbc.sql("""
                            select id, selected_canonical_role_id, proposed_family, proposed_specialization
                            from role_review_candidates
                            where status = 'APPROVED_STAGED'
                            order by created_at
                            for update
                            """)
                    .query((rs, rowNum) -> new RolePublishRow(
                            rs.getObject("id", UUID.class), rs.getString("selected_canonical_role_id"),
                            rs.getString("proposed_family"), rs.getString("proposed_specialization")
                    )).list();
            if (staged.isEmpty()) {
                throw new ApiException(HttpStatus.CONFLICT, "NO_STAGED_ROLES", "발행 대기 중인 신규 직무가 없습니다.");
            }
            for (RolePublishRow item : staged) {
                jdbc.sql("""
                                insert into approved_role_catalog (
                                    canonical_role_id, family, specialization, catalog_version,
                                    source_candidate_id, published_by
                                ) values (
                                    :canonicalRoleId, :family, :specialization, :version,
                                    :candidateId, :operatorId
                                )
                                on conflict (canonical_role_id) do update
                                set family = excluded.family, specialization = excluded.specialization,
                                    catalog_version = excluded.catalog_version,
                                    source_candidate_id = excluded.source_candidate_id,
                                    active = true, published_at = now(), published_by = excluded.published_by
                                """)
                        .param("canonicalRoleId", item.canonicalRoleId())
                        .param("family", item.family()).param("specialization", item.specialization())
                        .param("version", version).param("candidateId", item.id())
                        .param("operatorId", operatorId).update();
            }
            jdbc.sql("""
                            update role_review_candidates
                            set status = 'PUBLISHED', updated_at = now()
                            where id in (:ids)
                            """).param("ids", staged.stream().map(RolePublishRow::id).toList()).update();
            UUID releaseId = jdbc.sql("""
                            insert into role_catalog_releases (
                                version_number, published_count, notes, published_by
                            ) values (:version, :count, :notes, :operatorId) returning id
                            """).param("version", version).param("count", staged.size())
                    .param("notes", notes.trim()).param("operatorId", operatorId)
                    .query(UUID.class).single();
            return new RoleReleaseView(releaseId, version, staged.size());
        });
    }

    private void ensureOperator(org.springframework.jdbc.core.simple.JdbcClient jdbc) {
        boolean operator = jdbc.sql("""
                        select exists (
                            select 1 from users
                            where id = app_current_user_id() and account_role = 'OPERATOR'
                        )
                        """).query(Boolean.class).single();
        if (!operator) {
            throw new ApiException(HttpStatus.FORBIDDEN, "OPERATOR_REQUIRED", "운영자 권한이 필요합니다.");
        }
    }

    public record RoleCandidateView(
            UUID id,
            UUID analysisJobId,
            String positionId,
            String sourceTitle,
            String proposedFamily,
            String proposedSpecialization,
            String evidenceIds,
            BigDecimal confidence,
            String status,
            String selectedCanonicalRoleId,
            String operatorReason,
            OffsetDateTime createdAt,
            OffsetDateTime decidedAt
    ) {
    }

    private record ReviewState(String status, String canonicalRoleId) {
    }

    private record RolePublishRow(UUID id, String canonicalRoleId, String family, String specialization) {}
    public record RoleReleaseView(UUID id, long versionNumber, int publishedCount) {}
}
