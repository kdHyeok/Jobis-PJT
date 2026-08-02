package com.jobiss.analysis;

import com.jobiss.db.RlsTransactionExecutor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import tools.jackson.databind.ObjectMapper;

import java.net.InetAddress;
import java.util.List;
import java.util.UUID;

@Component
@ConditionalOnProperty(name = "jobiss.ai.worker-enabled", havingValue = "true")
public class AnalysisWorker {

    private static final Logger log = LoggerFactory.getLogger(AnalysisWorker.class);

    private final JdbcClient jdbcClient;
    private final RlsTransactionExecutor rls;
    private final AiAnalysisClient aiClient;
    private final ObjectMapper objectMapper;
    private final String workerId;

    public AnalysisWorker(
            JdbcClient jdbcClient,
            RlsTransactionExecutor rls,
            AiAnalysisClient aiClient,
            ObjectMapper objectMapper
    ) {
        this.jdbcClient = jdbcClient;
        this.rls = rls;
        this.aiClient = aiClient;
        this.objectMapper = objectMapper;
        this.workerId = hostName() + "-" + UUID.randomUUID();
    }

    @Scheduled(fixedDelayString = "${jobiss.ai.poll-delay-ms:3000}")
    public void processOne() {
        ClaimedJob job = claim();
        if (job == null) {
            return;
        }

        try {
            AiContracts.AnalysisRequest request = loadRequest(job);
            AiContracts.AnalysisResponse response = aiClient.analyze(request);
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
                    || response.changeProposal() == null) {
                throw new IllegalStateException("AI response did not include a change proposal");
            }
            updateStage(job, "VALIDATING", "분석 결과와 커리어 지도 변경안을 검증하고 있어요");
            complete(job, response);
        } catch (Exception exception) {
            log.warn("Analysis job {} failed: {}", job.id(), exception.getMessage());
            fail(job, exception);
        }
    }

    private ClaimedJob claim() {
        return jdbcClient.sql("""
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
                .orElse(null);
    }

    private AiContracts.AnalysisRequest loadRequest(ClaimedJob job) {
        return rls.read(job.userId(), jdbc -> {
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
                                p.raw_text
                            from analysis_jobs j
                            join job_postings p on p.id = j.posting_id
                            where j.id = :jobId
                            """)
                    .param("jobId", job.id())
                    .query((rs, rowNum) -> new OwnedPosting(
                            rs.getObject("id", UUID.class),
                            rs.getString("source_type"),
                            rs.getString("source_url"),
                            rs.getString("raw_text")
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
                                n.id,
                                n.canonical_key,
                                n.title,
                                n.domain,
                                n.kind,
                                n.scope_definition,
                                n.level,
                                coalesce(p.status::text, 'NOT_STARTED') as progress_status
                            from career_nodes n
                            left join node_progress p on p.node_id = n.id
                            where n.graph_id = :graphId
                              and n.archived_at is null
                            order by n.rank
                            """)
                    .param("graphId", graph.id())
                    .query((rs, rowNum) -> new AiContracts.ExistingNode(
                            rs.getObject("id", UUID.class),
                            rs.getString("canonical_key"),
                            rs.getString("title"),
                            rs.getString("domain"),
                            rs.getString("kind"),
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
                        return new AiContracts.AnalysisAnswer(
                                rs.getString("question_key"),
                                rs.getString("question_text"),
                                answerValue,
                                optionLabel(rs.getString("options"), answerValue)
                        );
                    })
                    .list();

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
                            fragments
                    ),
                    questionCount,
                    answers
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

        String optionsJson = writeJson(question.options());
        rls.write(job.userId(), jdbc -> {
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
                    .param("questionKey", question.key())
                    .param("questionText", question.text())
                    .param("reason", question.reason())
                    .param("options", optionsJson)
                    .param("ordinal", request.questionCount() + 1)
                    .query(UUID.class)
                    .single();

            jdbc.sql("""
                            update analysis_jobs
                            set
                                status = 'WAITING_FOR_INPUT',
                                stage = 'WAITING_FOR_INPUT',
                                stage_message = :questionText,
                                question_count = question_count + 1,
                                worker_id = null,
                                locked_until = null
                            where id = :jobId
                            """)
                    .param("questionText", question.text())
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
                    .param("questionText", question.text())
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
                    .param("questionText", question.text())
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

    private void complete(ClaimedJob job, AiContracts.AnalysisResponse response) {
        String resultJson = objectMapper.writeValueAsString(response);
        String proposalJson = objectMapper.writeValueAsString(response.changeProposal());

        rls.write(job.userId(), jdbc -> {
            jdbc.sql("""
                            update job_postings p
                            set
                                company_name = :companyName,
                                role_title = :roleTitle,
                                employment_type = :employmentType,
                                experience_text = :experienceText,
                                parsed_data = cast(:parsedData as jsonb)
                            from analysis_jobs j
                            where j.id = :jobId
                              and p.id = j.posting_id
                            """)
                    .param("companyName", response.job().companyName())
                    .param("roleTitle", response.job().roleTitle())
                    .param("employmentType", response.job().employmentType())
                    .param("experienceText", response.job().experienceText())
                    .param("parsedData", writeJson(response.job().parsedData()))
                    .param("jobId", job.id())
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
                                '변경 내용을 확인한 뒤 커리어 지도에 반영해 주세요.',
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
                                '공고 분석이 완료됐어요. 지원 판단과 지도 변경안을 확인해 주세요.',
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
                    .param("evaluation", writeJson(response.evaluation()))
                    .update();

            jdbc.sql("select finish_analysis_job(:jobId, :userId)")
                    .param("jobId", job.id())
                    .param("userId", job.userId())
                    .query(Object.class)
                    .optional();
            return null;
        });
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
                                '공고 분석을 완료하지 못했어요. 오류를 확인하고 다시 시도할 수 있습니다.',
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

    private String classify(Exception exception) {
        if (exception instanceof AiServiceException aiException) {
            return aiException.code();
        }
        String name = exception.getClass().getSimpleName();
        return name.length() > 80 ? "AI_ANALYSIS_FAILED" : name.toUpperCase();
    }

    private String safeMessage(Exception exception) {
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
            String rawText
    ) {
    }
}
