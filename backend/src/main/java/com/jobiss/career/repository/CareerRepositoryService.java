package com.jobiss.career.repository;

import com.jobiss.analysis.AiUsageLimitService;
import com.jobiss.common.ApiException;
import com.jobiss.db.RlsTransactionExecutor;
import com.jobiss.security.SensitiveTextCipher;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

@Service
public class CareerRepositoryService {

    private final RlsTransactionExecutor rls;
    private final ObjectMapper objectMapper;
    private final AiUsageLimitService usageLimit;
    private final SensitiveTextCipher sensitiveText;

    public CareerRepositoryService(
            RlsTransactionExecutor rls,
            ObjectMapper objectMapper,
            AiUsageLimitService usageLimit,
            SensitiveTextCipher sensitiveText
    ) {
        this.rls = rls;
        this.objectMapper = objectMapper;
        this.usageLimit = usageLimit;
        this.sensitiveText = sensitiveText;
    }

    public SourceDetail create(UUID userId, CreateSource command) {
        usageLimit.consume(userId, AiUsageLimitService.Kind.CAREER);
        return rls.write(userId, jdbc -> {
            UUID id = jdbc.sql("""
                            insert into career_sources (
                                user_id,
                                source_type,
                                title,
                                source_url,
                                raw_text
                            )
                            values (
                                :userId,
                                :sourceType,
                                :title,
                                :sourceUrl,
                                :rawText
                            )
                            returning id
                            """)
                    .param("userId", userId)
                    .param("sourceType", command.sourceType())
                    .param("title", command.title().trim())
                    .param("sourceUrl", blankToNull(command.sourceUrl()))
                    .param("rawText", sensitiveText.encrypt(command.rawText().trim()))
                    .query(UUID.class)
                    .single();
            return loadSource(jdbc, id);
        });
    }

    public List<SourceSummary> listSources(UUID userId, boolean archived) {
        return rls.read(userId, jdbc -> jdbc.sql("""
                        select
                            s.id,
                            s.source_type,
                            s.title,
                            s.source_url,
                            s.status,
                            s.stage,
                            s.stage_message,
                            s.summary,
                            s.attempt_count,
                            s.error_message,
                            s.archived_at,
                            s.created_at,
                            s.completed_at,
                            count(f.id) filter (
                                where f.review_status = 'CONFIRMED'
                                  and f.archived_at is null
                            ) as confirmed_count,
                            count(f.id) filter (
                                where f.review_status = 'SUGGESTED'
                                  and f.archived_at is null
                            ) as suggested_count
                        from career_sources s
                        left join career_fragments f on f.source_id = s.id
                        where ((:archived and s.archived_at is not null)
                               or (not :archived and s.archived_at is null))
                        group by s.id
                        order by s.created_at desc
                        limit 100
                        """)
                .param("archived", archived)
                .query(CareerRepositoryService::mapSourceSummary)
                .list());
    }

    public SourceDetail getSource(UUID userId, UUID sourceId) {
        return rls.read(userId, jdbc -> loadSource(jdbc, sourceId));
    }

