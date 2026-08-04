package com.jobiss.analysis;

import com.jobiss.roadmap.RoadmapService;
import com.jobiss.db.RlsTransactionExecutor;
import com.jobiss.config.JobissProperties;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.ObjectMapper;

import java.net.InetAddress;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

@Component
@ConditionalOnProperty(name = "jobiss.ai.worker-enabled", havingValue = "true")
public class AnalysisWorker {

    private static final Logger log = LoggerFactory.getLogger(AnalysisWorker.class);

    private final JdbcClient jdbcClient;
    private final RlsTransactionExecutor rls;
    private final AiAnalysisClient aiClient;
    private final ObjectMapper objectMapper;
    private final TransactionTemplate transactionTemplate;
    private final String workerId;
    private final int maxConcurrentAnalyses;
    private final ExecutorService executor;
    private final AtomicInteger activeAnalyses = new AtomicInteger();
    private final RoadmapService roadmapService;

    public AnalysisWorker(
            JdbcClient jdbcClient,
            RlsTransactionExecutor rls,
            AiAnalysisClient aiClient,
            ObjectMapper objectMapper,
            TransactionTemplate transactionTemplate,
            JobissProperties properties,
            RoadmapService roadmapService
    ) {
        this.jdbcClient = jdbcClient;
        this.rls = rls;
        this.aiClient = aiClient;
        this.objectMapper = objectMapper;
        this.transactionTemplate = transactionTemplate;
        this.roadmapService = roadmapService;
        this.workerId = hostName() + "-" + UUID.randomUUID();
        this.maxConcurrentAnalyses = Math.max(
                1,
                Math.min(properties.ai().maxConcurrentAnalyses(), 8)
        );
        this.executor = Executors.newFixedThreadPool(
                maxConcurrentAnalyses,
                runnable -> {
                    Thread thread = new Thread(runnable);
                    thread.setName("jobiss-analysis-" + thread.getId());
                    thread.setDaemon(true);
                    return thread;
                }
        );
    }

    @Scheduled(fixedDelayString = "${jobiss.ai.poll-delay-ms:3000}")
    public void dispatchAvailable() {
        while (activeAnalyses.get() < maxConcurrentAnalyses) {
            ClaimedJob job = claim();
            if (job == null) {
                break;
            }
            activeAnalyses.incrementAndGet();
            executor.submit(() -> {
                try {
                    process(job);
                } finally {
                    activeAnalyses.decrementAndGet();
                }
            });
        }
    }

    private void process(ClaimedJob job) {
        AnalysisCacheKey cacheKey = null;
        boolean ownsAnalysisLease = false;
        try {
            AiContracts.AnalysisRequest request = loadRequest(job);
            AiContracts.AnalysisResponse response;
            if (request.sharedAnalysis() != null) {
                response = reuseSharedAnalysis(job, request.sharedAnalysis());
            } else {
                cacheKey = analysisCacheKey(request);
                ownsAnalysisLease = tryAcquireAnalysisLease(cacheKey, job.id());
                if (!ownsAnalysisLease) {
                    updateStage(
                            job,
                            "WAITING_FOR_SHARED_ANALYSIS",
                            "같은 공고 분석이 진행 중이라 결과를 기다리고 있어요"
                    );
                    SharedAnalysisWait wait = awaitSharedAnalysis(job, cacheKey);
                    ownsAnalysisLease = wait.ownsLease();
                    response = wait.sharedAnalysis() == null
                            ? aiClient.analyze(
                                    request,
                                    event -> recordProgress(job, event)
                            )
                            : reuseSharedAnalysis(job, wait.sharedAnalysis());
                } else {
                    response = aiClient.analyze(
                            request,
                            event -> recordProgress(job, event)
                    );
                }
            }
            if (response == null || response.status() == null) {
                throw new IllegalStateException("AI response did not include an outcome status");
            }
            if ("NEEDS_INPUT".equals(response.status())) {
                pauseForQuestion(job, request, response.question());
                return;
            }
            if (!"COMPLETED".equals(response.status())
                    || response.job() == null
                    || response.evaluation() == null
                    || response.competencyProposal() == null) {
                throw new IllegalStateException("AI response did not include a competency proposal");
            }
            updateStage(job, "VALIDATING", "추출한 역량과 공고 조건을 검증하고 있어요");
            complete(job, request, response);
            // 재료가 적재됐으면 지도를 자동으로 그린다 — 페이지에서 버튼을 한 번 더 누르지
            // 않아도 되고 "분석했는데 지도가 비어 있다"가 사라진다. 규칙은 RoadmapService
            // 한 곳에 있다(대화 경로도 같은 메서드를 부른다).
            roadmapService.autoGenerateAfterAnalysis(job.userId(), job.id());
        } catch (Exception exception) {
            log.warn("Analysis job {} failed: {}", job.id(), exception.getMessage());
            fail(job, exception);
        } finally {
            if (ownsAnalysisLease && cacheKey != null) {
                releaseAnalysisLease(cacheKey, job.id());
            }
        }
    }

    @PreDestroy
    void shutdown() {
        executor.shutdown();
    }

    private ClaimedJob claim() {
        return transactionTemplate.execute(status -> jdbcClient.sql("""
                                select
                                    id,
                                    user_id,
                                    attempt_count
                                from claim_analysis_job(:workerId)
                                """)
                .param("workerId", workerId)
                .query((rs, rowNum) -> new ClaimedJob(
                        rs.getObject("id", UUID.class),
                        rs.getObject("user_id", UUID.class),
                        rs.getInt("attempt_count")
                ))
                .optional()
                .orElse(null));
    }

