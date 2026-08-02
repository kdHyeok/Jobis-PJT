package com.jobiss.analysis;

import com.jobiss.common.ApiException;
import com.jobiss.db.RlsTransactionExecutor;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

@Service
public class AnalysisJobService {

    private final RlsTransactionExecutor rls;
    private final ObjectMapper objectMapper;
    private final AiUsageLimitService usageLimit;

    public AnalysisJobService(
            RlsTransactionExecutor rls,
            ObjectMapper objectMapper,
            AiUsageLimitService usageLimit
    ) {
        this.rls = rls;
        this.objectMapper = objectMapper;
        this.usageLimit = usageLimit;
    }

    public AnalysisJobView get(UUID userId, UUID jobId) {
        return rls.read(userId, jdbc -> jdbc.sql("""
                        select
                            j.id,
                            j.posting_id,
                            j.status,
                            j.stage,
                            j.stage_message,
                            j.attempt_count,
                            j.question_count,
                            j.error_code,
                            j.error_message,
                            j.result_data,
                            j.created_at,
                            j.started_at,
                            j.completed_at,
                            c.id as change_set_id,
                            c.status as change_set_status,
                            c.proposal,
                            q.id as question_id,
                            q.question_key,
                            q.question_text,
                            q.reason as question_reason,
                            q.options::text as question_options,
                            q.ordinal as question_ordinal
                        from analysis_jobs j
                        left join graph_change_sets c on c.analysis_job_id = j.id
                        left join lateral (
                            select id, question_key, question_text, reason, options, ordinal
                            from analysis_questions
                            where analysis_job_id = j.id
                              and status = 'PENDING'
                            order by ordinal desc
                            limit 1
                        ) q on true
                        where j.id = :jobId
                        """)
                .param("jobId", jobId)
                .query((rs, rowNum) -> new AnalysisJobView(
                        rs.getObject("id", UUID.class),
                        rs.getObject("posting_id", UUID.class),
                        rs.getString("status"),
                        rs.getString("stage"),
                        rs.getString("stage_message"),
                        rs.getInt("attempt_count"),
                        rs.getInt("question_count"),
                        rs.getString("error_code"),
                        rs.getString("error_message"),
                        readJson(rs.getString("result_data")),
                        rs.getObject("change_set_id", UUID.class),
                        rs.getString("change_set_status"),
                        readJson(rs.getString("proposal")),
                        rs.getObject("created_at", OffsetDateTime.class),
                        rs.getObject("started_at", OffsetDateTime.class),
                        rs.getObject("completed_at", OffsetDateTime.class),
                        pendingQuestion(rs)
                ))
                .optional()
                .orElseThrow(() -> new ApiException(
                        HttpStatus.NOT_FOUND,
                        "ANALYSIS_JOB_NOT_FOUND",
                        "분석 작업을 찾을 수 없습니다."
                )));
    }

    public List<AnalysisJobView> list(UUID userId, String status, int limit) {
        int safeLimit = Math.max(1, Math.min(limit, 100));
        String normalizedStatus = status == null ? "" : status.trim().toUpperCase();
        return rls.read(userId, jdbc -> jdbc.sql("""
                        select
                            j.id,
                            j.posting_id,
                            j.status,
                            j.stage,
                            j.stage_message,
                            j.attempt_count,
                            j.question_count,
                            j.error_code,
                            j.error_message,
                            j.result_data,
                            j.created_at,
                            j.started_at,
                            j.completed_at,
                            c.id as change_set_id,
                            c.status as change_set_status,
                            c.proposal,
                            q.id as question_id,
                            q.question_key,
                            q.question_text,
                            q.reason as question_reason,
                            q.options::text as question_options,
                            q.ordinal as question_ordinal
                        from analysis_jobs j
                        left join graph_change_sets c on c.analysis_job_id = j.id
                        left join lateral (
                            select id, question_key, question_text, reason, options, ordinal
                            from analysis_questions
                            where analysis_job_id = j.id
                              and status = 'PENDING'
                            order by ordinal desc
                            limit 1
                        ) q on true
                        where (:status = '' or j.status::text = :status)
                        order by j.created_at desc
                        limit :limit
                        """)
                .param("status", normalizedStatus)
                .param("limit", safeLimit)
                .query((rs, rowNum) -> new AnalysisJobView(
                        rs.getObject("id", UUID.class),
                        rs.getObject("posting_id", UUID.class),
                        rs.getString("status"),
                        rs.getString("stage"),
                        rs.getString("stage_message"),
                        rs.getInt("attempt_count"),
                        rs.getInt("question_count"),
                        rs.getString("error_code"),
                        rs.getString("error_message"),
                        readJson(rs.getString("result_data")),
                        rs.getObject("change_set_id", UUID.class),
                        rs.getString("change_set_status"),
                        readJson(rs.getString("proposal")),
                        rs.getObject("created_at", OffsetDateTime.class),
                        rs.getObject("started_at", OffsetDateTime.class),
                        rs.getObject("completed_at", OffsetDateTime.class),
                        pendingQuestion(rs)
                ))
                .list());
    }

