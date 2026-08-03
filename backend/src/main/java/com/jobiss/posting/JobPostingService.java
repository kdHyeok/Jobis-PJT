package com.jobiss.posting;

import com.jobiss.common.ApiException;
import com.jobiss.db.RlsTransactionExecutor;
import com.jobiss.analysis.AiContracts;
import com.jobiss.analysis.AnalysisClarificationNormalizer;
import com.jobiss.analysis.AiUsageLimitService;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.OffsetDateTime;
import java.util.HexFormat;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.UUID;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

@Service
public class JobPostingService {

    private static final Pattern PLATFORM_POSTING_KEY = Pattern.compile(
            "(?:recruitNo|rec_idx|jobId|position|noticeSn)=([A-Za-z0-9_-]+)",
            Pattern.CASE_INSENSITIVE
    );
    private static final Pattern PATH_POSTING_KEY = Pattern.compile(
            "/([A-Za-z0-9_-]{4,})(?:/)?$"
    );

    private final RlsTransactionExecutor rls;
    private final AiUsageLimitService usageLimit;

    public JobPostingService(RlsTransactionExecutor rls, AiUsageLimitService usageLimit) {
        this.rls = rls;
        this.usageLimit = usageLimit;
    }

    public CreatedPosting create(UUID userId, CreatePosting command) {
        return rls.write(userId, jdbc -> {
            PostingIdentity identity = postingIdentity(
                    command.sourceUrl(),
                    command.rawText()
            );
            ActiveAnalysis active = findActiveAnalysis(
                    jdbc,
                    userId,
                    identity.contentFingerprint(),
                    command.conversationId()
            );
            if (active != null) {
                return new CreatedPosting(
                        active.postingId(),
                        active.jobId(),
                        active.status(),
                        true,
                        "같은 공고의 분석이 이미 진행 중이라 기존 작업을 이어서 보여드립니다."
                );
            }

            usageLimit.consume(jdbc, userId, AiUsageLimitService.Kind.ANALYSIS);
            ReusableAnalysis reusable = findReusableAnalysis(
                    jdbc,
                    userId,
                    identity.contentFingerprint()
            );
            UUID canonicalPostingId = findExactCanonical(jdbc, identity);
            UUID postingId = jdbc.sql("""
                            insert into job_postings (
                                user_id,
                                source_type,
                                source_url,
                                raw_text,
                                conversation_id,
                                source_platform,
                                source_posting_key,
                                content_fingerprint,
                                canonical_posting_id
                            )
                            values (
                                :userId,
                                cast(:sourceType as posting_source),
                                :sourceUrl,
                                :rawText,
                                :conversationId,
                                :sourcePlatform,
                                :sourcePostingKey,
                                :contentFingerprint,
                                :canonicalPostingId
                            )
                            returning id
                            """)
                    .param("userId", userId)
                    .param("sourceType", command.sourceType())
                    .param("sourceUrl", command.sourceUrl())
                    .param("rawText", command.rawText().trim())
                    .param("conversationId", command.conversationId())
                    .param("sourcePlatform", identity.platform())
                    .param("sourcePostingKey", identity.postingKey())
                    .param("contentFingerprint", identity.contentFingerprint())
                    .param("canonicalPostingId", canonicalPostingId)
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

            boolean reusedAnalysis = prepareReuse(
                    jdbc,
                    userId,
                    analysisJobId,
                    reusable
            );

            return new CreatedPosting(
                    postingId,
                    analysisJobId,
                    "QUEUED",
                    reusedAnalysis,
                    reusedAnalysis
                            ? "같은 공고의 기존 분석을 재사용해 현재 준비도만 다시 계산합니다."
                            : null
            );
        });
    }