    private AiContracts.AnalysisRequest loadRequest(ClaimedJob job) {
        return rls.read(job.userId(), jdbc -> {
            jdbc.sql("""
                            delete from analysis_agent_events
                            where analysis_job_id = :jobId
                            """)
                    .param("jobId", job.id())
                    .update();

            jdbc.sql("""
                            update analysis_jobs
                            set
                                status = 'RUNNING',
                                stage = 'CONTEXT',
                                stage_message = '공고와 현재 커리어 자료를 정리하고 있어요',
                                worker_id = :workerId,
                                locked_until = now() + interval '15 minutes',
                                attempt_count = :attemptCount,
                                started_at = coalesce(started_at, now()),
                                error_code = null,
                                error_message = null
                            where id = :jobId
                            """)
                    .param("workerId", workerId)
                    .param("attemptCount", job.attemptCount())
                    .param("jobId", job.id())
                    .update();

            OwnedPosting posting = jdbc.sql("""
                            select
                                p.id,
                                p.source_type,
                                p.source_url,
                                p.raw_text,
                                p.content_fingerprint
                            from analysis_jobs j
                            join job_postings p on p.id = j.posting_id
                            where j.id = :jobId
                            """)
                    .param("jobId", job.id())
                    .query((rs, rowNum) -> new OwnedPosting(
                            rs.getObject("id", UUID.class),
                            rs.getString("source_type"),
                            rs.getString("source_url"),
                            rs.getString("raw_text"),
                            rs.getString("content_fingerprint")
                    ))
                    .single();

            Graph graph = jdbc.sql("""
                            select id, version
                            from career_graphs
                            where user_id = :userId
                            """)
                    .param("userId", job.userId())
                    .query((rs, rowNum) -> new Graph(
                            rs.getObject("id", UUID.class),
                            rs.getLong("version")
                    ))
                    .single();

            List<AiContracts.ExistingNode> nodes = jdbc.sql("""
                            select
                                c.id,
                                c.canonical_key,
                                c.title,
                                c.domain,
                                c.competency_kind,
                                c.scope_definition,
                                greatest(c.verified_level, 1) as level,
                                c.progress_status::text
                            from user_competencies c
                            where c.user_id = :userId
                            order by c.default_stage, c.canonical_key
                            """)
                    .param("userId", job.userId())
                    .query((rs, rowNum) -> new AiContracts.ExistingNode(
                            rs.getObject("id", UUID.class),
                            rs.getString("canonical_key"),
                            rs.getString("title"),
                            rs.getString("domain"),
                            rs.getString("competency_kind"),
                            rs.getString("scope_definition"),
                            rs.getInt("level"),
                            rs.getString("progress_status")
                    ))
                    .list();

            List<AiContracts.ExistingCareerFragment> fragments = jdbc.sql("""
                            select
                                id,
                                kind,
                                title,
                                description,
                                detail::text
                            from career_fragments
                            where review_status = 'CONFIRMED'
                              and archived_at is null
                            order by updated_at desc
                            limit 500
                            """)
                    .query((rs, rowNum) -> new AiContracts.ExistingCareerFragment(
                            rs.getObject("id", UUID.class),
                            rs.getString("kind"),
                            rs.getString("title"),
                            rs.getString("description"),
                            readJson(rs.getString("detail"))
                    ))
                    .list();

            int questionCount = jdbc.sql("""
                            select question_count
                            from analysis_jobs
                            where id = :jobId
                            """)
                    .param("jobId", job.id())
                    .query(Integer.class)
                    .single();

            List<AiContracts.AnalysisAnswer> answers = jdbc.sql("""
                            select
                                question_key,
                                question_text,
                                answer_value,
                                options::text
                            from analysis_questions
                            where analysis_job_id = :jobId
                              and status = 'ANSWERED'
                            order by ordinal
                            """)
                    .param("jobId", job.id())
                    .query((rs, rowNum) -> {
                        String answerValue = rs.getString("answer_value");
                        return AnalysisClarificationNormalizer.normalize(
                                new AiContracts.AnalysisAnswer(
                                        rs.getString("question_key"),
                                        rs.getString("question_text"),
                                        answerValue,
                                        optionLabel(rs.getString("options"), answerValue)
                                )
                        );
                    })
                    .list();

            String clarificationFingerprint =
                    AnalysisClarificationNormalizer.fingerprint(answers);

            AiContracts.SharedPostingAnalysis sharedAnalysis = jdbc.sql("""
                            select normalized_analysis::text
                            from posting_analysis_cache
                            where content_fingerprint = :contentFingerprint
                              and clarification_fingerprint = :clarificationFingerprint
                              and schema_version = 1
                            limit 1
                            """)
                    .param("contentFingerprint", posting.contentFingerprint())
                    .param("clarificationFingerprint", clarificationFingerprint)
                    .query(String.class)
                    .optional()
                    .map(this::readSharedAnalysis)
                    .orElse(null);
            if (sharedAnalysis != null) {
                jdbc.sql("""
                                update posting_analysis_cache
                                set
                                    use_count = use_count + 1,
                                    last_used_at = now()
                                where content_fingerprint = :contentFingerprint
                                  and clarification_fingerprint = :clarificationFingerprint
                                """)
                        .param("contentFingerprint", posting.contentFingerprint())
                        .param("clarificationFingerprint", clarificationFingerprint)
                        .update();
            }

            AiContracts.CareerGoalContext goals = jdbc.sql("""
                            select
                                goal.current_goal_posting_id,
                                posting.company_name,
                                posting.role_title,
                                goal.final_goal_text
                            from user_goal_profiles goal
                            left join job_postings posting
                              on posting.id = goal.current_goal_posting_id
                            where goal.user_id = :userId
                            """)
                    .param("userId", job.userId())
                    .query((rs, rowNum) -> new AiContracts.CareerGoalContext(
                            rs.getObject("current_goal_posting_id", UUID.class),
                            rs.getString("company_name"),
                            rs.getString("role_title"),
                            rs.getString("final_goal_text")
                    ))
                    .optional()
                    .orElse(new AiContracts.CareerGoalContext(
                            null,
                            null,
                            null,
                            null
                    ));

            jdbc.sql("""
                            update analysis_jobs
                            set
                                stage = 'AI_ANALYSIS',
                                stage_message = '필수·우대 조건과 현재 증거를 비교하고 있어요'
                            where id = :jobId
                            """)
                    .param("jobId", job.id())
                    .update();

            return new AiContracts.AnalysisRequest(
                    job.id(),
                    new AiContracts.Posting(
                            posting.id(),
                            posting.sourceType(),
                            posting.sourceUrl(),
                            posting.rawText()
                    ),
                    new AiContracts.CareerSnapshot(
                            graph.id(),
                            graph.version(),
                            nodes,
                            fragments,
                            goals
                    ),
                    questionCount,
                    answers,
                    sharedAnalysis
            );
        });
    }

