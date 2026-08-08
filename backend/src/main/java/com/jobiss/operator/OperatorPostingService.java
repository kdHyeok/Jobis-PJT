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
                                left_posting.source_platform as left_platform,
                                left_posting.experience_text as left_experience,
                                left_posting.primary_track as left_track,
                                left_posting.minimum_experience_months as left_minimum_months,
                                left_posting.maximum_experience_months as left_maximum_months,
                                left_posting.last_seen_at as left_last_seen_at,
                                left_posting.closes_at as left_closes_at,
                                (select count(*) from posting_catalog_requirements r where r.posting_catalog_id = left_posting.id) as left_requirement_count,
                                (select count(*) from posting_catalog_observations o where o.posting_catalog_id = left_posting.id) as left_observation_count,
                                right_posting.id as right_id,
                                right_posting.company_name as right_company,
                                right_posting.role_title as right_role,
                                right_posting.source_url as right_url,
                                right_posting.lifecycle_status as right_lifecycle,
                                right_posting.source_platform as right_platform,
                                right_posting.experience_text as right_experience,
                                right_posting.primary_track as right_track,
                                right_posting.minimum_experience_months as right_minimum_months,
                                right_posting.maximum_experience_months as right_maximum_months,
                                right_posting.last_seen_at as right_last_seen_at,
                                right_posting.closes_at as right_closes_at,
                                (select count(*) from posting_catalog_requirements r where r.posting_catalog_id = right_posting.id) as right_requirement_count,
                                (select count(*) from posting_catalog_observations o where o.posting_catalog_id = right_posting.id) as right_observation_count
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
                                    rs.getString("left_lifecycle"),
                                    rs.getString("left_platform"),
                                    rs.getString("left_experience"),
                                    rs.getString("left_track"),
                                    rs.getInt("left_minimum_months"),
                                    (Integer) rs.getObject("left_maximum_months"),
                                    rs.getObject("left_last_seen_at", OffsetDateTime.class),
                                    rs.getObject("left_closes_at", OffsetDateTime.class),
                                    rs.getInt("left_requirement_count"),
                                    rs.getInt("left_observation_count")
                            ),
                            new PostingSide(
                                    rs.getObject("right_id", UUID.class),
                                    rs.getString("right_company"),
                                    rs.getString("right_role"),
                                    rs.getString("right_url"),
                                    rs.getString("right_lifecycle"),
                                    rs.getString("right_platform"),
                                    rs.getString("right_experience"),
                                    rs.getString("right_track"),
                                    rs.getInt("right_minimum_months"),
                                    (Integer) rs.getObject("right_maximum_months"),
                                    rs.getObject("right_last_seen_at", OffsetDateTime.class),
                                    rs.getObject("right_closes_at", OffsetDateTime.class),
                                    rs.getInt("right_requirement_count"),
                                    rs.getInt("right_observation_count")
                            ),
                            rs.getObject("created_at", OffsetDateTime.class)
                    ))
                    .list();
        });
    }

    public List<AuditView> audit(UUID operatorId, int limit) {
        return rls.read(operatorId, jdbc -> {
            ensureOperator(jdbc);
            return jdbc.sql("""
                            select
                                audit.id,
                                audit.action_kind,
                                audit.target_type,
                                audit.target_id,
                                audit.reason,
                                audit.rolled_back_at,
                                audit.created_at,
                                app_user.display_name as operator_name,
                                concat_ws(
                                    ' ↔ ',
                                    concat(left_posting.company_name, ' · ', left_posting.role_title),
                                    concat(right_posting.company_name, ' · ', right_posting.role_title)
                                ) as target_label,
                                candidate.status as candidate_status
                            from operator_action_audit audit
                            join users app_user on app_user.id = audit.operator_user_id
                            left join posting_duplicate_candidates candidate
                              on candidate.id = audit.target_id
                             and audit.target_type = 'POSTING_DUPLICATE'
                            left join posting_catalog left_posting
                              on left_posting.id = candidate.left_posting_id
                            left join posting_catalog right_posting
                              on right_posting.id = candidate.right_posting_id
                            order by audit.created_at desc
                            limit :limit
                            """)
                    .param("limit", limit)
                    .query((rs, rowNum) -> new AuditView(
                            rs.getObject("id", UUID.class),
                            rs.getString("action_kind"),
                            rs.getString("target_type"),
                            rs.getObject("target_id", UUID.class),
                            rs.getString("target_label"),
                            rs.getString("operator_name"),
                            rs.getString("reason"),
                            rs.getObject("rolled_back_at", OffsetDateTime.class),
                            rs.getObject("created_at", OffsetDateTime.class),
                            "MERGE".equals(rs.getString("action_kind"))
                                    && rs.getObject("rolled_back_at") == null
                                    && "MERGED".equals(rs.getString("candidate_status"))
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
            boolean stillMerged = jdbc.sql("""
                            select exists (
                                select 1
                                from posting_duplicate_candidates candidate
                                join posting_catalog duplicate
                                  on duplicate.id = :duplicateId
                                where candidate.id = :candidateId
                                  and candidate.status = 'MERGED'
                                  and duplicate.moderation_status = 'MERGED'
                                  and not duplicate.active
                            )
                            """)
                    .param("candidateId", audit.targetId())
                    .param("duplicateId", duplicate)
                    .query(Boolean.class)
                    .single();
            if (!stillMerged) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "OPERATOR_ACTION_STATE_CHANGED",
                        "병합 이후 공고 상태가 달라져 안전하게 되돌릴 수 없습니다."
                );
            }
            jdbc.sql("""
                            delete from posting_catalog_requirements
                            where posting_catalog_id = :canonicalId
                            """)
                    .param("canonicalId", canonical)
                    .update();
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
                                requirement.catalog_competency_id,
                                requirement.relation_kind,
                                requirement.required_scope,
                                requirement.required_level,
                                requirement.confidence
                            from jsonb_to_recordset(
                                cast(:requirements as jsonb)
                            ) as requirement(
                                catalog_competency_id uuid,
                                relation_kind varchar,
                                required_scope text,
                                required_level integer,
                                confidence numeric
                            )
                            """)
                    .param("canonicalId", canonical)
                    .param(
                            "requirements",
                            audit.beforeState()
                                    .path("canonicalRequirements")
                                    .toString()
                    )
                    .update();
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
                                moderation_status = :moderationStatus,
                                active = :active,
                                updated_at = now()
                            where id = :duplicateId
                            """)
                    .param("duplicateId", duplicate)
                    .param(
                            "moderationStatus",
                            audit.beforeState()
                                    .path("duplicateModerationStatus")
                                    .stringValue("VERIFIED")
                    )
                    .param(
                            "active",
                            audit.beforeState()
                                    .path("duplicateActive")
                                    .booleanValue(true)
                    )
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
        JsonNode canonicalRequirements = jdbc.sql("""
                        select coalesce(
                            jsonb_agg(
                                jsonb_build_object(
                                    'catalog_competency_id', catalog_competency_id,
                                    'relation_kind', relation_kind,
                                    'required_scope', required_scope,
                                    'required_level', required_level,
                                    'confidence', confidence
                                ) order by id
                            ),
                            '[]'::jsonb
                        )::text
                        from posting_catalog_requirements
                        where posting_catalog_id = :canonicalId
                        """)
                .param("canonicalId", canonical)
                .query(String.class)
                .single()
                .transform(objectMapper::readTree);
        before.set("canonicalRequirements", canonicalRequirements);
        CatalogState duplicateState = jdbc.sql("""
                        select moderation_status, active
                        from posting_catalog
                        where id = :duplicateId
                        """)
                .param("duplicateId", duplicate)
                .query((rs, rowNum) -> new CatalogState(
                        rs.getString("moderation_status"),
                        rs.getBoolean("active")
                ))
                .single();
        before.put(
                "duplicateModerationStatus",
                duplicateState.moderationStatus()
        );
        before.put("duplicateActive", duplicateState.active());
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
            String lifecycleStatus,
            String sourcePlatform,
            String experienceText,
            String primaryTrack,
            int minimumExperienceMonths,
            Integer maximumExperienceMonths,
            OffsetDateTime lastSeenAt,
            OffsetDateTime closesAt,
            int requirementCount,
            int observationCount
    ) {
    }

    public record AuditView(
            UUID id,
            String actionKind,
            String targetType,
            UUID targetId,
            String targetLabel,
            String operatorName,
            String reason,
            OffsetDateTime rolledBackAt,
            OffsetDateTime createdAt,
            boolean rollbackable
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

    private record CatalogState(String moderationStatus, boolean active) {
    }
}