    public List<PostingSummary> list(UUID userId) {
        return rls.read(userId, jdbc -> jdbc.sql("""
                        select
                            p.id,
                            p.source_type,
                            p.source_url,
                            coalesce(catalog.company_name, p.company_name) as company_name,
                            coalesce(catalog.role_title, p.role_title) as role_title,
                            p.experience_text,
                            p.closes_at,
                            p.lifecycle_status,
                            p.archived_at,
                            p.created_at,
                            j.id as analysis_job_id,
                            j.status as analysis_status
                        from job_postings p
                        left join posting_catalog catalog
                          on catalog.id = p.canonical_posting_id
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
                    left join posting_catalog catalog
                      on catalog.id = p.canonical_posting_id
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
                        or coalesce(catalog.company_name, p.company_name, '')
                            ilike '%' || :query || '%'
                        or coalesce(catalog.role_title, p.role_title, '')
                            ilike '%' || :query || '%'
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
                        coalesce(catalog.company_name, p.company_name) as company_name,
                        coalesce(catalog.role_title, p.role_title) as role_title,
                        p.experience_text,
                        p.closes_at,
                        p.lifecycle_status,
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
                            coalesce(catalog.company_name, p.company_name) as company_name,
                            coalesce(catalog.role_title, p.role_title) as role_title,
                            p.employment_type,
                            p.experience_text,
                            p.closes_at,
                            p.lifecycle_status,
                            p.parsed_data::text,
                            p.archived_at,
                            p.created_at,
                            p.updated_at,
                            j.id as analysis_job_id,
                            j.status as analysis_status
                        from job_postings p
                        left join posting_catalog catalog
                          on catalog.id = p.canonical_posting_id
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
                        rs.getObject("closes_at", OffsetDateTime.class),
                        rs.getString("lifecycle_status"),
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
        return rls.write(userId, jdbc -> {
            usageLimit.consume(jdbc, userId, AiUsageLimitService.Kind.ANALYSIS);
            PostingIdentity identity = postingIdentity(sourceUrl, rawText);
            ReusableAnalysis reusable = findReusableAnalysis(
                    jdbc,
                    userId,
                    identity.contentFingerprint()
            );
            UUID canonicalPostingId = findExactCanonical(jdbc, identity);
            int updated = jdbc.sql("""
                            update job_postings
                            set
                                source_url = :sourceUrl,
                                raw_text = :rawText,
                                source_platform = :sourcePlatform,
                                source_posting_key = :sourcePostingKey,
                                content_fingerprint = :contentFingerprint,
                                canonical_posting_id = :canonicalPostingId,
                                company_name = null,
                                role_title = null,
                                employment_type = null,
                                experience_text = null,
                                closes_at = null,
                                lifecycle_status = 'UNKNOWN',
                                parsed_data = null,
                                updated_by_user_at = now()
                            where id = :postingId
                              and archived_at is null
                            """)
                    .param("sourceUrl", sourceUrl)
                    .param("rawText", rawText.trim())
                    .param("sourcePlatform", identity.platform())
                    .param("sourcePostingKey", identity.postingKey())
                    .param("contentFingerprint", identity.contentFingerprint())
                    .param("canonicalPostingId", canonicalPostingId)
                    .param("postingId", postingId)
                    .update();
            if (updated == 0) {
                throw notFound();
            }
            UUID analysisJobId = createAnalysisJob(jdbc, userId, postingId);
            boolean reusedAnalysis = prepareReuse(
                    jdbc,
                    userId,
                    analysisJobId,
                    reusable
            );
            return new CreatedPosting(
                    postingId,
                    analysisJobId,
                    "QUEUED",
                    reusedAnalysis,
                    reusedAnalysis
                            ? "같은 공고의 기존 분석을 재사용해 현재 준비도만 다시 계산합니다."
                            : null
            );
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

    private ActiveAnalysis findActiveAnalysis(
            JdbcClient jdbc,
            UUID userId,
            String contentFingerprint,
            UUID conversationId
    ) {
        String conversationPredicate = conversationId == null
                ? "and posting.conversation_id is null"
                : "and posting.conversation_id = :conversationId";
        String sql = """
                        select
                            job.id,
                            job.posting_id,
                            job.status::text
                        from analysis_jobs job
                        join job_postings posting on posting.id = job.posting_id
                        where job.user_id = :userId
                          and posting.content_fingerprint = :contentFingerprint
                        """ + conversationPredicate + """
                          and job.status in ('QUEUED', 'RUNNING', 'WAITING_FOR_INPUT')
                        order by job.created_at desc
                        limit 1
                        """;
        JdbcClient.StatementSpec statement = jdbc.sql(sql)
                .param("userId", userId)
                .param("contentFingerprint", contentFingerprint);
        if (conversationId != null) {
            statement = statement.param("conversationId", conversationId);
        }
        return statement
                .query((rs, rowNum) -> new ActiveAnalysis(
                        rs.getObject("id", UUID.class),
                        rs.getObject("posting_id", UUID.class),
                        rs.getString("status")
                ))
                .optional()
                .orElse(null);
    }

    private ReusableAnalysis findReusableAnalysis(
            JdbcClient jdbc,
            UUID userId,
            String contentFingerprint
    ) {
        UUID sourceJobId = jdbc.sql("""
                        select job.id
                        from analysis_jobs job
                        join job_postings posting on posting.id = job.posting_id
                        where job.user_id = :userId
                          and job.status = 'SUCCEEDED'
                          and posting.content_fingerprint = :contentFingerprint
                          and jsonb_exists(job.result_data, 'job')
                          and jsonb_exists(job.result_data, 'competencyProposal')
                        order by job.completed_at desc nulls last
                        limit 1
                        """)
                .param("userId", userId)
                .param("contentFingerprint", contentFingerprint)
                .query(UUID.class)
                .optional()
                .orElse(null);
        if (sourceJobId == null) {
            return null;
        }

        List<ReusableAnswer> answers = jdbc.sql("""
                        select
                            question_key,
                            question_text,
                            reason,
                            options::text,
                            answer_value,
                            coalesce(
                                (
                                    select option ->> 'label'
                                    from jsonb_array_elements(options) option
                                    where option ->> 'value' = answer_value
                                    limit 1
                                ),
                                answer_value
                            ) as answer_label,
                            ordinal
                        from analysis_questions
                        where analysis_job_id = :jobId
                          and status = 'ANSWERED'
                        order by ordinal
                        """)
                .param("jobId", sourceJobId)
                .query((rs, rowNum) -> new ReusableAnswer(
                        rs.getString("question_key"),
                        rs.getString("question_text"),
                        rs.getString("reason"),
                        rs.getString("options"),
                        rs.getString("answer_value"),
                        rs.getString("answer_label"),
                        rs.getInt("ordinal")
                ))
                .list();
        return new ReusableAnalysis(sourceJobId, answers);
    }

    private boolean prepareReuse(
            JdbcClient jdbc,
            UUID userId,
            UUID targetJobId,
            ReusableAnalysis reusable
    ) {
        if (reusable == null) {
            return false;
        }

        List<AiContracts.AnalysisAnswer> normalizedAnswers = reusable.answers()
                .stream()
                .map(answer -> AnalysisClarificationNormalizer.normalize(
                        new AiContracts.AnalysisAnswer(
                                answer.questionKey(),
                                answer.questionText(),
                                answer.answerValue(),
                                answer.answerLabel()
                        )
                ))
                .toList();
        String clarificationFingerprint =
                AnalysisClarificationNormalizer.fingerprint(normalizedAnswers);

        int cached = jdbc.sql("""
                        insert into posting_analysis_cache (
                            content_fingerprint,
                            clarification_fingerprint,
                            normalized_analysis
                        )
                        select
                            posting.content_fingerprint,
                            :clarificationFingerprint,
                            jsonb_build_object(
                                'job', source_job.result_data -> 'job',
                                'competencyProposal',
                                source_job.result_data -> 'competencyProposal'
                            )
                        from analysis_jobs source_job
                        join job_postings posting
                          on posting.id = source_job.posting_id
                        where source_job.id = :sourceJobId
                          and source_job.status = 'SUCCEEDED'
                          and jsonb_exists(source_job.result_data, 'job')
                          and jsonb_exists(
                              source_job.result_data,
                              'competencyProposal'
                          )
                        on conflict (
                            content_fingerprint,
                            clarification_fingerprint
                        )
                        do update set
                            normalized_analysis = excluded.normalized_analysis,
                            last_used_at = now()
                        """)
                .param("clarificationFingerprint", clarificationFingerprint)
                .param("sourceJobId", reusable.sourceJobId())
                .update();
        if (cached == 0) {
            return false;
        }

        Set<String> copiedKeys = new HashSet<>();
        int ordinal = 0;
        for (int index = 0; index < reusable.answers().size(); index++) {
            ReusableAnswer source = reusable.answers().get(index);
            AiContracts.AnalysisAnswer normalized = normalizedAnswers.get(index);
            if (!copiedKeys.add(normalized.questionKey())) {
                continue;
            }
            ordinal += 1;
            jdbc.sql("""
                            insert into analysis_questions (
                                user_id,
                                analysis_job_id,
                                question_key,
                                question_text,
                                reason,
                                options,
                                status,
                                answer_value,
                                answered_at,
                                ordinal
                            )
                            values (
                                :userId,
                                :jobId,
                                :questionKey,
                                :questionText,
                                :reason,
                                cast(:options as jsonb),
                                'ANSWERED',
                                :answerValue,
                                now(),
                                :ordinal
                            )
                            """)
                    .param("userId", userId)
                    .param("jobId", targetJobId)
                    .param("questionKey", normalized.questionKey())
                    .param("questionText", source.questionText())
                    .param("reason", source.reason())
                    .param("options", source.optionsJson())
                    .param("answerValue", normalized.answerValue())
                    .param("ordinal", ordinal)
                    .update();
        }
        jdbc.sql("""
                        update analysis_jobs
                        set
                            question_count = :questionCount,
                            stage_message = '기존 공고 분석을 재사용할 준비가 되었어요'
                        where id = :jobId
                        """)
                .param("questionCount", ordinal)
                .param("jobId", targetJobId)
                .update();
        return true;
    }

    private UUID findExactCanonical(JdbcClient jdbc, PostingIdentity identity) {
        if (identity.platform() == null || identity.postingKey() == null) {
            return jdbc.sql("""
                            select id
                            from posting_catalog
                            where moderation_status <> 'MERGED'
                              and content_fingerprint = :contentFingerprint
                            order by updated_at desc
                            limit 1
                            """)
                    .param("contentFingerprint", identity.contentFingerprint())
                    .query(UUID.class)
                    .optional()
                    .orElse(null);
        }
        return jdbc.sql("""
                        select id
                        from posting_catalog
                        where moderation_status <> 'MERGED'
                          and (
                            (
                              source_platform = :sourcePlatform
                              and source_posting_key = :sourcePostingKey
                            )
                            or content_fingerprint = :contentFingerprint
                          )
                        order by
                            case
                                when source_platform = :sourcePlatform
                                 and source_posting_key = :sourcePostingKey
                                    then 0
                                else 1
                            end,
                            updated_at desc
                        limit 1
                        """)
                .param("sourcePlatform", identity.platform())
                .param("sourcePostingKey", identity.postingKey())
                .param("contentFingerprint", identity.contentFingerprint())
                .query(UUID.class)
                .optional()
                .orElse(null);
    }

    private PostingIdentity postingIdentity(String sourceUrl, String rawText) {
        String platform = null;
        String postingKey = null;
        if (sourceUrl != null && !sourceUrl.isBlank()) {
            try {
                URI uri = URI.create(sourceUrl.trim());
                String host = uri.getHost();
                if (host != null) {
                    platform = host.toLowerCase(Locale.ROOT)
                            .replaceFirst("^www\\.", "");
                }
                Matcher queryMatcher =
                        PLATFORM_POSTING_KEY.matcher(sourceUrl.trim());
                if (queryMatcher.find()) {
                    postingKey = queryMatcher.group(1);
                } else if (uri.getPath() != null) {
                    Matcher pathMatcher =
                            PATH_POSTING_KEY.matcher(uri.getPath());
                    if (pathMatcher.find()) {
                        postingKey = pathMatcher.group(1);
                    }
                }
            } catch (IllegalArgumentException ignored) {
                // URL metadata is optional; body hashing remains available.
            }
        }
        String normalizedBody = rawText.trim()
                .replaceAll("\\s+", " ")
                .toLowerCase(Locale.ROOT);
        return new PostingIdentity(
                platform,
                postingKey,
                sha256(normalizedBody)
        );
    }

    private String sha256(String value) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(
                    digest.digest(value.getBytes(StandardCharsets.UTF_8))
            );
        } catch (Exception exception) {
            throw new IllegalStateException(
                    "Could not fingerprint posting",
                    exception
            );
        }
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
                rs.getObject("closes_at", OffsetDateTime.class),
                rs.getString("lifecycle_status"),
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

    public record CreatedPosting(
            UUID postingId,
            UUID analysisJobId,
            String status,
            boolean reusedAnalysis,
            String reuseMessage
    ) {
    }

    public record PostingSummary(
            UUID id,
            String sourceType,
            String sourceUrl,
            String companyName,
            String roleTitle,
            String experienceText,
            OffsetDateTime closesAt,
            String lifecycleStatus,
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
            OffsetDateTime closesAt,
            String lifecycleStatus,
            String parsedData,
            UUID analysisJobId,
            String analysisStatus,
            OffsetDateTime archivedAt,
            OffsetDateTime createdAt,
            OffsetDateTime updatedAt
    ) {
    }

    private record PostingIdentity(
            String platform,
            String postingKey,
            String contentFingerprint
    ) {
    }

    private record ReusableAnalysis(
            UUID sourceJobId,
            List<ReusableAnswer> answers
    ) {
    }

    private record ActiveAnalysis(
            UUID jobId,
            UUID postingId,
            String status
    ) {
    }

    private record ReusableAnswer(
            String questionKey,
            String questionText,
            String reason,
            String optionsJson,
            String answerValue,
            String answerLabel,
            int ordinal
    ) {
    }
}