    public void retry(UUID userId, UUID jobId) {
        usageLimit.consume(userId, AiUsageLimitService.Kind.ANALYSIS);
        rls.write(userId, jdbc -> {
            int updated = jdbc.sql("""
                            update analysis_jobs
                            set
                                status = 'QUEUED',
                                stage = 'QUEUED',
                                stage_message = '분석 재시도 대기 중',
                                worker_id = null,
                                locked_until = null,
                                error_code = null,
                                error_message = null,
                                completed_at = null
                            where id = :jobId
                              and status = 'FAILED'
                              and attempt_count < 3
                            """)
                    .param("jobId", jobId)
                    .update();
            if (updated == 0) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "ANALYSIS_NOT_RETRYABLE",
                        "현재 상태에서는 분석을 재시도할 수 없습니다."
                );
            }
            jdbc.sql("select requeue_analysis_job(:jobId, :userId)")
                    .param("jobId", jobId)
                    .param("userId", userId)
                    .query(Object.class)
                    .optional();
            return null;
        });
    }

    public void answerQuestion(
            UUID userId,
            UUID jobId,
            UUID questionId,
            String answerValue
    ) {
        String normalizedAnswer = answerValue == null ? "" : answerValue.trim();
        if (normalizedAnswer.isEmpty() || normalizedAnswer.length() > 120) {
            throw new ApiException(
                    HttpStatus.BAD_REQUEST,
                    "INVALID_ANALYSIS_ANSWER",
                    "제공된 선택지 중 하나를 선택해 주세요."
            );
        }

        rls.write(userId, jdbc -> {
            QuestionForAnswer question = jdbc.sql("""
                            select
                                j.status::text as job_status,
                                q.status as question_status,
                                q.question_text,
                                q.options::text
                            from analysis_jobs j
                            join analysis_questions q
                              on q.analysis_job_id = j.id
                             and q.user_id = j.user_id
                            where j.id = :jobId
                              and q.id = :questionId
                            for update of j, q
                            """)
                    .param("jobId", jobId)
                    .param("questionId", questionId)
                    .query((rs, rowNum) -> new QuestionForAnswer(
                            rs.getString("job_status"),
                            rs.getString("question_status"),
                            rs.getString("question_text"),
                            readJson(rs.getString("options"))
                    ))
                    .optional()
                    .orElseThrow(() -> new ApiException(
                            HttpStatus.NOT_FOUND,
                            "ANALYSIS_QUESTION_NOT_FOUND",
                            "분석 질문을 찾을 수 없습니다."
                    ));

            if (!"WAITING_FOR_INPUT".equals(question.jobStatus())
                    || !"PENDING".equals(question.questionStatus())) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "ANALYSIS_QUESTION_NOT_PENDING",
                        "이미 답변했거나 현재 답변을 기다리는 질문이 아닙니다."
                );
            }

            String answerLabel = null;
            for (JsonNode option : question.options()) {
                if (normalizedAnswer.equals(option.path("value").stringValue(""))) {
                    answerLabel = option.path("label").stringValue(normalizedAnswer);
                    break;
                }
            }
            if (answerLabel == null) {
                throw new ApiException(
                        HttpStatus.BAD_REQUEST,
                        "INVALID_ANALYSIS_ANSWER",
                        "제공된 선택지 중 하나를 선택해 주세요."
                );
            }

            jdbc.sql("""
                            update analysis_questions
                            set
                                status = 'ANSWERED',
                                answer_value = :answerValue,
                                answered_at = now()
                            where id = :questionId
                            """)
                    .param("answerValue", normalizedAnswer)
                    .param("questionId", questionId)
                    .update();

            jdbc.sql("""
                            update analysis_jobs
                            set
                                status = 'QUEUED',
                                stage = 'QUEUED',
                                stage_message = '답변을 반영해 분석을 이어갈게요',
                                worker_id = null,
                                locked_until = null,
                                error_code = null,
                                error_message = null,
                                completed_at = null
                            where id = :jobId
                            """)
                    .param("jobId", jobId)
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
                                'USER',
                                'ANALYSIS_STATUS',
                                :answerLabel,
                                p.id,
                                j.id,
                                jsonb_build_object(
                                    'status', 'ANSWERED',
                                    'analysisJobId', cast(j.id as text),
                                    'questionId', cast(:questionId as text),
                                    'answerValue', :answerValue
                                )
                            from analysis_jobs j
                            join job_postings p on p.id = j.posting_id
                            where j.id = :jobId
                              and p.conversation_id is not null
                            """)
                    .param("userId", userId)
                    .param("answerLabel", answerLabel)
                    .param("questionId", questionId)
                    .param("answerValue", normalizedAnswer)
                    .param("jobId", jobId)
                    .update();

            jdbc.sql("select requeue_analysis_job(:jobId, :userId)")
                    .param("jobId", jobId)
                    .param("userId", userId)
                    .query(Object.class)
                    .optional();
            return null;
        });
    }

    private JsonNode readJson(String value) {
        if (value == null) {
            return null;
        }
        try {
            return objectMapper.readTree(value);
        } catch (RuntimeException exception) {
            throw new IllegalStateException("Stored analysis JSON is invalid", exception);
        }
    }

    private PendingQuestion pendingQuestion(ResultSet rs) throws SQLException {
        UUID questionId = rs.getObject("question_id", UUID.class);
        if (questionId == null) {
            return null;
        }
        return new PendingQuestion(
                questionId,
                rs.getString("question_key"),
                rs.getString("question_text"),
                rs.getString("question_reason"),
                readJson(rs.getString("question_options")),
                rs.getInt("question_ordinal")
        );
    }

    public record AnalysisJobView(
            UUID id,
            UUID postingId,
            String status,
            String stage,
            String stageMessage,
            int attemptCount,
            int questionCount,
            String errorCode,
            String errorMessage,
            JsonNode result,
            UUID changeSetId,
            String changeSetStatus,
            JsonNode proposal,
            OffsetDateTime createdAt,
            OffsetDateTime startedAt,
            OffsetDateTime completedAt,
            PendingQuestion pendingQuestion
    ) {
    }

    public record PendingQuestion(
            UUID id,
            String key,
            String text,
            String reason,
            JsonNode options,
            int ordinal
    ) {
    }

    private record QuestionForAnswer(
            String jobStatus,
            String questionStatus,
            String questionText,
            JsonNode options
    ) {
    }
}