    public void retrySource(UUID userId, UUID sourceId) {
        usageLimit.consume(userId, AiUsageLimitService.Kind.CAREER);
        rls.write(userId, jdbc -> {
            int updated = jdbc.sql("""
                            update career_sources
                            set
                                status = 'QUEUED',
                                stage = 'QUEUED',
                                stage_message = '자료 분석 재시도 대기 중',
                                worker_id = null,
                                locked_until = null,
                                error_code = null,
                                error_message = null,
                                completed_at = null
                            where id = :sourceId
                              and status in ('FAILED', 'CANCELLED')
                              and attempt_count < 3
                            """)
                    .param("sourceId", sourceId)
                    .update();
            if (updated == 0) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "CAREER_SOURCE_NOT_RETRYABLE",
                        "현재 상태에서는 자료 분석을 재시도할 수 없습니다."
                );
            }
            jdbc.sql("select requeue_career_source(:sourceId, :userId)")
                    .param("sourceId", sourceId)
                    .param("userId", userId)
                    .query(Object.class)
                    .optional();
            return null;
        });
    }

    public void cancelSource(UUID userId, UUID sourceId) {
        rls.write(userId, jdbc -> {
            int updated = jdbc.sql("""
                            update career_sources
                            set status = 'CANCELLED',
                                stage = 'CANCELLED',
                                stage_message = '자료 분석을 취소했어요',
                                completed_at = now(),
                                locked_until = null,
                                worker_id = null
                            where id = :sourceId
                              and status in ('QUEUED', 'RUNNING')
                            """)
                    .param("sourceId", sourceId)
                    .update();
            if (updated == 0) {
                throw new ApiException(HttpStatus.CONFLICT, "CAREER_SOURCE_NOT_CANCELLABLE", "진행 중인 자료만 취소할 수 있습니다.");
            }
            jdbc.sql("select finish_career_source(:sourceId, :userId)")
                    .param("sourceId", sourceId)
                    .param("userId", userId)
                    .query(Object.class)
                    .optional();
            return null;
        });
    }

    public void confirmSource(UUID userId, UUID sourceId, List<UUID> fragmentIds) {
        if (fragmentIds == null || fragmentIds.isEmpty()) {
            throw new ApiException(
                    HttpStatus.BAD_REQUEST,
                    "CAREER_FRAGMENT_REQUIRED",
                    "저장할 커리어 조각을 하나 이상 선택해 주세요."
            );
        }
        rls.write(userId, jdbc -> {
            int expected = fragmentIds.size();
            long owned = jdbc.sql("""
                            select count(*)
                            from career_fragments
                            where source_id = :sourceId
                              and id in (:fragmentIds)
                              and archived_at is null
                            """)
                    .param("sourceId", sourceId)
                    .param("fragmentIds", fragmentIds)
                    .query(Long.class)
                    .single();
            if (owned != expected) {
                throw new ApiException(
                        HttpStatus.BAD_REQUEST,
                        "CAREER_FRAGMENT_MISMATCH",
                        "선택한 조각 중 이 자료에 속하지 않는 항목이 있습니다."
                );
            }
            jdbc.sql("""
                            update career_fragments
                            set review_status = case
                                when id in (:fragmentIds) then 'CONFIRMED'
                                else 'REJECTED'
                            end
                            where source_id = :sourceId
                              and review_status = 'SUGGESTED'
                            """)
                    .param("fragmentIds", fragmentIds)
                    .param("sourceId", sourceId)
                    .update();
            int updated = jdbc.sql("""
                            update career_sources
                            set status = 'CONFIRMED'
                            where id = :sourceId
                              and status in ('REVIEW_READY', 'CONFIRMED')
                            """)
                    .param("sourceId", sourceId)
                    .update();
            if (updated == 0) {
                throw sourceNotFound();
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
                                'CAREER_SOURCE_CONFIRMED',
                                '커리어 조각을 저장했어요',
                                :body,
                                jsonb_build_object('careerSourceId', cast(:sourceId as text))
                            )
                            """)
                    .param("userId", userId)
                    .param("body", expected + "개의 조각이 이후 대화와 공고 분석에 반영됩니다.")
                    .param("sourceId", sourceId)
                    .update();
            return null;
        });
    }

    public FragmentPage searchFragments(
            UUID userId,
            String query,
            String kind,
            String status,
            String sort,
            String direction,
            boolean archived,
            int page,
            int size
    ) {
        int safePage = Math.max(0, page);
        int safeSize = Math.max(1, Math.min(size, 100));
        String orderColumn = switch (sort) {
            case "title" -> "f.title";
            case "kind" -> "f.kind";
            case "updatedAt" -> "f.updated_at";
            default -> "f.created_at";
        };
        String orderDirection = "asc".equalsIgnoreCase(direction) ? "asc" : "desc";
        String normalizedQuery = query == null ? "" : query.trim();
        String normalizedKind = kind == null ? "" : kind.trim().toUpperCase();
        String normalizedStatus = status == null || status.isBlank()
                ? "CONFIRMED"
                : status.trim().toUpperCase();

        return rls.read(userId, jdbc -> {
            String filter = """
                    from career_fragments f
                    join career_sources s on s.id = f.source_id
                    where ((:archived and f.archived_at is not null)
                           or (not :archived and f.archived_at is null))
                      and (:query = ''
                           or f.title ilike '%' || :query || '%'
                           or f.description ilike '%' || :query || '%')
                      and (:kind = '' or f.kind = :kind)
                      and (:status = '' or f.review_status = :status)
                    """;
            long total = jdbc.sql("select count(*) " + filter)
                    .param("archived", archived)
                    .param("query", normalizedQuery)
                    .param("kind", normalizedKind)
                    .param("status", normalizedStatus)
                    .query(Long.class)
                    .single();
            String sql = """
                    select
                        f.id,
                        f.source_id,
                        s.title as source_title,
                        f.kind,
                        f.title,
                        f.description,
                        f.canonical_key,
                        f.detail::text,
                        f.review_status,
                        f.archived_at,
                        f.created_at,
                        f.updated_at
                    """ + filter + " order by " + orderColumn + " " + orderDirection
                    + " nulls last limit :limit offset :offset";
            List<FragmentView> items = jdbc.sql(sql)
                    .param("archived", archived)
                    .param("query", normalizedQuery)
                    .param("kind", normalizedKind)
                    .param("status", normalizedStatus)
                    .param("limit", safeSize)
                    .param("offset", safePage * safeSize)
                    .query((rs, rowNum) -> mapFragment(rs))
                    .list();
            return new FragmentPage(items, safePage, safeSize, total);
        });
    }

    public FragmentView updateFragment(
            UUID userId,
            UUID fragmentId,
            UpdateFragment command
    ) {
        return rls.write(userId, jdbc -> {
            FragmentView existing = loadFragment(jdbc, fragmentId);
            JsonNode requestedDetail = command.detail() == null
                    ? objectMapper.createObjectNode()
                    : command.detail();
            if ("CONFIRMED".equals(existing.reviewStatus())
                    && (!existing.kind().equals(command.kind())
                    || !java.util.Objects.equals(existing.canonicalKey(), blankToNull(command.canonicalKey()))
                    || !existing.detail().equals(requestedDetail))) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "CAREER_FRAGMENT_IDENTITY_IMMUTABLE",
                        "확정된 조각의 종류·역량 식별자·검증 범위는 직접 바꿀 수 없습니다. 제목과 설명만 수정하거나 새 자료로 다시 분석해 주세요."
                );
            }
            int updated = jdbc.sql("""
                            update career_fragments
                            set
                                kind = :kind,
                                title = :title,
                                description = :description,
                                canonical_key = :canonicalKey,
                                detail = cast(:detail as jsonb)
                            where id = :fragmentId
                              and archived_at is null
                            """)
                    .param("kind", command.kind())
                    .param("title", command.title().trim())
                    .param("description", command.description().trim())
                    .param("canonicalKey", blankToNull(command.canonicalKey()))
                    .param("detail", objectMapper.writeValueAsString(requestedDetail))
                    .param("fragmentId", fragmentId)
                    .update();
            if (updated == 0) {
                throw fragmentNotFound();
            }
            return loadFragment(jdbc, fragmentId);
        });
    }

    public FragmentView addSuggestedFragment(
            UUID userId,
            UUID sourceId,
            UpdateFragment command
    ) {
        return rls.write(userId, jdbc -> {
            boolean reviewable = jdbc.sql("""
                            select exists (
                                select 1
                                from career_sources
                                where id = :sourceId
                                  and status = 'REVIEW_READY'
                                  and archived_at is null
                            )
                            """)
                    .param("sourceId", sourceId)
                    .query(Boolean.class)
                    .single();
            if (!reviewable) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "CAREER_SOURCE_NOT_REVIEWABLE",
                        "검토 중인 자료에만 조각을 직접 추가할 수 있습니다."
                );
            }
            UUID fragmentId = jdbc.sql("""
                            insert into career_fragments (
                                user_id,
                                source_id,
                                kind,
                                title,
                                description,
                                canonical_key,
                                detail,
                                review_status
                            )
                            values (
                                :userId,
                                :sourceId,
                                :kind,
                                :title,
                                :description,
                                null,
                                cast(:detail as jsonb),
                                'SUGGESTED'
                            )
                            returning id
                            """)
                    .param("userId", userId)
                    .param("sourceId", sourceId)
                    .param("kind", command.kind())
                    .param("title", command.title().trim())
                    .param("description", command.description().trim())
                    .param(
                            "detail",
                            objectMapper.writeValueAsString(
                                    command.detail() == null
                                            ? objectMapper.createObjectNode()
                                            : command.detail()
                            )
                    )
                    .query(UUID.class)
                    .single();
            return loadFragment(jdbc, fragmentId);
        });
    }

    public MergePreview previewMerge(UUID userId, List<UUID> fragmentIds) {
        return rls.read(userId, jdbc -> inspectMerge(jdbc, fragmentIds));
    }

    public MergeResult mergeFragments(
            UUID userId,
            List<UUID> fragmentIds,
            UpdateFragment command
    ) {
        if (fragmentIds == null || fragmentIds.size() < 2) {
            throw new ApiException(
                    HttpStatus.BAD_REQUEST,
                    "CAREER_FRAGMENT_MERGE_REQUIRES_TWO",
                    "병합할 조각을 두 개 이상 선택해 주세요."
            );
        }
        return rls.write(userId, jdbc -> {
            MergePreview preview = inspectMerge(jdbc, fragmentIds);
            if (!preview.compatible()) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "CAREER_FRAGMENT_MERGE_INCOMPATIBLE",
                        preview.reason()
                );
            }
            UUID targetId = fragmentIds.get(0);
            FragmentView target = loadFragment(jdbc, targetId);
            if (!target.kind().equals(command.kind())
                    || !java.util.Objects.equals(target.canonicalKey(), blankToNull(command.canonicalKey()))
                    || !target.detail().equals(command.detail() == null ? objectMapper.createObjectNode() : command.detail())) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "CAREER_FRAGMENT_MERGE_IDENTITY_CHANGED",
                        "병합 과정에서는 조각의 종류·역량 식별자·검증 범위를 바꿀 수 없습니다."
                );
            }
            UUID mergeEventId = jdbc.sql("""
                            insert into career_fragment_merge_events (
                                user_id, target_fragment_id, fragment_ids, before_snapshot
                            )
                            select
                                :userId,
                                :targetId,
                                array_agg(fragment.id order by fragment.created_at),
                                jsonb_agg(to_jsonb(fragment) order by fragment.created_at)
                            from career_fragments fragment
                            where fragment.id in (:fragmentIds)
                            returning id
                            """)
                    .param("userId", userId)
                    .param("targetId", targetId)
                    .param("fragmentIds", fragmentIds)
                    .query(UUID.class)
                    .single();
            jdbc.sql("""
                            update career_fragments
                            set
                                title = :title,
                                description = :description,
                                review_status = 'CONFIRMED'
                            where id = :targetId
                            """)
                    .param("title", command.title().trim())
                    .param("description", command.description().trim())
                    .param("targetId", targetId)
                    .update();
            jdbc.sql("""
                            update career_fragments
                            set archived_at = now()
                            where id in (:fragmentIds)
                              and id <> :targetId
                            """)
                    .param("fragmentIds", fragmentIds)
                    .param("targetId", targetId)
                    .update();
            return new MergeResult(loadFragment(jdbc, targetId), mergeEventId);
        });
    }

    public FragmentView undoMerge(UUID userId, UUID mergeEventId) {
        return rls.write(userId, jdbc -> {
            MergeEvent event = jdbc.sql("""
                            select target_fragment_id, before_snapshot::text
                            from career_fragment_merge_events
                            where id = :eventId
                              and undone_at is null
                            for update
                            """)
                    .param("eventId", mergeEventId)
                    .query((rs, rowNum) -> new MergeEvent(
                            rs.getObject("target_fragment_id", UUID.class),
                            rs.getString("before_snapshot")
                    ))
                    .optional()
                    .orElseThrow(() -> new ApiException(
                            HttpStatus.CONFLICT,
                            "CAREER_FRAGMENT_MERGE_NOT_UNDOABLE",
                            "이미 되돌렸거나 찾을 수 없는 병합입니다."
                    ));
            jdbc.sql("""
                            update career_fragments fragment
                            set
                                source_id = snapshot.source_id,
                                kind = snapshot.kind,
                                title = snapshot.title,
                                description = snapshot.description,
                                canonical_key = snapshot.canonical_key,
                                detail = snapshot.detail,
                                review_status = snapshot.review_status,
                                archived_at = snapshot.archived_at,
                                updated_at = snapshot.updated_at
                            from jsonb_to_recordset(cast(:snapshot as jsonb)) as snapshot(
                                id uuid,
                                source_id uuid,
                                kind varchar,
                                title varchar,
                                description text,
                                canonical_key varchar,
                                detail jsonb,
                                review_status varchar,
                                archived_at timestamptz,
                                updated_at timestamptz
                            )
                            where fragment.id = snapshot.id
                            """)
                    .param("snapshot", event.beforeSnapshot())
                    .update();
            jdbc.sql("""
                            update career_fragment_merge_events
                            set undone_at = now()
                            where id = :eventId
                            """)
                    .param("eventId", mergeEventId)
                    .update();
            return loadFragment(jdbc, event.targetFragmentId());
        });
    }

    private MergePreview inspectMerge(JdbcClient jdbc, List<UUID> fragmentIds) {
        if (fragmentIds == null || fragmentIds.size() < 2) {
            return new MergePreview(false, "병합할 조각을 두 개 이상 선택해 주세요.", null, null, 0);
        }
        MergeFacts facts = jdbc.sql("""
                        select
                            count(*) as fragment_count,
                            count(distinct kind) as kind_count,
                            min(kind) as kind,
                            count(distinct canonical_key) filter (where canonical_key is not null) as canonical_count,
                            count(*) filter (where canonical_key is null) as canonical_missing_count,
                            min(canonical_key) filter (where canonical_key is not null) as canonical_key,
                            count(distinct detail) as detail_count,
                            count(*) filter (where review_status <> 'CONFIRMED') as unconfirmed_count
                        from career_fragments
                        where id in (:fragmentIds)
                          and archived_at is null
                        """)
                .param("fragmentIds", fragmentIds)
                .query((rs, rowNum) -> new MergeFacts(
                        rs.getInt("fragment_count"),
                        rs.getInt("kind_count"),
                        rs.getString("kind"),
                        rs.getInt("canonical_count"),
                        rs.getInt("canonical_missing_count"),
                        rs.getString("canonical_key"),
                        rs.getInt("detail_count"),
                        rs.getInt("unconfirmed_count")
                ))
                .single();
        if (facts.fragmentCount() != fragmentIds.size()) {
            return new MergePreview(false, "보관되었거나 존재하지 않는 조각이 포함되어 있습니다.", null, null, facts.fragmentCount());
        }
        if (facts.unconfirmedCount() > 0) {
            return new MergePreview(false, "검토가 끝난 확정 조각만 병합할 수 있습니다.", facts.kind(), facts.canonicalKey(), facts.fragmentCount());
        }
        if (facts.kindCount() != 1) {
            return new MergePreview(false, "같은 종류의 커리어 조각만 병합할 수 있습니다.", null, null, facts.fragmentCount());
        }
        if (facts.canonicalCount() > 1) {
            return new MergePreview(false, "서로 다른 원자 역량으로 확인된 조각은 하나로 병합할 수 없습니다.", facts.kind(), null, facts.fragmentCount());
        }
        if ("SKILL".equals(facts.kind()) && facts.canonicalMissingCount() > 0) {
            return new MergePreview(false, "아직 원자 역량 식별자가 없는 기술 조각은 먼저 범위를 확인해야 합니다.", facts.kind(), null, facts.fragmentCount());
        }
        if ("SKILL".equals(facts.kind()) && facts.detailCount() > 1) {
            return new MergePreview(false, "같은 기술명이어도 검증 범위가 다른 조각은 병합할 수 없습니다.", facts.kind(), facts.canonicalKey(), facts.fragmentCount());
        }
        return new MergePreview(true, "병합할 수 있습니다. 원본은 보관되며 한 번 되돌릴 수 있습니다.", facts.kind(), facts.canonicalKey(), facts.fragmentCount());
    }

    public void archiveFragment(UUID userId, UUID fragmentId, boolean archived) {
        rls.write(userId, jdbc -> {
            int updated = jdbc.sql("""
                            update career_fragments
                            set archived_at = case when :archived then now() else null end
                            where id = :fragmentId
                            """)
                    .param("archived", archived)
                    .param("fragmentId", fragmentId)
                    .update();
            if (updated == 0) {
                throw fragmentNotFound();
            }
            return null;
        });
    }

    public void deleteFragment(UUID userId, UUID fragmentId) {
        rls.write(userId, jdbc -> {
            int deleted = jdbc.sql("delete from career_fragments where id = :fragmentId")
                    .param("fragmentId", fragmentId)
                    .update();
            if (deleted == 0) {
                throw fragmentNotFound();
            }
            return null;
        });
    }

    public void deleteSource(UUID userId, UUID sourceId) {
        rls.write(userId, jdbc -> {
            jdbc.sql("select finish_career_source(:sourceId, :userId)")
                    .param("sourceId", sourceId)
                    .param("userId", userId)
                    .query(Object.class)
                    .optional();
            int deleted = jdbc.sql("""
                            delete from career_sources
                            where id = :sourceId
                              and status <> 'RUNNING'
                            """)
                    .param("sourceId", sourceId)
                    .update();
            if (deleted == 0) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "CAREER_SOURCE_BUSY",
                        "분석 중인 자료는 완료된 뒤 삭제할 수 있습니다."
                );
            }
            return null;
        });
    }

    private SourceDetail loadSource(
            org.springframework.jdbc.core.simple.JdbcClient jdbc,
            UUID sourceId
    ) {
        SourceSummary source = jdbc.sql("""
                        select
                            s.id,
                            s.source_type,
                            s.title,
                            s.source_url,
                            s.status,
                            s.stage,
                            s.stage_message,
                            s.summary,
                            s.attempt_count,
                            s.error_message,
                            s.archived_at,
                            s.created_at,
                            s.completed_at,
                            count(f.id) filter (
                                where f.review_status = 'CONFIRMED'
                                  and f.archived_at is null
                            ) as confirmed_count,
                            count(f.id) filter (
                                where f.review_status = 'SUGGESTED'
                                  and f.archived_at is null
                            ) as suggested_count
                        from career_sources s
                        left join career_fragments f on f.source_id = s.id
                        where s.id = :sourceId
                        group by s.id
                        """)
                .param("sourceId", sourceId)
                .query(CareerRepositoryService::mapSourceSummary)
                .optional()
                .orElseThrow(CareerRepositoryService::sourceNotFound);
        String rawText = jdbc.sql("select raw_text from career_sources where id = :sourceId")
                .param("sourceId", sourceId)
                .query(String.class)
                .single();
        List<FragmentView> fragments = jdbc.sql("""
                        select
                            f.id,
                            f.source_id,
                            s.title as source_title,
                            f.kind,
                            f.title,
                            f.description,
                            f.canonical_key,
                            f.detail::text,
                            f.review_status,
                            f.archived_at,
                            f.created_at,
                            f.updated_at
                        from career_fragments f
                        join career_sources s on s.id = f.source_id
                        where f.source_id = :sourceId
                          and f.archived_at is null
                        order by f.created_at, f.id
                        """)
                .param("sourceId", sourceId)
                .query((rs, rowNum) -> mapFragment(rs))
                .list();
        return new SourceDetail(source, sensitiveText.decrypt(rawText), fragments);
    }

    private FragmentView loadFragment(
            org.springframework.jdbc.core.simple.JdbcClient jdbc,
            UUID fragmentId
    ) {
        return jdbc.sql("""
                        select
                            f.id,
                            f.source_id,
                            s.title as source_title,
                            f.kind,
                            f.title,
                            f.description,
                            f.canonical_key,
                            f.detail::text,
                            f.review_status,
                            f.archived_at,
                            f.created_at,
                            f.updated_at
                        from career_fragments f
                        join career_sources s on s.id = f.source_id
                        where f.id = :fragmentId
                        """)
                .param("fragmentId", fragmentId)
                .query((rs, rowNum) -> mapFragment(rs))
                .optional()
                .orElseThrow(CareerRepositoryService::fragmentNotFound);
    }

    private static SourceSummary mapSourceSummary(java.sql.ResultSet rs, int rowNum)
            throws java.sql.SQLException {
        return new SourceSummary(
                rs.getObject("id", UUID.class),
                rs.getString("source_type"),
                rs.getString("title"),
                rs.getString("source_url"),
                rs.getString("status"),
                rs.getString("stage"),
                rs.getString("stage_message"),
                rs.getString("summary"),
                rs.getInt("attempt_count"),
                rs.getString("error_message"),
                rs.getLong("confirmed_count"),
                rs.getLong("suggested_count"),
                rs.getObject("archived_at", OffsetDateTime.class),
                rs.getObject("created_at", OffsetDateTime.class),
                rs.getObject("completed_at", OffsetDateTime.class)
        );
    }

    private FragmentView mapFragment(java.sql.ResultSet rs)
            throws java.sql.SQLException {
        return new FragmentView(
                rs.getObject("id", UUID.class),
                rs.getObject("source_id", UUID.class),
                rs.getString("source_title"),
                rs.getString("kind"),
                rs.getString("title"),
                rs.getString("description"),
                rs.getString("canonical_key"),
                readJson(rs.getString("detail")),
                rs.getString("review_status"),
                rs.getObject("archived_at", OffsetDateTime.class),
                rs.getObject("created_at", OffsetDateTime.class),
                rs.getObject("updated_at", OffsetDateTime.class)
        );
    }

    private JsonNode readJson(String value) {
        return value == null ? objectMapper.createObjectNode() : objectMapper.readTree(value);
    }

    private static String blankToNull(String value) {
        return value == null || value.isBlank() ? null : value.trim();
    }

    private static ApiException sourceNotFound() {
        return new ApiException(
                HttpStatus.NOT_FOUND,
                "CAREER_SOURCE_NOT_FOUND",
                "커리어 자료를 찾을 수 없습니다."
        );
    }

    private static ApiException fragmentNotFound() {
        return new ApiException(
                HttpStatus.NOT_FOUND,
                "CAREER_FRAGMENT_NOT_FOUND",
                "커리어 조각을 찾을 수 없습니다."
        );
    }

    public record CreateSource(
            String sourceType,
            String title,
            String sourceUrl,
            String rawText
    ) {
    }

    public record UpdateFragment(
            String kind,
            String title,
            String description,
            String canonicalKey,
            JsonNode detail
    ) {
    }

    public record SourceSummary(
            UUID id,
            String sourceType,
            String title,
            String sourceUrl,
            String status,
            String stage,
            String stageMessage,
            String summary,
            int attemptCount,
            String errorMessage,
            long confirmedCount,
            long suggestedCount,
            OffsetDateTime archivedAt,
            OffsetDateTime createdAt,
            OffsetDateTime completedAt
    ) {
    }

    public record SourceDetail(
            SourceSummary source,
            String rawText,
            List<FragmentView> fragments
    ) {
    }

    public record FragmentView(
            UUID id,
            UUID sourceId,
            String sourceTitle,
            String kind,
            String title,
            String description,
            String canonicalKey,
            JsonNode detail,
            String reviewStatus,
            OffsetDateTime archivedAt,
            OffsetDateTime createdAt,
            OffsetDateTime updatedAt
    ) {
    }

    public record FragmentPage(
            List<FragmentView> items,
            int page,
            int size,
            long total
    ) {
    }

    public record MergePreview(boolean compatible, String reason, String kind, String canonicalKey, int fragmentCount) {
    }

    public record MergeResult(FragmentView fragment, UUID undoId) {
    }

    private record MergeFacts(int fragmentCount, int kindCount, String kind, int canonicalCount, int canonicalMissingCount, String canonicalKey, int detailCount, int unconfirmedCount) {
    }

    private record MergeEvent(UUID targetFragmentId, String beforeSnapshot) {
    }
}
