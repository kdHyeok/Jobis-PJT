package com.jobiss.analysis;

import com.jobiss.db.RlsTransactionExecutor;
import com.jobiss.config.JobissProperties;
import com.jobiss.analysis.v3.V3AnalysisJobProcessor;
import com.jobiss.security.SensitiveTextCipher;
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
import java.util.concurrent.FutureTask;
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
    private final AnalysisTaskRegistry taskRegistry;
    private final V3AnalysisJobProcessor v3Processor;
    private final SensitiveTextCipher sensitiveText;
    private final String workerId;
    private final int maxConcurrentAnalyses;
    private final ExecutorService executor;
    private final AtomicInteger activeAnalyses = new AtomicInteger();

    public AnalysisWorker(
            JdbcClient jdbcClient,
            RlsTransactionExecutor rls,
            AiAnalysisClient aiClient,
            ObjectMapper objectMapper,
            TransactionTemplate transactionTemplate,
            JobissProperties properties,
            AnalysisTaskRegistry taskRegistry,
            V3AnalysisJobProcessor v3Processor,
            SensitiveTextCipher sensitiveText
    ) {
        this.jdbcClient = jdbcClient;
        this.rls = rls;
        this.aiClient = aiClient;
        this.objectMapper = objectMapper;
        this.transactionTemplate = transactionTemplate;
        this.taskRegistry = taskRegistry;
        this.v3Processor = v3Processor;
        this.sensitiveText = sensitiveText;
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
        recoverStaleJobs();
        while (activeAnalyses.get() < maxConcurrentAnalyses) {
            ClaimedJob job = claim();
            if (job == null) {
                break;
            }
            activeAnalyses.incrementAndGet();
            FutureTask<Void> task = new FutureTask<>(() -> {
                try {
                    process(job);
                } finally {
                    taskRegistry.complete(job.id());
                    activeAnalyses.decrementAndGet();
                }
                return null;
            });
            taskRegistry.register(job.id(), task);
            executor.execute(task);
        }
    }

    private void process(ClaimedJob job) {
        AnalysisCacheKey cacheKey = null;
        boolean ownsAnalysisLease = false;
        String failureStage = "INITIALIZATION";
        try {
            if (v3Processor.supports(job.userId(), job.id())) {
                failureStage = "CAREER_PIPELINE";
                v3Processor.process(job.userId(), job.id(), workerId);
                return;
            }
            AiContracts.AnalysisRequest request = loadRequest(job);
            failureStage = "AI_ANALYSIS";
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
                            "같은 공고의 커리어 적합도 분석이 진행 중이라 결과를 기다리고 있어요"
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
            response = ensureTargetProject(response);
            validateAnalysisQuality(response);
            failureStage = "RESULT_VALIDATION";
            updateStage(job, "VALIDATING", "추출한 역량과 공고 조건을 검증하고 있어요");
            failureStage = "RESULT_PERSISTENCE";
            complete(job, request, response);
        } catch (SupersededAnalysisException exception) {
            log.info("Ignoring result from superseded analysis job {}", job.id());
        } catch (Exception exception) {
            log.warn("Analysis job {} failed: {}", job.id(), exception.getMessage());
            try {
                fail(job, exception, failureStage);
            } catch (RuntimeException failureUpdateException) {
                log.error(
                        "Could not persist failure for analysis job {}",
                        job.id(),
                        failureUpdateException
                );
            }
        } finally {
            if (ownsAnalysisLease && cacheKey != null) {
                releaseAnalysisLease(cacheKey, job.id());
            }
        }
    }

    @PreDestroy
    void shutdown() {
        try {
            Integer interrupted = transactionTemplate.execute(status -> jdbcClient.sql("""
                            select interrupt_analysis_jobs(:workerId)
                            """)
                    .param("workerId", workerId)
                    .query(Integer.class)
                    .single());
            if (interrupted != null && interrupted > 0) {
                log.info("Marked {} analysis jobs interrupted during shutdown", interrupted);
            }
        } catch (RuntimeException exception) {
            log.warn("Could not mark active analysis jobs interrupted: {}", exception.getMessage());
        }
        taskRegistry.cancelAll();
        executor.shutdownNow();
        try {
            if (!executor.awaitTermination(5, TimeUnit.SECONDS)) {
                log.warn("Analysis executor did not terminate within 5 seconds");
            }
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
        }
    }

    private void recoverStaleJobs() {
        try {
            Integer recovered = transactionTemplate.execute(status -> jdbcClient.sql("""
                            select recover_stale_analysis_jobs()
                            """)
                    .query(Integer.class)
                    .single());
            if (recovered != null && recovered > 0) {
                log.warn("Recovered {} stale analysis jobs", recovered);
            }
        } catch (RuntimeException exception) {
            log.warn("Could not recover stale analysis jobs: {}", exception.getMessage());
        }
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
                            sensitiveText.decrypt(rs.getString("raw_text")),
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
                                input_type,
                                answer_status,
                                related_requirement_ids::text,
                                absence_scope,
                                options::text
                            from analysis_questions
                            where analysis_job_id = :jobId
                              and status = 'ANSWERED'
                            order by ordinal
                            """)
                    .param("jobId", job.id())
                    .query((rs, rowNum) -> {
                        String answerValue = rs.getString("answer_value");
                        String optionsJson = rs.getString("options");
                        String inputType = rs.getString("input_type");
                        return AnalysisClarificationNormalizer.normalize(
                                new AiContracts.AnalysisAnswer(
                                        rs.getString("question_key"),
                                        rs.getString("question_text"),
                                        answerValue,
                                        optionLabel(optionsJson, answerValue),
                                        inputType,
                                        rs.getString("answer_status"),
                                        readStringList(rs.getString("related_requirement_ids")),
                                        rs.getString("absence_scope")
                                )
                        );
                    })
                    .list();

            String clarificationFingerprint =
                    AnalysisClarificationNormalizer.fingerprint(answers);

            String sharedAnalysisJson = jdbc.sql("""
                            select normalized_analysis::text
                            from posting_analysis_cache
                            where content_fingerprint = :contentFingerprint
                              and clarification_fingerprint = :clarificationFingerprint
                              and schema_version = 1
                              and invalidated_at is null
                            limit 1
                            """)
                    .param("contentFingerprint", posting.contentFingerprint())
                    .param("clarificationFingerprint", clarificationFingerprint)
                    .query(String.class)
                    .optional()
                    .orElse(null);
            AiContracts.SharedPostingAnalysis sharedAnalysis = parseSharedAnalysis(
                    jdbc,
                    posting.contentFingerprint(),
                    clarificationFingerprint,
                    sharedAnalysisJson
            );
            if (sharedAnalysis != null) {
                jdbc.sql("""
                                update posting_analysis_cache
                                set
                                    use_count = use_count + 1,
                                    last_used_at = now()
                                where content_fingerprint = :contentFingerprint
                                  and clarification_fingerprint = :clarificationFingerprint
                                  and invalidated_at is null
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

            int staged = jdbc.sql("""
                            update analysis_jobs
                            set
                                stage = 'AI_ANALYSIS',
                                stage_message = '필수·우대 조건과 현재 증거를 비교하고 있어요'
                            where id = :jobId
                              and status = 'RUNNING'
                              and worker_id = :workerId
                            """)
                    .param("workerId", workerId)
                    .param("jobId", job.id())
                    .update();
            if (staged == 0) {
                throw new SupersededAnalysisException();
            }

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
                || question.inputType() == null
                || question.options() == null
                || question.relatedRequirementIds() == null
                || question.absenceScope() == null) {
            throw new IllegalStateException("AI requested input without a valid question");
        }
        boolean textQuestion = "TEXT".equalsIgnoreCase(question.inputType());
        if ((textQuestion && !question.options().isEmpty())
                || (!textQuestion && (question.options().size() < 2
                || question.options().size() > 4))) {
            throw new IllegalStateException("AI requested input with an invalid question shape");
        }
        if (request.questionCount() >= 3) {
            throw new IllegalStateException("AI exceeded the clarification question limit");
        }

        AiContracts.AnalysisQuestion normalizedQuestion =
                AnalysisClarificationNormalizer.normalize(question);

        String optionsJson = writeJson(normalizedQuestion.options());
        rls.write(job.userId(), jdbc -> {
            QuestionJobState state = jdbc.sql("""
                            select status::text, question_count, worker_id
                            from analysis_jobs
                            where id = :jobId
                            for update
                            """)
                    .param("jobId", job.id())
                    .query((rs, rowNum) -> new QuestionJobState(
                            rs.getString("status"),
                            rs.getInt("question_count"),
                            rs.getString("worker_id")
                    ))
                    .single();
            if (!"RUNNING".equals(state.status())
                    || !workerId.equals(state.workerId())) {
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
                                input_type,
                                options,
                                related_requirement_ids,
                                absence_scope,
                                ordinal
                            )
                            values (
                                :userId,
                                :jobId,
                                :questionKey,
                                :questionText,
                                :reason,
                                :inputType,
                                cast(:options as jsonb),
                                cast(:relatedRequirementIds as jsonb),
                                :absenceScope,
                                :ordinal
                            )
                            returning id
                            """)
                    .param("userId", job.userId())
                    .param("jobId", job.id())
                    .param("questionKey", normalizedQuestion.key())
                    .param("questionText", normalizedQuestion.text())
                    .param("reason", normalizedQuestion.reason())
                    .param("inputType", normalizedQuestion.inputType())
                    .param("options", optionsJson)
                    .param(
                            "relatedRequirementIds",
                            writeJson(normalizedQuestion.relatedRequirementIds())
                    )
                    .param("absenceScope", normalizedQuestion.absenceScope())
                    .param("ordinal", ordinal)
                    .query(UUID.class)
                    .single();

            jdbc.sql("""
                            delete from posting_analysis_leases
                            where owner_analysis_job_id = :jobId
                            """)
                    .param("jobId", job.id())
                    .update();

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
                                '커리어 적합도 분석에 확인이 필요해요',
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
            requireCurrentWorker(jdbc, job);
            jdbc.sql("""
                            update job_postings p
                            set
                                company_name = :companyName,
                                role_title = :roleTitle,
                                employment_type = :employmentType,
                                experience_text = :experienceText,
                                closes_at = :closesAt,
                                lifecycle_status = :lifecycleStatus,
                                parsed_data = cast(:parsedData as jsonb)
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
                    response.job().experienceRequirement();
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
                    .param("primaryTrack", response.job().primaryTrack())
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
                        .param("primaryTrack", response.job().primaryTrack())
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
            if (project != null) {
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
            }

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
                                last_used_at = now(),
                                invalidated_at = null,
                                invalid_reason = null
                            """)
                    .param(
                            "clarificationFingerprint",
                            AnalysisClarificationNormalizer.fingerprint(request.answers())
                    )
                    .param("jobContext", writeJson(normalizedJob))
                    .param("proposal", proposalJson)
                    .param("postingId", postingId)
                    .update();

            int completed = jdbc.sql("""
                            update analysis_jobs
                            set
                                status = 'SUCCEEDED',
                                stage = 'COMPLETED',
                                stage_message = '분석 완료',
                                result_data = cast(:resultJson as jsonb),
                                completed_at = now(),
                                locked_until = null
                            where id = :jobId
                              and status = 'RUNNING'
                              and worker_id = :workerId
                            """)
                    .param("resultJson", resultJson)
                    .param("workerId", workerId)
                    .param("jobId", job.id())
                    .update();
            if (completed == 0) {
                throw new SupersededAnalysisException();
            }

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
                                '커리어 적합도 분석이 완료됐어요',
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
                                '커리어 적합도 분석이 완료됐어요. 역량과 맞춤 프로젝트를 확인해 주세요.',
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

    private AiContracts.AnalysisResponse ensureTargetProject(
            AiContracts.AnalysisResponse response
    ) {
        AiContracts.CompetencyProposal proposal = response.competencyProposal();
        if (proposal.targetProject() != null) {
            return response;
        }
        Map<String, AiContracts.AnalyzedCompetency> competenciesByRef =
                proposal.competencies().stream()
                        .filter(AiContracts.AnalyzedCompetency::roadmapEligible)
                        .collect(java.util.stream.Collectors.toMap(
                                AiContracts.AnalyzedCompetency::ref,
                                item -> item,
                                (left, right) -> left,
                                java.util.LinkedHashMap::new
                        ));
        if (competenciesByRef.isEmpty()) {
            return response;
        }
        List<String> requiredRefs = proposal.requirements().stream()
                .filter(item -> "REQUIRED".equals(item.relation()))
                .map(AiContracts.AnalyzedRequirement::competencyRef)
                .filter(competenciesByRef::containsKey)
                .distinct()
                .limit(30)
                .toList();
        if (requiredRefs.isEmpty()) {
            return response;
        }
        final List<String> requiredProjectRefs = requiredRefs;
        List<String> optionalRefs = proposal.requirements().stream()
                .filter(item -> "PREFERRED".equals(item.relation()))
                .map(AiContracts.AnalyzedRequirement::competencyRef)
                .filter(competenciesByRef::containsKey)
                .filter(ref -> !requiredProjectRefs.contains(ref))
                .distinct()
                .limit(20)
                .toList();
        List<String> requiredTitles = requiredProjectRefs.stream()
                .map(competenciesByRef::get)
                .map(AiContracts.AnalyzedCompetency::title)
                .limit(8)
                .toList();
        List<String> requirementContext = proposal.requirements().stream()
                .filter(item -> "REQUIRED".equals(item.relation()))
                .map(AiContracts.AnalyzedRequirement::sourceText)
                .filter(value -> value != null && !value.isBlank())
                .distinct()
                .limit(3)
                .toList();
        String company = defaultText(response.job().companyName(), "목표 회사");
        String role = defaultText(response.job().roleTitle(), "지원 직무");
        String title = company + " " + role + " 지원 프로젝트";
        String objective = requiredTitles.isEmpty()
                ? "공고의 필수 요구사항을 하나의 실행 가능한 결과물로 증명합니다."
                : String.join(", ", requiredTitles)
                        + " 역량을 하나의 실행 가능한 결과물로 증명합니다.";
        String domainContext = requirementContext.isEmpty()
                ? company + "의 " + role + " 업무 맥락"
                : String.join(" / ", requirementContext);
        List<String> deliverables = List.of(
                "실행 가능한 " + role + " 핵심 기능 소스 코드",
                "설계 선택과 로컬 실행 방법을 정리한 README",
                "필수 역량별 테스트 또는 재현 가능한 검증 기록"
        );
        List<String> acceptanceCriteria = new ArrayList<>();
        acceptanceCriteria.add("저장소의 안내만으로 로컬 빌드와 핵심 기능 실행을 재현할 수 있음");
        requiredTitles.forEach(item -> acceptanceCriteria.add(
                item + " 요구 범위를 코드와 테스트에서 확인할 수 있음"
        ));
        acceptanceCriteria.add("실패·예외 경로와 검증 결과가 문서 또는 자동화 테스트에 남아 있음");
        AiContracts.TargetProjectBrief project = new AiContracts.TargetProjectBrief(
                title.length() > 200 ? title.substring(0, 200) : title,
                objective,
                domainContext.length() > 4000
                        ? domainContext.substring(0, 4000)
                        : domainContext,
                requiredProjectRefs,
                optionalRefs,
                deliverables,
                acceptanceCriteria.stream().limit(30).toList()
        );
        AiContracts.CompetencyProposal completedProposal =
                new AiContracts.CompetencyProposal(
                        proposal.competencies(),
                        proposal.requirements(),
                        project
                );
        return new AiContracts.AnalysisResponse(
                response.status(),
                response.question(),
                response.job(),
                response.evaluation(),
                completedProposal
        );
    }

    private void validateAnalysisQuality(AiContracts.AnalysisResponse response) {
        if (response.job().companyName() == null
                || response.job().companyName().isBlank()
                || response.job().roleTitle() == null
                || response.job().roleTitle().isBlank()
                || response.job().primaryTrack() == null
                || response.job().primaryTrack().isBlank()) {
            throw new AiServiceException(
                    "ANALYSIS_INSUFFICIENT",
                    "공고의 회사명, 직무 또는 직무 분야를 충분히 확인하지 못했습니다. 공고 원문을 확인한 뒤 다시 시도해 주세요."
            );
        }
        if (response.competencyProposal().competencies() == null
                || response.competencyProposal().competencies().isEmpty()) {
            throw new AiServiceException(
                    "ANALYSIS_INSUFFICIENT",
                    "공고에서 검토할 역량을 추출하지 못했습니다. 공고 원문을 확인한 뒤 다시 시도해 주세요."
            );
        }
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
        AiContracts.ExperienceRequirement experience =
                response.job().experienceRequirement();
        boolean experienceMet = !"REQUIRED".equals(experience.type())
                || experienceMonths >= experience.minimumMonths();
        int experienceShortage = Math.max(
                0,
                experience.minimumMonths() - experienceMonths
        );
        double coverage = counts.requiredTotal() == 0
                ? 0
                : (double) counts.requiredMet() / counts.requiredTotal();

        String verdict;
        if (counts.requiredTotal() == 0) {
            verdict = "REVIEW_REQUIRED";
        } else if (counts.requiredMet() == counts.requiredTotal() && experienceMet) {
            verdict = "APPLY_NOW";
        } else if ((!experienceMet && experienceShortage > 12)
                || coverage < 0.5) {
            verdict = "ALTERNATIVE_FIRST";
        } else {
            verdict = "STRENGTHEN_THEN_APPLY";
        }

        List<String> reasons = new ArrayList<>();
        if (counts.requiredTotal() == 0) {
            reasons.add("필수 지원 조건을 충분히 추출하지 못해 준비도를 계산하지 않았습니다.");
        }
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
            case "REVIEW_REQUIRED" ->
                    "공고 본문에서 충분한 필수 지원 조건을 추출하지 못해 준비도 판정을 보류했습니다.";
            case "APPLY_NOW" ->
                    "현재 검증된 필수 역량과 경력 조건을 기준으로 지원 가능한 상태입니다.";
            case "STRENGTHEN_THEN_APPLY" ->
                    "핵심 경로는 맞지만 일부 필수 역량을 검증한 뒤 지원하는 것이 좋습니다.";
            default ->
                    "현재 목표까지 간격이 커서 가까운 실제 공고를 함께 검토하는 것이 좋습니다.";
        };
        return new AiContracts.Evaluation(verdict, summary, List.copyOf(reasons));
    }

    private void fail(ClaimedJob job, Exception exception, String failureStage) {
        rls.write(job.userId(), jdbc -> {
            String errorCode = "INITIALIZATION".equals(failureStage)
                    && !(exception instanceof AiServiceException)
                    ? "ANALYSIS_INITIALIZATION_FAILED"
                    : classify(exception);
            int failed = jdbc.sql("""
                            update analysis_jobs
                            set
                                status = 'FAILED',
                                stage = 'FAILED',
                                stage_message = '커리어 적합도 분석을 완료하지 못했어요',
                                error_code = :errorCode,
                                error_message = :errorMessage,
                                completed_at = now(),
                                locked_until = null
                            where id = :jobId
                              and status = 'RUNNING'
                              and worker_id = :workerId
                            """)
                    .param("errorCode", errorCode)
                    .param("errorMessage", safeMessage(exception))
                    .param("workerId", workerId)
                    .param("jobId", job.id())
                    .update();
            if (failed == 0) {
                log.info("Ignoring failure from superseded analysis job {}", job.id());
                return null;
            }
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
                                '커리어 적합도 분석을 완료하지 못했어요. 오류를 확인하고 다시 시도할 수 있습니다.',
                                p.id,
                                j.id,
                                jsonb_build_object(
                                    'status', 'FAILED',
                                    'analysisJobId', cast(j.id as text),
                                    'failureStage', :failureStage,
                                    'errorMessage', :errorMessage
                                )
                            from analysis_jobs j
                            join job_postings p on p.id = j.posting_id
                            where j.id = :jobId
                              and p.conversation_id is not null
                            """)
                    .param("userId", job.userId())
                    .param("jobId", job.id())
                    .param("failureStage", failureStage)
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

    private List<String> readStringList(String value) {
        List<String> items = new ArrayList<>();
        for (tools.jackson.databind.JsonNode item : readJson(value)) {
            String text = item.stringValue("").trim();
            if (!text.isEmpty()) {
                items.add(text);
            }
        }
        return List.copyOf(items);
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

    private AiContracts.SharedPostingAnalysis parseSharedAnalysis(
            JdbcClient jdbc,
            String contentFingerprint,
            String clarificationFingerprint,
            String value
    ) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return readSharedAnalysis(value);
        } catch (RuntimeException exception) {
            String reason = safeMessage(exception);
            jdbc.sql("""
                            update posting_analysis_cache
                            set
                                invalidated_at = now(),
                                invalid_reason = :reason
                            where content_fingerprint = :contentFingerprint
                              and clarification_fingerprint = :clarificationFingerprint
                              and invalidated_at is null
                            """)
                    .param("reason", reason)
                    .param("contentFingerprint", contentFingerprint)
                    .param("clarificationFingerprint", clarificationFingerprint)
                    .update();
            log.warn(
                    "Invalidated shared posting analysis cache {}:{}: {}",
                    contentFingerprint,
                    clarificationFingerprint,
                    reason
            );
            return null;
        }
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
                        "기존 공고 요건을 재사용해 현재 준비도를 다시 계산합니다.",
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
            String sharedJson = jdbcClient.sql("""
                            select normalized_analysis::text
                            from posting_analysis_cache
                            where content_fingerprint = :contentFingerprint
                              and clarification_fingerprint = :clarificationFingerprint
                              and schema_version = 1
                              and invalidated_at is null
                            limit 1
                            """)
                    .param("contentFingerprint", key.contentFingerprint())
                    .param(
                            "clarificationFingerprint",
                            key.clarificationFingerprint()
                    )
                    .query(String.class)
                    .optional()
                    .orElse(null);
            AiContracts.SharedPostingAnalysis shared = parseSharedAnalysis(
                    jdbcClient,
                    key.contentFingerprint(),
                    key.clarificationFingerprint(),
                    sharedJson
            );
            if (shared != null) {
                jdbcClient.sql("""
                                update posting_analysis_cache
                                set
                                    use_count = use_count + 1,
                                    last_used_at = now()
                                where content_fingerprint = :contentFingerprint
                                  and clarification_fingerprint = :clarificationFingerprint
                                  and invalidated_at is null
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
                              and exists (
                                  select 1
                                  from analysis_jobs job
                                  where job.id = :analysisJobId
                                    and job.worker_id = :workerId
                              )
                            """)
                    .param("contentFingerprint", key.contentFingerprint())
                    .param(
                            "clarificationFingerprint",
                            key.clarificationFingerprint()
                    )
                    .param("analysisJobId", analysisJobId)
                    .param("workerId", workerId)
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
            int updated = jdbc.sql("""
                            update analysis_jobs
                            set
                                stage = :stage,
                                stage_message = :message,
                                locked_until = now() + interval '15 minutes'
                            where id = :jobId
                              and status = 'RUNNING'
                              and worker_id = :workerId
                            """)
                    .param("stage", stage)
                    .param("message", message)
                    .param("workerId", workerId)
                    .param("jobId", job.id())
                    .update();
            if (updated == 0) {
                throw new SupersededAnalysisException();
            }
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
            requireCurrentWorker(jdbc, job);
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

            jdbc.sql("""
                            update analysis_jobs
                            set locked_until = now() + interval '15 minutes'
                            where id = :jobId
                              and status = 'RUNNING'
                              and worker_id = :workerId
                            """)
                    .param("jobId", job.id())
                    .param("workerId", workerId)
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

    private void requireCurrentWorker(JdbcClient jdbc, ClaimedJob job) {
        boolean current = jdbc.sql("""
                        select status = 'RUNNING' and worker_id = :workerId
                        from analysis_jobs
                        where id = :jobId
                        for update
                        """)
                .param("workerId", workerId)
                .param("jobId", job.id())
                .query(Boolean.class)
                .optional()
                .orElse(false);
        if (!current) {
            throw new SupersededAnalysisException();
        }
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
        if ("INTERNAL_ERROR".equals(code)) {
            return "AI 분석 내부 처리 중 오류가 발생했습니다. 저장된 공고에서 다시 시도해 주세요.";
        }
        if ("AI_TIMEOUT".equals(code)) {
            return "AI 모델의 응답 제한 시간을 초과했습니다. 공고와 답변은 저장되어 있으니 "
                    + "잠시 후 다시 분석할 수 있습니다.";
        }
        if ("ANALYSIS_CONVERGENCE_FAILED".equals(code)) {
            return "AI 호출은 완료됐지만 분석 상태가 반복되어 결과를 확정하지 못했습니다. "
                    + "저장된 공고에서 다시 분석해 주세요.";
        }
        String message = exception.getMessage();
        if (message == null || message.isBlank()) {
            return "AI 분석을 완료하지 못했습니다.";
        }
        return message.length() > 1000 ? message.substring(0, 1000) : message;
    }

    private String defaultText(String value, String fallback) {
        return value == null || value.isBlank() ? fallback : value.trim();
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
            int questionCount,
            String workerId
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

    private static final class SupersededAnalysisException extends RuntimeException {
        private SupersededAnalysisException() {
            super("Analysis result belongs to an inactive worker");
        }
    }
}
