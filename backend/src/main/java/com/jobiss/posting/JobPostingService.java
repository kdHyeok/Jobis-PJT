package com.jobiss.posting;

import com.jobiss.common.ApiException;
import com.jobiss.db.RlsTransactionExecutor;
import com.jobiss.analysis.AiUsageLimitService;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

@Service
public class JobPostingService {

    private final RlsTransactionExecutor rls;
    private final AiUsageLimitService usageLimit;

    public JobPostingService(RlsTransactionExecutor rls, AiUsageLimitService usageLimit) {
        this.rls = rls;
        this.usageLimit = usageLimit;
    }

    public CreatedPosting create(UUID userId, CreatePosting command) {
        usageLimit.consume(userId, AiUsageLimitService.Kind.ANALYSIS);
        return rls.write(userId, jdbc -> {
            UUID postingId = jdbc.sql("""
                            insert into job_postings (
                                user_id,
                                source_type,
                                source_url,
                                raw_text,
                                conversation_id
                            )
                            values (
                                :userId,
                                cast(:sourceType as posting_source),
                                :sourceUrl,
                                :rawText,
                                :conversationId
                            )
                            returning id
                            """)
                    .param("userId", userId)
                    .param("sourceType", command.sourceType())
                    .param("sourceUrl", command.sourceUrl())
                    .param("rawText", command.rawText().trim())
                    .param("conversationId", command.conversationId())
                    .query(UUID.class)
                    .single();

            UUID analysisJobId = jdbc.sql("""
                            insert into analysis_jobs (user_id, posting_id)
                            values (:userId, :postingId)
                            returning id
                            """)
                    .param("userId", userId)
                    .param("postingId", postingId)
                    .query(UUID.class)
                    .single();

            return new CreatedPosting(postingId, analysisJobId, "QUEUED");
        });
    }

    public List<PostingSummary> list(UUID userId) {
        return rls.read(userId, jdbc -> jdbc.sql("""
                        select
                            p.id,
                            p.source_type,
                            p.source_url,
                            p.company_name,
                            p.role_title,
                            p.experience_text,
                            p.archived_at,
                            p.created_at,
                            j.id as analysis_job_id,
                            j.status as analysis_status
                        from job_postings p
                        left join lateral (
                            select a.id, a.status
                            from analysis_jobs a
                            where a.posting_id = p.id
                            order by a.created_at desc
                            limit 1
                        ) j on true
                        where p.archived_at is null
                        order by p.created_at desc
                        limit 100
                        """)
                .query(JobPostingService::mapSummary)
                .list());
    }

    public PostingPage search(
            UUID userId,
            String query,
            String status,
            String sort,
            String direction,
            int page,
            int size,
            boolean archived
    ) {
        int safePage = Math.max(0, page);
        int safeSize = Math.max(1, Math.min(size, 100));
        String orderColumn = switch (sort) {
            case "company" -> "company_name";
            case "role" -> "role_title";
            case "status" -> "analysis_status";
            default -> "created_at";
        };
        String orderDirection = "asc".equalsIgnoreCase(direction) ? "asc" : "desc";
        String normalizedStatus = status == null ? "" : status.trim().toUpperCase();
        String normalizedQuery = query == null ? "" : query.trim();

        return rls.read(userId, jdbc -> {
            String filter = """
                    from job_postings p
                    left join lateral (
                        select a.id, a.status
                        from analysis_jobs a
                        where a.posting_id = p.id
                        order by a.created_at desc
                        limit 1
                    ) j on true
                    where ((:archived and p.archived_at is not null)
                           or (not :archived and p.archived_at is null))
                      and (
                        :query = ''
                        or coalesce(p.company_name, '') ilike '%' || :query || '%'
                        or coalesce(p.role_title, '') ilike '%' || :query || '%'
                        or p.raw_text ilike '%' || :query || '%'
                      )
                      and (:status = '' or coalesce(j.status::text, 'QUEUED') = :status)
                    """;
            long total = jdbc.sql("select count(*) " + filter)
                    .param("archived", archived)
                    .param("query", normalizedQuery)
                    .param("status", normalizedStatus)
                    .query(Long.class)
                    .single();
            String listSql = """
                    select
                        p.id,
                        p.source_type,
                        p.source_url,
                        p.company_name,
                        p.role_title,
                        p.experience_text,
                        p.archived_at,
                        p.created_at,
                        j.id as analysis_job_id,
                        j.status as analysis_status
                    """ + filter + " order by " + orderColumn + " " + orderDirection
                    + " nulls last limit :limit offset :offset";
            List<PostingSummary> items = jdbc.sql(listSql)
                    .param("archived", archived)
                    .param("query", normalizedQuery)
                    .param("status", normalizedStatus)
                    .param("limit", safeSize)
                    .param("offset", safePage * safeSize)
                    .query(JobPostingService::mapSummary)
                    .list();
            return new PostingPage(items, safePage, safeSize, total);
        });
    }

