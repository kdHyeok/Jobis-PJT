package com.jobiss.analysis.v3;

import com.jobiss.common.ApiException;
import com.jobiss.db.RlsTransactionExecutor;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

@Service
public class V3AtomicMigrationService {

    private final RlsTransactionExecutor rls;

    public V3AtomicMigrationService(RlsTransactionExecutor rls) {
        this.rls = rls;
    }

    public List<MigrationCandidateView> candidates(UUID userId, String canonicalKey) {
        String filter = canonicalKey == null ? "" : canonicalKey.trim();
        return rls.read(userId, jdbc -> jdbc.sql("""
                        select
                            candidate.id,
                            candidate.atomic_capability_id,
                            atomic.canonical_key,
                            atomic.title,
                            atomic.scope_definition,
                            candidate.legacy_competency_id,
                            legacy.title as legacy_title,
                            candidate.legacy_progress_status,
                            candidate.legacy_verified_level,
                            candidate.confidence,
                            candidate.reason,
                            candidate.status,
                            candidate.created_at,
                            candidate.decided_at
                        from user_atomic_migration_candidates candidate
                        join user_atomic_capabilities atomic
                          on atomic.id = candidate.atomic_capability_id
                        join user_competencies legacy
                          on legacy.id = candidate.legacy_competency_id
                        where (:canonicalKey = '' or atomic.canonical_key = :canonicalKey)
                        order by candidate.created_at desc
                        """)
                .param("canonicalKey", filter)
                .query((rs, rowNum) -> new MigrationCandidateView(
                        rs.getObject("id", UUID.class),
                        rs.getObject("atomic_capability_id", UUID.class),
                        rs.getString("canonical_key"),
                        rs.getString("title"),
                        rs.getString("scope_definition"),
                        rs.getObject("legacy_competency_id", UUID.class),
                        rs.getString("legacy_title"),
                        rs.getString("legacy_progress_status"),
                        rs.getInt("legacy_verified_level"),
                        rs.getBigDecimal("confidence"),
                        rs.getString("reason"),
                        rs.getString("status"),
                        rs.getObject("created_at", OffsetDateTime.class),
                        rs.getObject("decided_at", OffsetDateTime.class)
                ))
                .list());
    }

    public MigrationCandidateView resolve(
            UUID userId,
            UUID candidateId,
            boolean confirmed
    ) {
        return rls.write(userId, jdbc -> {
            CandidateTarget target = jdbc.sql("""
                            select
                                id,
                                atomic_capability_id,
                                legacy_competency_id,
                                status
                            from user_atomic_migration_candidates
                            where id = :candidateId
                            for update
                            """)
                    .param("candidateId", candidateId)
                    .query((rs, rowNum) -> new CandidateTarget(
                            rs.getObject("id", UUID.class),
                            rs.getObject("atomic_capability_id", UUID.class),
                            rs.getObject("legacy_competency_id", UUID.class),
                            rs.getString("status")
                    ))
                    .optional()
                    .orElseThrow(() -> new ApiException(
                            HttpStatus.NOT_FOUND,
                            "ATOMIC_MIGRATION_CANDIDATE_NOT_FOUND",
                            "기존 역량 연결 후보를 찾을 수 없습니다."
                    ));
            if (!"PENDING_REVIEW".equals(target.status())) {
                return candidate(jdbc, candidateId);
            }
            jdbc.sql("""
                            update user_atomic_migration_candidates
                            set status = :status, decided_at = now()
                            where id = :candidateId
                            """)
                    .param("status", confirmed ? "CONFIRMED" : "REJECTED")
                    .param("candidateId", candidateId)
                    .update();
            if (confirmed) {
                String previous = jdbc.sql("""
                                select progress_state
                                from user_atomic_capabilities
                                where id = :capabilityId
                                for update
                                """)
                        .param("capabilityId", target.atomicCapabilityId())
                        .query(String.class)
                        .single();
                String next = switch (previous) {
                    case "NOT_STARTED", "CLAIMED" -> "EVIDENCED";
                    default -> previous;
                };
                if (!next.equals(previous)) {
                    jdbc.sql("""
                                    update user_atomic_capabilities
                                    set progress_state = :nextState
                                    where id = :capabilityId
                                    """)
                            .param("nextState", next)
                            .param("capabilityId", target.atomicCapabilityId())
                            .update();
                    jdbc.sql("""
                                    insert into user_atomic_capability_events (
                                        user_id,
                                        atomic_capability_id,
                                        from_state,
                                        to_state,
                                        event_type,
                                        source_ref,
                                        evidence
                                    )
                                    values (
                                        :userId,
                                        :capabilityId,
                                        :fromState,
                                        :toState,
                                        'MIGRATION_REVIEW',
                                        :sourceRef,
                                        jsonb_build_object(
                                            'legacyCompetencyId', :legacyCompetencyId,
                                            'candidateId', :candidateId
                                        )
                                    )
                                    """)
                            .param("userId", userId)
                            .param("capabilityId", target.atomicCapabilityId())
                            .param("fromState", previous)
                            .param("toState", next)
                            .param("sourceRef", "legacy-competency:" + target.legacyCompetencyId())
                            .param("legacyCompetencyId", target.legacyCompetencyId())
                            .param("candidateId", candidateId)
                            .update();
                }
            }
            return candidate(jdbc, candidateId);
        });
    }

    private MigrationCandidateView candidate(JdbcClient jdbc, UUID candidateId) {
        return jdbc.sql("""
                        select
                            candidate.id,
                            candidate.atomic_capability_id,
                            atomic.canonical_key,
                            atomic.title,
                            atomic.scope_definition,
                            candidate.legacy_competency_id,
                            legacy.title as legacy_title,
                            candidate.legacy_progress_status,
                            candidate.legacy_verified_level,
                            candidate.confidence,
                            candidate.reason,
                            candidate.status,
                            candidate.created_at,
                            candidate.decided_at
                        from user_atomic_migration_candidates candidate
                        join user_atomic_capabilities atomic
                          on atomic.id = candidate.atomic_capability_id
                        join user_competencies legacy
                          on legacy.id = candidate.legacy_competency_id
                        where candidate.id = :candidateId
                        """)
                .param("candidateId", candidateId)
                .query((rs, rowNum) -> new MigrationCandidateView(
                        rs.getObject("id", UUID.class),
                        rs.getObject("atomic_capability_id", UUID.class),
                        rs.getString("canonical_key"),
                        rs.getString("title"),
                        rs.getString("scope_definition"),
                        rs.getObject("legacy_competency_id", UUID.class),
                        rs.getString("legacy_title"),
                        rs.getString("legacy_progress_status"),
                        rs.getInt("legacy_verified_level"),
                        rs.getBigDecimal("confidence"),
                        rs.getString("reason"),
                        rs.getString("status"),
                        rs.getObject("created_at", OffsetDateTime.class),
                        rs.getObject("decided_at", OffsetDateTime.class)
                ))
                .optional()
                .orElseThrow();
    }

    public record MigrationCandidateView(
            UUID id,
            UUID atomicCapabilityId,
            String canonicalKey,
            String title,
            String scopeDefinition,
            UUID legacyCompetencyId,
            String legacyTitle,
            String legacyProgressStatus,
            int legacyVerifiedLevel,
            java.math.BigDecimal confidence,
            String reason,
            String status,
            OffsetDateTime createdAt,
            OffsetDateTime decidedAt
    ) {
    }

    private record CandidateTarget(
            UUID id,
            UUID atomicCapabilityId,
            UUID legacyCompetencyId,
            String status
    ) {
    }
}