    private void pauseForQuestion(
            ClaimedJob job,
            AiContracts.AnalysisRequest request,
            AiContracts.AnalysisQuestion question
    ) {
        if (question == null
                || question.key() == null
                || question.text() == null
                || question.reason() == null
                || question.options() == null
                || question.options().size() < 2
                || question.options().size() > 4) {
            throw new IllegalStateException("AI requested input without a valid question");
        }
        if (request.questionCount() >= 3) {
            throw new IllegalStateException("AI exceeded the clarification question limit");
        }

        AiContracts.AnalysisQuestion normalizedQuestion =
                AnalysisClarificationNormalizer.normalize(question);

        String optionsJson = writeJson(normalizedQuestion.options());
        rls.write(job.userId(), jdbc -> {
            QuestionJobState state = jdbc.sql("""
                            select status::text, question_count
                            from analysis_jobs
                            where id = :jobId
                            for update
                            """)
                    .param("jobId", job.id())
                    .query((rs, rowNum) -> new QuestionJobState(
                            rs.getString("status"),
                            rs.getInt("question_count")
                    ))
                    .single();
            if (!"RUNNING".equals(state.status())) {
                log.info(
                        "Ignoring stale clarification result for analysis job {} in state {}",
                        job.id(),
                        state.status()
                );
                return null;
            }
            if (state.questionCount() >= 3) {
                throw new IllegalStateException(
                        "AI exceeded the clarification question limit"
                );
            }
            boolean repeatedQuestion = jdbc.sql("""
                            select exists (
                                select 1
                                from analysis_questions
                                where analysis_job_id = :jobId
                                  and question_key = :questionKey
                            )
                            """)
                    .param("jobId", job.id())
                    .param("questionKey", normalizedQuestion.key())
                    .query(Boolean.class)
                    .single();
            if (repeatedQuestion) {
                throw new IllegalStateException(
                        "AI repeated a clarification question that was already asked"
                );
            }

            int ordinal = state.questionCount() + 1;
            UUID questionId = jdbc.sql("""
                            insert into analysis_questions (
                                user_id,
                                analysis_job_id,
                                question_key,
                                question_text,
                                reason,
                                options,
                                ordinal
                            )
                            values (
                                :userId,
                                :jobId,
                                :questionKey,
                                :questionText,
                                :reason,
                                cast(:options as jsonb),
                                :ordinal
                            )
                            returning id
                            """)
                    .param("userId", job.userId())
                    .param("jobId", job.id())
                    .param("questionKey", normalizedQuestion.key())
                    .param("questionText", normalizedQuestion.text())
                    .param("reason", normalizedQuestion.reason())
                    .param("options", optionsJson)
                    .param("ordinal", ordinal)
                    .query(UUID.class)
                    .single();

            jdbc.sql("""
                            update analysis_jobs
                            set
                                status = 'WAITING_FOR_INPUT',
                                stage = 'WAITING_FOR_INPUT',
                                stage_message = :questionText,
                                question_count = :questionCount,
                                worker_id = null,
                                locked_until = null
                            where id = :jobId
                            """)
                    .param("questionText", normalizedQuestion.text())
                    .param("questionCount", ordinal)
                    .param("jobId", job.id())
                    .update();

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
                                'ANALYSIS_INPUT_REQUIRED',
                                '공고 분석에 확인이 필요해요',
                                :questionText,
                                jsonb_build_object(
                                    'analysisJobId', cast(:jobId as text),
                                    'questionId', cast(:questionId as text),
                                    'postingId', (
                                        select cast(posting_id as text)
                                        from analysis_jobs
                                        where id = :jobId
                                    )
                                )
                            )
                            """)
                    .param("userId", job.userId())
                    .param("questionText", normalizedQuestion.text())
                    .param("jobId", job.id())
                    .param("questionId", questionId)
                    .update();

            jdbc.sql("""
                            insert into conversation_messages (
                                user_id,
                                conversation_id,
                                role,
                                kind,
                                content,
                                posting_id,
                                analysis_job_id,
                                metadata
                            )
                            select
                                :userId,
                                p.conversation_id,
                                'ASSISTANT',
                                'ANALYSIS_STATUS',
                                :questionText,
                                p.id,
                                j.id,
                                jsonb_build_object(
                                    'status', 'WAITING_FOR_INPUT',
                                    'analysisJobId', cast(j.id as text),
                                    'questionId', cast(:questionId as text)
                                )
                            from analysis_jobs j
                            join job_postings p on p.id = j.posting_id
                            where j.id = :jobId
                              and p.conversation_id is not null
                            """)
                    .param("userId", job.userId())
                    .param("questionText", normalizedQuestion.text())
                    .param("questionId", questionId)
                    .param("jobId", job.id())
                    .update();

            jdbc.sql("select finish_analysis_job(:jobId, :userId)")
                    .param("jobId", job.id())
                    .param("userId", job.userId())
                    .query(Object.class)
                    .optional();
            return null;
        });
    }

    private void complete(
            ClaimedJob job,
            AiContracts.AnalysisRequest request,
            AiContracts.AnalysisResponse response
    ) {
        String proposalJson = objectMapper.writeValueAsString(response.competencyProposal());

        rls.write(job.userId(), jdbc -> {
            jdbc.sql("""
                            update job_postings p
                            set
                                company_name = :companyName,
                                role_title = :roleTitle,
                                employment_type = :employmentType,
                                experience_text = :experienceText,
                                closes_at = :closesAt,
                                lifecycle_status = :lifecycleStatus,
                                parsed_data = cast(:parsedData as jsonb),
                                -- 주소만 받은 공고의 자리표시를 수집 원문으로 되메운다.
                                -- 사용자가 직접 붙여넣은 원문은 건드리지 않는다:
                                -- raw_text 가 source_url 과 같을 때만 바꾼다.
                                -- 존재 여부는 boolean 파라미터로 판별한다(AGENTS.md SQL 규칙 —
                                -- nullable 이름 파라미터를 `is not null` 로 재지 않는다).
                                raw_text = case
                                    when :hasSourceText
                                         and p.source_url is not null
                                         and p.raw_text = p.source_url
                                    then cast(:sourceText as text)
                                    else p.raw_text
                                end
                            from analysis_jobs j
                            where j.id = :jobId
                              and p.id = j.posting_id
                            """)
                    .param("companyName", response.job().companyName())
                    .param("roleTitle", response.job().roleTitle())
                    .param("employmentType", response.job().employmentType())
                    .param("experienceText", response.job().experienceText())
                    .param("closesAt", response.job().closesAt())
                    .param(
                            "lifecycleStatus",
                            effectiveLifecycleStatus(response.job())
                    )
                    .param("parsedData", writeJson(response.job().parsedData()))
                    .param("hasSourceText", blankToNull(response.job().sourceText()) != null)
                    .param("sourceText", blankToNull(response.job().sourceText()) == null
                            ? "" : response.job().sourceText())
                    .param("jobId", job.id())
                    .update();

            UUID postingId = jdbc.sql("""
                            select posting_id
                            from analysis_jobs
                            where id = :jobId
                            """)
                    .param("jobId", job.id())
                    .query(UUID.class)
                    .single();

            AiContracts.ExperienceRequirement experience =
                    experienceOrNone(response);
            jdbc.sql("""
                            insert into posting_path_profiles (
                                posting_id,
                                user_id,
                                analysis_job_id,
                                primary_track,
                                experience_requirement_type,
                                minimum_experience_months,
                                maximum_experience_months,
                                experience_source_text
                            )
                            values (
                                :postingId,
                                :userId,
                                :jobId,
                                :primaryTrack,
                                :experienceType,
                                :minimumMonths,
                                :maximumMonths,
                                :sourceText
                            )
                            on conflict (posting_id)
                            do update set
                                analysis_job_id = excluded.analysis_job_id,
                                primary_track = excluded.primary_track,
                                experience_requirement_type =
                                    excluded.experience_requirement_type,
                                minimum_experience_months =
                                    excluded.minimum_experience_months,
                                maximum_experience_months =
                                    excluded.maximum_experience_months,
                                experience_source_text =
                                    excluded.experience_source_text
                            """)
                    .param("postingId", postingId)
                    .param("userId", job.userId())
                    .param("jobId", job.id())
                    .param("primaryTrack", trackOrDefault(response))
                    .param("experienceType", experience.type())
                    .param("minimumMonths", experience.minimumMonths())
                    .param("maximumMonths", experience.maximumMonths())
                    .param("sourceText", experience.sourceText())
                    .update();

            jdbc.sql("""
                            delete from posting_competency_requirements
                            where posting_id = :postingId
                            """)
                    .param("postingId", postingId)
                    .update();
            jdbc.sql("""
                            delete from posting_target_projects
                            where posting_id = :postingId
                            """)
                    .param("postingId", postingId)
                    .update();

            Map<String, UUID> competencyIds = new HashMap<>();
            Map<String, UUID> catalogCompetencyIds = new HashMap<>();
            Map<String, AiContracts.AnalyzedCompetency> competenciesByRef =
                    new HashMap<>();
            for (AiContracts.AnalyzedCompetency competency
                    : response.competencyProposal().competencies()) {
                UUID catalogCompetencyId = null;
                if (competency.roadmapEligible()) {
                    catalogCompetencyId = jdbc.sql("""
                                    select upsert_competency_catalog(
                                        :canonicalKey,
                                        :title,
                                        :domain,
                                        :scopeDefinition
                                    )
                                    """)
                            .param("canonicalKey", competency.canonicalKey())
                            .param("title", competency.title())
                            .param("domain", competency.domain())
                            .param("scopeDefinition", competency.scopeDefinition())
                            .query(UUID.class)
                            .single();
                }
                UUID competencyId = jdbc.sql("""
                                insert into user_competencies (
                                    user_id,
                                    catalog_competency_id,
                                    canonical_key,
                                    title,
                                    competency_kind,
                                    domain,
                                    default_stage,
                                    scope_definition,
                                    roadmap_eligible,
                                    verification_method
                                )
                                values (
                                    :userId,
                                    :catalogCompetencyId,
                                    :canonicalKey,
                                    :title,
                                    :kind,
                                    :domain,
                                    :stage,
                                    :scopeDefinition,
                                    :roadmapEligible,
                                    :verificationMethod
                                )
                                on conflict (user_id, canonical_key)
                                do update set
                                    catalog_competency_id = coalesce(
                                        user_competencies.catalog_competency_id,
                                        excluded.catalog_competency_id
                                    ),
                                    title = case
                                        when user_competencies.catalog_competency_id is not null
                                            then user_competencies.title
                                        else excluded.title
                                    end,
                                    competency_kind = case
                                        when user_competencies.catalog_competency_id is not null
                                            then user_competencies.competency_kind
                                        else excluded.competency_kind
                                    end,
                                    domain = case
                                        when user_competencies.catalog_competency_id is not null
                                            then user_competencies.domain
                                        else excluded.domain
                                    end,
                                    default_stage = case
                                        when user_competencies.catalog_competency_id is not null
                                            then user_competencies.default_stage
                                        else excluded.default_stage
                                    end,
                                    scope_definition = case
                                        when user_competencies.catalog_competency_id is not null
                                            then user_competencies.scope_definition
                                        else excluded.scope_definition
                                    end,
                                    roadmap_eligible = case
                                        when user_competencies.catalog_competency_id is not null
                                            then true
                                        else excluded.roadmap_eligible
                                    end,
                                    verification_method = case
                                        when user_competencies.catalog_competency_id is not null
                                            then user_competencies.verification_method
                                        else excluded.verification_method
                                    end
                                returning id
                                """)
                        .param("userId", job.userId())
                        .param("catalogCompetencyId", catalogCompetencyId)
                        .param("canonicalKey", competency.canonicalKey())
                        .param("title", competency.title())
                        .param("kind", competency.kind())
                        .param("domain", competency.domain())
                        .param("stage", competency.stage())
                        .param("scopeDefinition", competency.scopeDefinition())
                        .param("roadmapEligible", competency.roadmapEligible())
                        .param("verificationMethod", competency.verificationMethod())
                        .query(UUID.class)
                        .single();
                if (competencyIds.put(competency.ref(), competencyId) != null) {
                    throw new IllegalStateException("AI returned duplicate competency refs");
                }
                if (catalogCompetencyId != null) {
                    catalogCompetencyIds.put(competency.ref(), catalogCompetencyId);
                }
                competenciesByRef.put(competency.ref(), competency);
            }

            for (AiContracts.AnalyzedRequirement requirement
                    : response.competencyProposal().requirements()) {
                UUID competencyId = competencyIds.get(requirement.competencyRef());
                AiContracts.AnalyzedCompetency competency =
                        competenciesByRef.get(requirement.competencyRef());
                if (competencyId == null || competency == null) {
                    throw new IllegalStateException(
                            "AI requirement references an unknown competency"
                    );
                }
                jdbc.sql("""
                                insert into posting_competency_requirements (
                                    user_id,
                                    posting_id,
                                    analysis_job_id,
                                    competency_id,
                                    relation_kind,
                                    required_scope,
                                    required_level,
                                    source_text,
                                    confidence,
                                    competency_title,
                                    competency_kind,
                                    roadmap_domain,
                                    roadmap_stage,
                                    roadmap_eligible,
                                    verification_method
                                )
                                values (
                                    :userId,
                                    :postingId,
                                    :jobId,
                                    :competencyId,
                                    :relationKind,
                                    :requiredScope,
                                    :requiredLevel,
                                    :sourceText,
                                    :confidence,
                                    :competencyTitle,
                                    :competencyKind,
                                    :roadmapDomain,
                                    :roadmapStage,
                                    :roadmapEligible,
                                    :verificationMethod
                                )
                                """)
                        .param("userId", job.userId())
                        .param("postingId", postingId)
                        .param("jobId", job.id())
                        .param("competencyId", competencyId)
                        .param("relationKind", requirement.relation())
                        .param("requiredScope", competency.scopeDefinition())
                        .param("requiredLevel", competency.requiredLevel())
                        .param("sourceText", requirement.sourceText())
                        .param("confidence", requirement.confidence())
                        .param("competencyTitle", competency.title())
                        .param("competencyKind", competency.kind())
                        .param("roadmapDomain", competency.domain())
                        .param("roadmapStage", competency.stage())
                        .param("roadmapEligible", competency.roadmapEligible())
                        .param("verificationMethod", competency.verificationMethod())
                        .update();
            }

            UUID postingCatalogId = jdbc.sql("""
                            select canonical_posting_id
                            from job_postings
                            where id = :postingId
                            """)
                    .param("postingId", postingId)
                    .query(UUID.class)
                    .optional()
                    .orElse(null);
            if (postingCatalogId == null) {
                postingCatalogId = jdbc.sql("""
                                select publish_analyzed_posting(
                                    :postingId,
                                    :primaryTrack,
                                    :experienceType,
                                    :minimumMonths,
                                    :maximumMonths
                                )
                                """)
                        .param("postingId", postingId)
                        .param("primaryTrack", trackOrDefault(response))
                        .param("experienceType", experience.type())
                        .param("minimumMonths", experience.minimumMonths())
                        .param("maximumMonths", experience.maximumMonths())
                        .query(UUID.class)
                        .single();
            }

            jdbc.sql("""
                            update posting_catalog catalog
                            set
                                source_platform = coalesce(
                                    catalog.source_platform,
                                    posting.source_platform
                                ),
                                source_posting_key = coalesce(
                                    catalog.source_posting_key,
                                    posting.source_posting_key
                                ),
                                content_fingerprint = coalesce(
                                    catalog.content_fingerprint,
                                    posting.content_fingerprint
                                ),
                                closes_at = posting.closes_at,
                                lifecycle_status = posting.lifecycle_status,
                                last_seen_at = now(),
                                updated_at = now()
                            from job_postings posting
                            where catalog.id = :catalogId
                              and posting.id = :postingId
                            """)
                    .param("catalogId", postingCatalogId)
                    .param("postingId", postingId)
                    .update();
            jdbc.sql("""
                            update job_postings posting
                            set
                                canonical_posting_id = :catalogId,
                                company_name = catalog.company_name,
                                role_title = catalog.role_title
                            from posting_catalog catalog
                            where posting.id = :postingId
                              and catalog.id = :catalogId
                            """)
                    .param("catalogId", postingCatalogId)
                    .param("postingId", postingId)
                    .update();
            jdbc.sql("""
                            insert into posting_catalog_observations (
                                user_id,
                                private_posting_id,
                                posting_catalog_id,
                                observed_url,
                                content_fingerprint
                            )
                            select
                                :userId,
                                posting.id,
                                :catalogId,
                                posting.source_url,
                                posting.content_fingerprint
                            from job_postings posting
                            where posting.id = :postingId
                            on conflict (user_id, private_posting_id)
                            do update set
                                posting_catalog_id = excluded.posting_catalog_id,
                                observed_url = excluded.observed_url,
                                content_fingerprint = excluded.content_fingerprint,
                                last_observed_at = now()
                            """)
                    .param("userId", job.userId())
                    .param("catalogId", postingCatalogId)
                    .param("postingId", postingId)
                    .update();

            jdbc.sql("""
                            insert into posting_duplicate_candidates (
                                left_posting_id,
                                right_posting_id,
                                match_kind,
                                similarity_score,
                                proposed_action,
                                proposal_reason
                            )
                            select
                                least(:catalogId, candidate.id),
                                greatest(:catalogId, candidate.id),
                                'FUZZY',
                                greatest(
                                    similarity(current.company_name, candidate.company_name),
                                    similarity(current.role_title, candidate.role_title)
                                ),
                                case
                                    when similarity(
                                        current.company_name,
                                        candidate.company_name
                                    ) >= 0.8
                                     and similarity(
                                        current.role_title,
                                        candidate.role_title
                                    ) >= 0.75
                                        then 'MERGE'
                                    else 'REVIEW'
                                end,
                                '회사명과 직무명이 유사해 운영자 확인이 필요합니다.'
                            from posting_catalog current
                            join posting_catalog candidate
                              on candidate.id <> current.id
                             and candidate.moderation_status <> 'MERGED'
                             and similarity(
                                 current.company_name,
                                 candidate.company_name
                             ) >= 0.65
                             and similarity(
                                 current.role_title,
                                 candidate.role_title
                             ) >= 0.6
                            where current.id = :catalogId
                            on conflict (
                                (least(left_posting_id, right_posting_id)),
                                (greatest(left_posting_id, right_posting_id))
                            )
                            do nothing
                            """)
                    .param("catalogId", postingCatalogId)
                    .update();

            for (AiContracts.AnalyzedRequirement requirement
                    : response.competencyProposal().requirements()) {
                AiContracts.AnalyzedCompetency competency =
                        competenciesByRef.get(requirement.competencyRef());
                UUID catalogCompetencyId =
                        catalogCompetencyIds.get(requirement.competencyRef());
                if (competency == null
                        || catalogCompetencyId == null
                        || !competency.roadmapEligible()) {
                    continue;
                }
                jdbc.sql("""
                                select publish_posting_catalog_requirement(
                                    :privatePostingId,
                                    :postingCatalogId,
                                    :catalogCompetencyId,
                                    :relationKind,
                                    :requiredScope,
                                    :requiredLevel,
                                    :confidence
                                )
                                """)
                        .param("privatePostingId", postingId)
                        .param("postingCatalogId", postingCatalogId)
                        .param("catalogCompetencyId", catalogCompetencyId)
                        .param("relationKind", requirement.relation())
                        .param("requiredScope", competency.scopeDefinition())
                        .param("requiredLevel", competency.requiredLevel())
                        .param("confidence", requirement.confidence())
                        .query(Object.class)
                        .optional();
            }

            AiContracts.TargetProjectBrief project =
                    response.competencyProposal().targetProject();
            List<String> requiredProjectKeys = project.requiredCompetencyRefs()
                    .stream()
                    .map(ref -> competenciesByRef.get(ref).canonicalKey())
                    .toList();
            List<String> optionalProjectKeys = project.optionalCompetencyRefs()
                    .stream()
                    .map(ref -> competenciesByRef.get(ref).canonicalKey())
                    .toList();
            jdbc.sql("""
                            insert into posting_target_projects (
                                posting_id,
                                user_id,
                                analysis_job_id,
                                title,
                                objective,
                                domain_context,
                                required_competency_keys,
                                optional_competency_keys,
                                deliverables,
                                acceptance_criteria
                            )
                            values (
                                :postingId,
                                :userId,
                                :jobId,
                                :title,
                                :objective,
                                :domainContext,
                                cast(:requiredKeys as jsonb),
                                cast(:optionalKeys as jsonb),
                                cast(:deliverables as jsonb),
                                cast(:acceptanceCriteria as jsonb)
                            )
                            """)
                    .param("postingId", postingId)
                    .param("userId", job.userId())
                    .param("jobId", job.id())
                    .param("title", project.title())
                    .param("objective", project.objective())
                    .param("domainContext", project.domainContext())
                    .param("requiredKeys", writeJson(requiredProjectKeys))
                    .param("optionalKeys", writeJson(optionalProjectKeys))
                    .param("deliverables", writeJson(project.deliverables()))
                    .param("acceptanceCriteria", writeJson(project.acceptanceCriteria()))
                    .update();

            AiContracts.Evaluation deterministicEvaluation =
                    evaluateReadiness(jdbc, postingId, response);
            CatalogDisplay catalogDisplay = jdbc.sql("""
                            select company_name, role_title
                            from posting_catalog
                            where id = :catalogId
                            """)
                    .param("catalogId", postingCatalogId)
                    .query((rs, rowNum) -> new CatalogDisplay(
                            rs.getString("company_name"),
                            rs.getString("role_title")
                    ))
                    .single();
            AiContracts.JobContext normalizedJob = withCanonicalDisplay(
                    response.job(),
                    catalogDisplay
            );
            AiContracts.AnalysisResponse normalizedResponse =
                    new AiContracts.AnalysisResponse(
                            response.status(),
                            response.question(),
                            normalizedJob,
                            deterministicEvaluation,
                            response.competencyProposal()
                    );
            String resultJson = objectMapper.writeValueAsString(normalizedResponse);

            jdbc.sql("""
                            insert into posting_analysis_cache (
                                content_fingerprint,
                                clarification_fingerprint,
                                normalized_analysis
                            )
                            select
                                posting.content_fingerprint,
                                :clarificationFingerprint,
                                jsonb_build_object(
                                    'job', cast(:jobContext as jsonb),
                                    'competencyProposal', cast(:proposal as jsonb)
                                )
                            from job_postings posting
                            where posting.id = :postingId
                            on conflict (
                                content_fingerprint,
                                clarification_fingerprint
                            )
                            do update set
                                normalized_analysis = excluded.normalized_analysis,
                                last_used_at = now()
                            """)
                    .param(
                            "clarificationFingerprint",
                            AnalysisClarificationNormalizer.fingerprint(request.answers())
                    )
                    .param("jobContext", writeJson(normalizedJob))
                    .param("proposal", proposalJson)
                    .param("postingId", postingId)
                    .update();

            jdbc.sql("""
                            update analysis_jobs
                            set
                                status = 'SUCCEEDED',
                                stage = 'COMPLETED',
                                stage_message = '분석 완료',
                                result_data = cast(:resultJson as jsonb),
                                completed_at = now(),
                                locked_until = null
                            where id = :jobId
                            """)
                    .param("resultJson", resultJson)
                    .param("jobId", job.id())
                    .update();

            jdbc.sql("""
                            insert into graph_change_sets (
                                user_id,
                                analysis_job_id,
                                proposal
                            )
                            values (
                                :userId,
                                :jobId,
                                cast(:proposalJson as jsonb)
                            )
                            on conflict (analysis_job_id)
                            do update set
                                proposal = excluded.proposal,
                                status = 'PROPOSED',
                                approved_at = null,
                                rejected_at = null
                            """)
                    .param("userId", job.userId())
                    .param("jobId", job.id())
                    .param("proposalJson", proposalJson)
                    .update();

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
                                'ANALYSIS_COMPLETED',
                                '공고 분석이 완료됐어요',
                                '추출한 역량을 확인한 뒤 목표 공고에 추가해 주세요.',
                                jsonb_build_object(
                                    'analysisJobId', cast(:jobId as text),
                                    'postingId', (
                                        select cast(posting_id as text)
                                        from analysis_jobs
                                        where id = :jobId
                                    )
                                )
                            )
                            """)
                    .param("userId", job.userId())
                    .param("jobId", job.id())
                    .update();

            jdbc.sql("""
                            insert into conversation_messages (
                                user_id,
                                conversation_id,
                                role,
                                kind,
                                content,
                                posting_id,
                                analysis_job_id,
                                metadata
                            )
                            select
                                :userId,
                                p.conversation_id,
                                'ASSISTANT',
                                'ANALYSIS_STATUS',
                                -- 완료 안내도 에이전트가 한다 — 여기는 카드 자리만 남긴다.
                                '',
                                p.id,
                                j.id,
                                jsonb_build_object(
                                    'status', 'SUCCEEDED',
                                    'analysisJobId', cast(j.id as text),
                                    'evaluation', cast(:evaluation as jsonb)
                                )
                            from analysis_jobs j
                            join job_postings p on p.id = j.posting_id
                            where j.id = :jobId
                              and p.conversation_id is not null
                            """)
                    .param("userId", job.userId())
                    .param("jobId", job.id())
                    .param("evaluation", writeJson(deterministicEvaluation))
                    .update();

            jdbc.sql("select finish_analysis_job(:jobId, :userId)")
                    .param("jobId", job.id())
                    .param("userId", job.userId())
                    .query(Object.class)
                    .optional();
            return null;
        });
    }

    private AiContracts.Evaluation evaluateReadiness(
            org.springframework.jdbc.core.simple.JdbcClient jdbc,
            UUID postingId,
            AiContracts.AnalysisResponse response
    ) {
        ReadinessCounts counts = jdbc.sql("""
                        select
                            count(*) filter (
                                where requirement.relation_kind = 'REQUIRED'
                                  and requirement.roadmap_eligible
                            ) as required_total,
                            count(*) filter (
                                where requirement.relation_kind = 'REQUIRED'
                                  and requirement.roadmap_eligible
                                  and competency.progress_status = 'COMPLETED'
                                  and competency.verified_level >=
                                      requirement.required_level
                            ) as required_met,
                            count(*) filter (
                                where requirement.relation_kind = 'PREFERRED'
                                  and requirement.roadmap_eligible
                            ) as preferred_total,
                            count(*) filter (
                                where requirement.relation_kind = 'PREFERRED'
                                  and requirement.roadmap_eligible
                                  and competency.progress_status = 'COMPLETED'
                                  and competency.verified_level >=
                                      requirement.required_level
                            ) as preferred_met
                        from posting_competency_requirements requirement
                        join user_competencies competency
                          on competency.id = requirement.competency_id
                        where requirement.posting_id = :postingId
                        """)
                .param("postingId", postingId)
                .query((rs, rowNum) -> new ReadinessCounts(
                        rs.getInt("required_total"),
                        rs.getInt("required_met"),
                        rs.getInt("preferred_total"),
                        rs.getInt("preferred_met")
                ))
                .single();
        List<String> gaps = jdbc.sql("""
                        select distinct requirement.competency_title
                        from posting_competency_requirements requirement
                        join user_competencies competency
                          on competency.id = requirement.competency_id
                        where requirement.posting_id = :postingId
                          and requirement.relation_kind = 'REQUIRED'
                          and requirement.roadmap_eligible
                          and (
                              competency.progress_status <> 'COMPLETED'
                              or competency.verified_level <
                                  requirement.required_level
                          )
                        order by requirement.competency_title
                        limit 5
                        """)
                .param("postingId", postingId)
                .query(String.class)
                .list();
        int experienceMonths = jdbc.sql("""
                        select coalesce(max(
                            case
                                when detail ->> 'months' ~ '^[0-9]{1,3}$'
                                then (detail ->> 'months')::integer
                                else 0
                            end
                        ), 0)
                        from career_fragments
                        where review_status = 'CONFIRMED'
                          and archived_at is null
                          and kind = 'EXPERIENCE'
                        """)
                .query(Integer.class)
                .single();
        AiContracts.ExperienceRequirement experience = experienceOrNone(response);
        boolean experienceMet = !"REQUIRED".equals(experience.type())
                || experienceMonths >= experience.minimumMonths();
        int experienceShortage = Math.max(
                0,
                experience.minimumMonths() - experienceMonths
        );
        double coverage = counts.requiredTotal() == 0
                ? 1
                : (double) counts.requiredMet() / counts.requiredTotal();

        String verdict;
        if (counts.requiredMet() == counts.requiredTotal() && experienceMet) {
            verdict = "APPLY_NOW";
        } else if ((!experienceMet && experienceShortage > 12)
                || coverage < 0.5) {
            verdict = "ALTERNATIVE_FIRST";
        } else {
            verdict = "STRENGTHEN_THEN_APPLY";
        }

        List<String> reasons = new ArrayList<>();
        reasons.add("검증된 필수 역량 "
                + counts.requiredMet() + "/" + counts.requiredTotal());
        if (counts.preferredTotal() > 0) {
            reasons.add("검증된 우대 역량 "
                    + counts.preferredMet() + "/" + counts.preferredTotal());
        }
        if (!gaps.isEmpty()) {
            reasons.add("보완이 필요한 필수 역량: " + String.join(", ", gaps));
        }
        if ("REQUIRED".equals(experience.type())) {
            reasons.add(experienceMet
                    ? "요구 경력 조건을 충족하는 기록이 확인됐습니다."
                    : "요구 경력 " + experience.minimumMonths()
                            + "개월에 대한 검증 기록이 부족합니다.");
        }

        String summary = switch (verdict) {
            case "APPLY_NOW" ->
                    "현재 검증된 필수 역량과 경력 조건을 기준으로 지원 가능한 상태입니다.";
            case "STRENGTHEN_THEN_APPLY" ->
                    "핵심 경로는 맞지만 일부 필수 역량을 검증한 뒤 지원하는 것이 좋습니다.";
            default ->
                    "현재 목표까지 간격이 커서 가까운 실제 공고를 함께 검토하는 것이 좋습니다.";
        };
        return new AiContracts.Evaluation(verdict, summary, List.copyOf(reasons));
    }

    private void fail(ClaimedJob job, Exception exception) {
        rls.write(job.userId(), jdbc -> {
            jdbc.sql("""
                            update analysis_jobs
                            set
                                status = 'FAILED',
                                stage = 'FAILED',
                                stage_message = '공고 분석을 완료하지 못했어요',
                                error_code = :errorCode,
                                error_message = :errorMessage,
                                completed_at = now(),
                                locked_until = null
                            where id = :jobId
                            """)
                    .param("errorCode", classify(exception))
                    .param("errorMessage", safeMessage(exception))
                    .param("jobId", job.id())
                    .update();
            jdbc.sql("""
                            insert into conversation_messages (
                                user_id,
                                conversation_id,
                                role,
                                kind,
                                content,
                                posting_id,
                                analysis_job_id,
                                metadata
                            )
                            select
                                :userId,
                                p.conversation_id,
                                'ASSISTANT',
                                'ANALYSIS_STATUS',
                                -- **문장을 담지 않는다.** 이 턴에 말할 주체는 에이전트다.
                                -- 이 행은 진행 카드가 붙는 자리로만 남긴다(카드가 상태 FAILED ·
                                -- errorMessage · "다시 분석"을 보여준다). 실측(08-03 22:47):
                                -- 에이전트가 공고를 정리해 답하는 턴에 "이력서를 주시겠어요?"가
                                -- 화자 없이 따로 떠서 누가 무엇을 요구하는지 흐려졌다.
                                '',
                                p.id,
                                j.id,
                                jsonb_build_object(
                                    'status', 'FAILED',
                                    'analysisJobId', cast(j.id as text),
                                    'errorMessage', :errorMessage
                                )
                            from analysis_jobs j
                            join job_postings p on p.id = j.posting_id
                            where j.id = :jobId
                              and p.conversation_id is not null
                            """)
                    .param("userId", job.userId())
                    .param("jobId", job.id())
                    .param("errorMessage", safeMessage(exception))
                    .update();
            jdbc.sql("select finish_analysis_job(:jobId, :userId)")
                    .param("jobId", job.id())
                    .param("userId", job.userId())
                    .query(Object.class)
                    .optional();
            return null;
        });
    }

    /** 빈 문자열은 "값 없음"이다 — SQL 에서 null 로 다뤄야 되메우기 조건이 성립한다. */
    private static String blankToNull(String value) {
        return value == null || value.isBlank() ? null : value;
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (RuntimeException exception) {
            throw new IllegalStateException("Could not serialize AI response", exception);
        }
    }

    private tools.jackson.databind.JsonNode readJson(String value) {
        return value == null ? objectMapper.createObjectNode() : objectMapper.readTree(value);
    }

    private String optionLabel(String optionsJson, String answerValue) {
        for (tools.jackson.databind.JsonNode option : readJson(optionsJson)) {
            if (answerValue.equals(option.path("value").stringValue(""))) {
                return option.path("label").stringValue(answerValue);
            }
        }
        return answerValue;
    }

    private String normalizeLifecycleStatus(String status) {
        if (status == null) {
            return "UNKNOWN";
        }
        return switch (status) {
            case "ACTIVE", "EXPIRED", "CLOSED", "UNKNOWN" -> status;
            default -> "UNKNOWN";
        };
    }

    private String effectiveLifecycleStatus(AiContracts.JobContext job) {
        if (job.closesAt() != null
                && !job.closesAt().isAfter(OffsetDateTime.now())) {
            return "EXPIRED";
        }
        return normalizeLifecycleStatus(job.lifecycleStatus());
    }

    private AiContracts.SharedPostingAnalysis readSharedAnalysis(String value) {
        try {
            return objectMapper.readValue(
                    value,
                    AiContracts.SharedPostingAnalysis.class
            );
        } catch (RuntimeException exception) {
            throw new IllegalStateException(
                    "Stored shared posting analysis is invalid",
                    exception
            );
        }
    }

    /**
     * AI 계약상 경력 근거가 없는 공고는 {@code experienceRequirement} 가 null 이다
     * (근거 없이 "요건 없음"을 단정하지 않는다는 AI 쪽 원칙). 경력 관문은
     * {@code REQUIRED·개월>0} 에서만 생기므로 'NONE'/0 은 V11 백필과 같은 무관문 표기다 —
     * null 그대로 쓰면 NPE 로 분석 job 이 통째로 죽는다(실측 08-04, 캐시 재사용 경로).
     */
    /** 트랙을 못 정한 공고도 지도에 올린다 — `primary_track` 은 두 테이블에서 NOT NULL 이다.

     * <p>AI 계약상 `primaryTrack` 은 null 이 될 수 있다(모르면 짐작하지 않는다). 그런데
     * `posting_path_profiles`·`posting_catalog` 는 10종 중 하나를 강제하고 'ETC' 가 없어,
     * null 을 그대로 넣으면 성공한 분석이 마지막 적재에서 통째로 죽는다(실측 08-04:
     * job 765a595e, `null value in column "primary_track"`). 조회 쪽이 이미
     * `coalesce(profile.primary_track, 'BACKEND')` 로 같은 기본값을 쓰므로(RoadmapService)
     * 쓰기도 같은 값으로 맞춘다 — 받는 쪽은 넉넉하게.
     */
    private static String trackOrDefault(AiContracts.AnalysisResponse response) {
        String track = response.job().primaryTrack();
        return track == null || track.isBlank() ? "BACKEND" : track;
    }

    private static AiContracts.ExperienceRequirement experienceOrNone(
            AiContracts.AnalysisResponse response
    ) {
        AiContracts.ExperienceRequirement experience =
                response.job().experienceRequirement();
        return experience != null
                ? experience
                : new AiContracts.ExperienceRequirement("NONE", 0, null, "");
    }

    private AiContracts.AnalysisResponse reuseSharedAnalysis(
            ClaimedJob job,
            AiContracts.SharedPostingAnalysis shared
    ) {
        updateStage(
                job,
                "SHARED_REUSE",
                "같은 공고의 기존 분석을 재사용하고 현재 준비도만 다시 계산하고 있어요"
        );
        return new AiContracts.AnalysisResponse(
                "COMPLETED",
                null,
                shared.job(),
                new AiContracts.Evaluation(
                        "STRENGTHEN_THEN_APPLY",
                        "공용 공고 분석을 재사용해 현재 준비도를 다시 계산합니다.",
                        List.of("공고 자체를 다시 생성하지 않고 현재 커리어 근거만 비교합니다.")
                ),
                shared.competencyProposal()
        );
    }

    private AiContracts.JobContext withCanonicalDisplay(
            AiContracts.JobContext job,
            CatalogDisplay display
    ) {
        return new AiContracts.JobContext(
                display.companyName(),
                display.roleTitle(),
                job.employmentType(),
                job.experienceText(),
                job.primaryTrack(),
                job.experienceRequirement(),
                job.closesAt(),
                job.lifecycleStatus(),
                job.sourceText(),
                job.parsedData()
        );
    }

    private AnalysisCacheKey analysisCacheKey(AiContracts.AnalysisRequest request) {
        String normalizedBody = request.posting().rawText()
                .trim()
                .replaceAll("\\s+", " ")
                .toLowerCase(Locale.ROOT);
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            String contentFingerprint = HexFormat.of().formatHex(
                    digest.digest(normalizedBody.getBytes(StandardCharsets.UTF_8))
            );
            return new AnalysisCacheKey(
                    contentFingerprint,
                    AnalysisClarificationNormalizer.fingerprint(request.answers())
            );
        } catch (Exception exception) {
            throw new IllegalStateException(
                    "Could not fingerprint posting analysis",
                    exception
            );
        }
    }

    private boolean tryAcquireAnalysisLease(
            AnalysisCacheKey key,
            UUID analysisJobId
    ) {
        UUID owner = transactionTemplate.execute(status -> jdbcClient.sql("""
                                insert into posting_analysis_leases (
                                    content_fingerprint,
                                    clarification_fingerprint,
                                    owner_analysis_job_id,
                                    lease_until
                                )
                                values (
                                    :contentFingerprint,
                                    :clarificationFingerprint,
                                    :analysisJobId,
                                    now() + interval '15 minutes'
                                )
                                on conflict (
                                    content_fingerprint,
                                    clarification_fingerprint
                                )
                                do update set
                                    owner_analysis_job_id = excluded.owner_analysis_job_id,
                                    lease_until = excluded.lease_until
                                where posting_analysis_leases.lease_until < now()
                                returning owner_analysis_job_id
                                """)
                        .param("contentFingerprint", key.contentFingerprint())
                        .param(
                                "clarificationFingerprint",
                                key.clarificationFingerprint()
                        )
                        .param("analysisJobId", analysisJobId)
                        .query(UUID.class)
                        .optional()
                        .orElse(null));
        return analysisJobId.equals(owner);
    }

    private SharedAnalysisWait awaitSharedAnalysis(
            ClaimedJob job,
            AnalysisCacheKey key
    ) throws InterruptedException {
        long deadline = System.nanoTime() + TimeUnit.MINUTES.toNanos(14);
        while (System.nanoTime() < deadline) {
            AiContracts.SharedPostingAnalysis shared = loadSharedAnalysis(key);
            if (shared != null) {
                return new SharedAnalysisWait(shared, false);
            }
            if (tryAcquireAnalysisLease(key, job.id())) {
                updateStage(
                        job,
                        "AI_ANALYSIS",
                        "이전 분석이 중단되어 이 작업에서 분석을 이어가고 있어요"
                );
                return new SharedAnalysisWait(null, true);
            }
            Thread.sleep(2_000);
        }
        throw new IllegalStateException(
                "Timed out waiting for the shared posting analysis"
        );
    }

    private AiContracts.SharedPostingAnalysis loadSharedAnalysis(
            AnalysisCacheKey key
    ) {
        return transactionTemplate.execute(status -> {
            AiContracts.SharedPostingAnalysis shared = jdbcClient.sql("""
                            select normalized_analysis::text
                            from posting_analysis_cache
                            where content_fingerprint = :contentFingerprint
                              and clarification_fingerprint = :clarificationFingerprint
                              and schema_version = 1
                            limit 1
                            """)
                    .param("contentFingerprint", key.contentFingerprint())
                    .param(
                            "clarificationFingerprint",
                            key.clarificationFingerprint()
                    )
                    .query(String.class)
                    .optional()
                    .map(this::readSharedAnalysis)
                    .orElse(null);
            if (shared != null) {
                jdbcClient.sql("""
                                update posting_analysis_cache
                                set
                                    use_count = use_count + 1,
                                    last_used_at = now()
                                where content_fingerprint = :contentFingerprint
                                  and clarification_fingerprint = :clarificationFingerprint
                                """)
                        .param("contentFingerprint", key.contentFingerprint())
                        .param(
                                "clarificationFingerprint",
                                key.clarificationFingerprint()
                        )
                        .update();
            }
            return shared;
        });
    }

    private void releaseAnalysisLease(
            AnalysisCacheKey key,
            UUID analysisJobId
    ) {
        try {
            transactionTemplate.executeWithoutResult(status -> jdbcClient.sql("""
                            delete from posting_analysis_leases
                            where content_fingerprint = :contentFingerprint
                              and clarification_fingerprint = :clarificationFingerprint
                              and owner_analysis_job_id = :analysisJobId
                            """)
                    .param("contentFingerprint", key.contentFingerprint())
                    .param(
                            "clarificationFingerprint",
                            key.clarificationFingerprint()
                    )
                    .param("analysisJobId", analysisJobId)
                    .update());
        } catch (RuntimeException exception) {
            log.warn(
                    "Could not release shared analysis lease for job {}: {}",
                    analysisJobId,
                    exception.getMessage()
            );
        }
    }

    private void updateStage(ClaimedJob job, String stage, String message) {
        rls.write(job.userId(), jdbc -> {
            jdbc.sql("""
                            update analysis_jobs
                            set stage = :stage, stage_message = :message
                            where id = :jobId
                            """)
                    .param("stage", stage)
                    .param("message", message)
                    .param("jobId", job.id())
                    .update();
            return null;
        });
    }

    private void recordProgress(
            ClaimedJob job,
            AiContracts.AnalysisStreamEvent event
    ) {
        if (event == null
                || event.runId() == null
                || !job.id().equals(event.runId())
                || event.sequence() < 1
                || event.sequence() > 10000) {
            throw new IllegalStateException("AI progress event did not match the analysis job");
        }
        if ("RESULT".equals(event.type())) {
            return;
        }
        String eventJson = writeJson(event);
        rls.write(job.userId(), jdbc -> {
            jdbc.sql("""
                            insert into analysis_agent_events (
                                user_id,
                                analysis_job_id,
                                sequence,
                                event_data,
                                occurred_at
                            )
                            values (
                                :userId,
                                :jobId,
                                :sequence,
                                cast(:eventData as jsonb),
                                coalesce(:occurredAt, now())
                            )
                            on conflict (analysis_job_id, sequence)
                            do update set
                                event_data = excluded.event_data,
                                occurred_at = excluded.occurred_at
                            """)
                    .param("userId", job.userId())
                    .param("jobId", job.id())
                    .param("sequence", event.sequence())
                    .param("eventData", eventJson)
                    .param("occurredAt", event.occurredAt())
                    .update();

            if ("STAGE_UPDATED".equals(event.type()) && event.stage() != null) {
                String message = event.stage().message();
                boolean hasMessage = message != null && !message.isBlank();
                jdbc.sql("""
                                update analysis_jobs
                                set
                                    stage = :stage,
                                    stage_message = case
                                        when :hasMessage then :message
                                        else stage_message
                                    end
                                where id = :jobId
                                """)
                        .param("stage", event.stage().id())
                        .param("hasMessage", hasMessage)
                        .param("message", hasMessage ? message : "")
                        .param("jobId", job.id())
                        .update();
            }
            return null;
        });
    }

    private String classify(Exception exception) {
        if (exception instanceof AiServiceException aiException) {
            return aiException.code();
        }
        String name = exception.getClass().getSimpleName();
        return name.length() > 80 ? "AI_ANALYSIS_FAILED" : name.toUpperCase();
    }

    private String safeMessage(Exception exception) {
        String code = classify(exception);
        if ("INVALID_AI_RESPONSE".equals(code)) {
            return "AI가 만든 분석 결과 중 일부가 서비스 검증 규칙과 맞지 않았습니다. "
                    + "저장된 공고에서 다시 분석을 눌러 주세요.";
        }
        if ("AI_PROVIDER_UNAVAILABLE".equals(code)) {
            return "AI 서비스 응답이 지연되거나 중단되었습니다. 공고는 저장되어 있으니 "
                    + "잠시 후 다시 분석할 수 있습니다.";
        }
        String message = exception.getMessage();
        if (message == null || message.isBlank()) {
            return "AI 분석을 완료하지 못했습니다.";
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

    private record Graph(UUID id, long version) {
    }

    private record ClaimedJob(
            UUID id,
            UUID userId,
            int attemptCount
    ) {
    }

    private record OwnedPosting(
            UUID id,
            String sourceType,
            String sourceUrl,
            String rawText,
            String contentFingerprint
    ) {
    }

    private record QuestionJobState(
            String status,
            int questionCount
    ) {
    }

    private record ReadinessCounts(
            int requiredTotal,
            int requiredMet,
            int preferredTotal,
            int preferredMet
    ) {
    }

    private record CatalogDisplay(String companyName, String roleTitle) {
    }

    private record AnalysisCacheKey(
            String contentFingerprint,
            String clarificationFingerprint
    ) {
    }

    private record SharedAnalysisWait(
            AiContracts.SharedPostingAnalysis sharedAnalysis,
            boolean ownsLease
    ) {
    }
}