    public PostingDetail get(UUID userId, UUID postingId) {
        return rls.read(userId, jdbc -> jdbc.sql("""
                        select
                            p.id,
                            p.source_type,
                            p.source_url,
                            p.raw_text,
                            p.company_name,
                            p.role_title,
                            p.employment_type,
                            p.experience_text,
                            p.parsed_data::text,
                            p.archived_at,
                            p.created_at,
                            p.updated_at,
                            j.id as analysis_job_id,
                            j.status as analysis_status
                        from job_postings p
                        left join lateral (
                            select a.id, a.status
                            from analysis_jobs a
                            where a.posting_id = p.id
                            order by a.created_at desc
                            limit 1
                        ) j on true
                        where p.id = :postingId
                        """)
                .param("postingId", postingId)
                .query((rs, rowNum) -> new PostingDetail(
                        rs.getObject("id", UUID.class),
                        rs.getString("source_type"),
                        rs.getString("source_url"),
                        rs.getString("raw_text"),
                        rs.getString("company_name"),
                        rs.getString("role_title"),
                        rs.getString("employment_type"),
                        rs.getString("experience_text"),
                        rs.getString("parsed_data"),
                        rs.getObject("analysis_job_id", UUID.class),
                        rs.getString("analysis_status"),
                        rs.getObject("archived_at", OffsetDateTime.class),
                        rs.getObject("created_at", OffsetDateTime.class),
                        rs.getObject("updated_at", OffsetDateTime.class)
                ))
                .optional()
                .orElseThrow(() -> notFound()));
    }

    public CreatedPosting update(UUID userId, UUID postingId, String sourceUrl, String rawText) {
        usageLimit.consume(userId, AiUsageLimitService.Kind.ANALYSIS);
        return rls.write(userId, jdbc -> {
            int updated = jdbc.sql("""
                            update job_postings
                            set
                                source_url = :sourceUrl,
                                raw_text = :rawText,
                                company_name = null,
                                role_title = null,
                                employment_type = null,
                                experience_text = null,
                                parsed_data = null,
                                updated_by_user_at = now()
                            where id = :postingId
                              and archived_at is null
                            """)
                    .param("sourceUrl", sourceUrl)
                    .param("rawText", rawText.trim())
                    .param("postingId", postingId)
                    .update();
            if (updated == 0) {
                throw notFound();
            }
            UUID analysisJobId = createAnalysisJob(jdbc, userId, postingId);
            return new CreatedPosting(postingId, analysisJobId, "QUEUED");
        });
    }

    public void archive(UUID userId, UUID postingId) {
        setArchived(userId, postingId, true);
    }

    public void restore(UUID userId, UUID postingId) {
        setArchived(userId, postingId, false);
    }

    private void setArchived(UUID userId, UUID postingId, boolean archived) {
        rls.write(userId, jdbc -> {
            int updated = jdbc.sql("""
                            update job_postings
                            set archived_at = case when :archived then now() else null end
                            where id = :postingId
                            """)
                    .param("archived", archived)
                    .param("postingId", postingId)
                    .update();
            if (updated == 0) {
                throw notFound();
            }
            return null;
        });
    }

    public void delete(UUID userId, UUID postingId) {
        rls.write(userId, jdbc -> {
            boolean approved = jdbc.sql("""
                            select exists (
                                select 1
                                from graph_change_sets c
                                join analysis_jobs a on a.id = c.analysis_job_id
                                where a.posting_id = :postingId
                                  and c.status = 'APPROVED'
                            )
                            """)
                    .param("postingId", postingId)
                    .query(Boolean.class)
                    .single();
            if (approved) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "POSTING_ALREADY_MERGED",
                        "지도에 반영된 공고는 삭제 대신 보관할 수 있습니다."
                );
            }
            int deleted = jdbc.sql("delete from job_postings where id = :postingId")
                    .param("postingId", postingId)
                    .update();
            if (deleted == 0) {
                throw notFound();
            }
            return null;
        });
    }

    private UUID createAnalysisJob(JdbcClient jdbc, UUID userId, UUID postingId) {
        return jdbc.sql("""
                        insert into analysis_jobs (user_id, posting_id)
                        values (:userId, :postingId)
                        returning id
                        """)
                .param("userId", userId)
                .param("postingId", postingId)
                .query(UUID.class)
                .single();
    }

    private ApiException notFound() {
        return new ApiException(
                HttpStatus.NOT_FOUND,
                "POSTING_NOT_FOUND",
                "공고를 찾을 수 없습니다."
        );
    }

    private static PostingSummary mapSummary(java.sql.ResultSet rs, int rowNum)
            throws java.sql.SQLException {
        return new PostingSummary(
                rs.getObject("id", UUID.class),
                rs.getString("source_type"),
                rs.getString("source_url"),
                rs.getString("company_name"),
                rs.getString("role_title"),
                rs.getString("experience_text"),
                rs.getObject("analysis_job_id", UUID.class),
                rs.getString("analysis_status"),
                rs.getObject("archived_at", OffsetDateTime.class),
                rs.getObject("created_at", OffsetDateTime.class)
        );
    }

    public record CreatePosting(
            String sourceType,
            String sourceUrl,
            String rawText,
            UUID conversationId
    ) {
    }

    public record CreatedPosting(UUID postingId, UUID analysisJobId, String status) {
    }

    public record PostingSummary(
            UUID id,
            String sourceType,
            String sourceUrl,
            String companyName,
            String roleTitle,
            String experienceText,
            UUID analysisJobId,
            String analysisStatus,
            OffsetDateTime archivedAt,
            OffsetDateTime createdAt
    ) {
    }

    public record PostingPage(
            List<PostingSummary> items,
            int page,
            int size,
            long total
    ) {
    }

    public record PostingDetail(
            UUID id,
            String sourceType,
            String sourceUrl,
            String rawText,
            String companyName,
            String roleTitle,
            String employmentType,
            String experienceText,
            String parsedData,
            UUID analysisJobId,
            String analysisStatus,
            OffsetDateTime archivedAt,
            OffsetDateTime createdAt,
            OffsetDateTime updatedAt
    ) {
    }
}
