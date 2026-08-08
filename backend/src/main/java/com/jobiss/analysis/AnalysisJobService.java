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
    private final AnalysisTaskRegistry taskRegistry;
    private final AiAnalysisClient aiClient;

    public AnalysisJobService(
            RlsTransactionExecutor rls,
            ObjectMapper objectMapper,
            AiUsageLimitService usageLimit,
            AnalysisTaskRegistry taskRegistry,
            AiAnalysisClient aiClient
    ) {
        this.rls = rls;
        this.objectMapper = objectMapper;
        this.usageLimit = usageLimit;
        this.taskRegistry = taskRegistry;
        this.aiClient = aiClient;
    }

    public AnalysisJobView get(UUID userId, UUID jobId) {
        return rls.read(userId, jdbc -> jdbc.sql("""
                        select
                            j.id,
                            j.posting_id,
                            j.status,
                            j.analysis_provider,
                            j.stage,
                            j.stage_message,
                            case
                                when j.status = 'QUEUED'
                                    then count_analysis_jobs_ahead(j.id, :userId)
                                else null
                            end as queue_position,
                            j.attempt_count,
                            j.question_count,
                            j.error_code,
                            j.error_message,
                            j.result_data,
                            j.created_at,
                            j.started_at,
                            j.completed_at,
                            coalesce(c.id, v3_proposal.id) as change_set_id,
                            coalesce(c.status::text, v3_proposal.status) as change_set_status,
                            coalesce(c.proposal, v3_proposal.proposal) as proposal,
                            e.events::text as progress_events,
                            q.id as question_id,
                            q.question_key,
                            q.question_text,
                            q.reason as question_reason,
                            q.input_type as question_input_type,
                            q.options::text as question_options,
                            q.related_requirement_ids::text as question_requirement_ids,
                            q.absence_scope as question_absence_scope,
                            q.ordinal as question_ordinal,
                            h.history::text as question_history
                        from analysis_jobs j
                        left join graph_change_sets c on c.analysis_job_id = j.id
                        left join ai_v3_roadmap_proposals v3_proposal
                          on v3_proposal.analysis_job_id = j.id
                        left join lateral (
                            select coalesce(
                                jsonb_agg(event_data order by sequence),
                                '[]'::jsonb
                            ) as events
                            from analysis_agent_events
                            where analysis_job_id = j.id
                        ) e on true
                        left join lateral (
                            select id, question_key, question_text, reason, input_type, options,
                                   related_requirement_ids, absence_scope, ordinal
                            from analysis_questions
                            where analysis_job_id = j.id
                              and status = 'PENDING'
                            order by ordinal desc
                            limit 1
                        ) q on true
                        left join lateral (
                            select coalesce(
                                jsonb_agg(
                                    jsonb_build_object(
                                        'id', id,
                                        'key', question_key,
                                        'text', question_text,
                                        'inputType', input_type,
                                        'answerValue', answer_value,
                                        'answerStatus', answer_status,
                                        'answeredAt', answered_at,
                                        'ordinal', ordinal
                                    )
                                    order by ordinal
                                ),
                                '[]'::jsonb
                            ) as history
                            from analysis_questions
                            where analysis_job_id = j.id
                              and status = 'ANSWERED'
                        ) h on true
                        where j.id = :jobId
                        """)
                .param("jobId", jobId)
                .param("userId", userId)
                .query((rs, rowNum) -> new AnalysisJobView(
                        rs.getObject("id", UUID.class),
                        rs.getObject("posting_id", UUID.class),
                        rs.getString("status"),
                        rs.getString("analysis_provider"),
                        rs.getString("stage"),
                        rs.getString("stage_message"),
                        (Integer) rs.getObject("queue_position"),
                        rs.getInt("attempt_count"),
                        rs.getInt("question_count"),
                        rs.getString("error_code"),
                        rs.getString("error_message"),
                        readJson(rs.getString("result_data")),
                        rs.getObject("change_set_id", UUID.class),
                        rs.getString("change_set_status"),
                        readJson(rs.getString("proposal")),
                        readJson(rs.getString("progress_events")),
                        rs.getObject("created_at", OffsetDateTime.class),
                        rs.getObject("started_at", OffsetDateTime.class),
                        rs.getObject("completed_at", OffsetDateTime.class),
                        pendingQuestion(rs),
                        readJson(rs.getString("question_history"))
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
                            j.analysis_provider,
                            j.stage,
                            j.stage_message,
                            case
                                when j.status = 'QUEUED'
                                    then count_analysis_jobs_ahead(j.id, :userId)
                                else null
                            end as queue_position,
                            j.attempt_count,
                            j.question_count,
                            j.error_code,
                            j.error_message,
                            j.result_data,
                            j.created_at,
                            j.started_at,
                            j.completed_at,
                            coalesce(c.id, v3_proposal.id) as change_set_id,
                            coalesce(c.status::text, v3_proposal.status) as change_set_status,
                            coalesce(c.proposal, v3_proposal.proposal) as proposal,
                            e.events::text as progress_events,
                            q.id as question_id,
                            q.question_key,
                            q.question_text,
                            q.reason as question_reason,
                            q.input_type as question_input_type,
                            q.options::text as question_options,
                            q.related_requirement_ids::text as question_requirement_ids,
                            q.absence_scope as question_absence_scope,
                            q.ordinal as question_ordinal,
                            h.history::text as question_history
                        from analysis_jobs j
                        left join graph_change_sets c on c.analysis_job_id = j.id
                        left join ai_v3_roadmap_proposals v3_proposal
                          on v3_proposal.analysis_job_id = j.id
                        left join lateral (
                            select coalesce(
                                jsonb_agg(event_data order by sequence),
                                '[]'::jsonb
                            ) as events
                            from analysis_agent_events
                            where analysis_job_id = j.id
                        ) e on true
                        left join lateral (
                            select id, question_key, question_text, reason, input_type, options,
                                   related_requirement_ids, absence_scope, ordinal
                            from analysis_questions
                            where analysis_job_id = j.id
                              and status = 'PENDING'
                            order by ordinal desc
                            limit 1
                        ) q on true
                        left join lateral (
                            select coalesce(
                                jsonb_agg(
                                    jsonb_build_object(
                                        'id', id,
                                        'key', question_key,
                                        'text', question_text,
                                        'inputType', input_type,
                                        'answerValue', answer_value,
                                        'answerStatus', answer_status,
                                        'answeredAt', answered_at,
                                        'ordinal', ordinal
                                    )
                                    order by ordinal
                                ),
                                '[]'::jsonb
                            ) as history
                            from analysis_questions
                            where analysis_job_id = j.id
                              and status = 'ANSWERED'
                        ) h on true
                        where (:status = '' or j.status::text = :status)
                        order by j.created_at desc
                        limit :limit
                        """)
                .param("userId", userId)
                .param("status", normalizedStatus)
                .param("limit", safeLimit)
                .query((rs, rowNum) -> new AnalysisJobView(
                        rs.getObject("id", UUID.class),
                        rs.getObject("posting_id", UUID.class),
                        rs.getString("status"),
                        rs.getString("analysis_provider"),
                        rs.getString("stage"),
                        rs.getString("stage_message"),
                        (Integer) rs.getObject("queue_position"),
                        rs.getInt("attempt_count"),
                        rs.getInt("question_count"),
                        rs.getString("error_code"),
                        rs.getString("error_message"),
                        readJson(rs.getString("result_data")),
                        rs.getObject("change_set_id", UUID.class),
                        rs.getString("change_set_status"),
                        readJson(rs.getString("proposal")),
                        readJson(rs.getString("progress_events")),
                        rs.getObject("created_at", OffsetDateTime.class),
                        rs.getObject("started_at", OffsetDateTime.class),
                        rs.getObject("completed_at", OffsetDateTime.class),
                        pendingQuestion(rs),
                        readJson(rs.getString("question_history"))
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
                              and status in ('FAILED', 'CANCELLED')
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

    public void cancel(UUID userId, UUID jobId) {
        String provider = rls.write(userId, jdbc -> {
            String analysisProvider = jdbc.sql("""
                            select analysis_provider
                            from analysis_jobs
                            where id = :jobId
                            for update
                            """)
                    .param("jobId", jobId)
                    .query(String.class)
                    .optional()
                    .orElseThrow(() -> new ApiException(
                            HttpStatus.NOT_FOUND,
                            "ANALYSIS_JOB_NOT_FOUND",
                            "분석 작업을 찾을 수 없습니다."
                    ));
            int updated = jdbc.sql("""
                            update analysis_jobs
                            set
                                status = 'CANCELLED',
                                stage = 'CANCELLED',
                                stage_message = '사용자가 분석을 취소했어요',
                                worker_id = null,
                                locked_until = null,
                                error_code = null,
                                error_message = null,
                                completed_at = now()
                            where id = :jobId
                              and status in (
                                  'QUEUED',
                                  'RUNNING',
                                  'WAITING_FOR_INPUT'
                              )
                            """)
                    .param("jobId", jobId)
                    .update();
            if (updated == 0) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "ANALYSIS_NOT_CANCELLABLE",
                        "현재 상태에서는 분석을 취소할 수 없습니다."
                );
            }

            jdbc.sql("select finish_analysis_job(:jobId, :userId)")
                    .param("jobId", jobId)
                    .param("userId", userId)
                    .query(Object.class)
                    .optional();
            jdbc.sql("""
                            delete from posting_analysis_leases
                            where owner_analysis_job_id = :jobId
                            """)
                    .param("jobId", jobId)
                    .update();
            return analysisProvider;
        });
        taskRegistry.cancel(jobId);
        if ("UNIFIED".equals(provider)) {
            try {
                aiClient.cancelCareerPipeline(jobId);
            } catch (RuntimeException ignored) {
                // The database terminal state is authoritative. A late pipeline
                // result is rejected by worker ownership checks even if the
                // best-effort process interruption endpoint is unavailable.
            }
        }
    }

    public void answerQuestion(
            UUID userId,
            UUID jobId,
            UUID questionId,
            String answerValue,
            String requestedAnswerStatus
    ) {
        String normalizedAnswer = answerValue == null ? "" : answerValue.trim();
        if (normalizedAnswer.isEmpty() || normalizedAnswer.length() > 2000) {
            throw new ApiException(
                    HttpStatus.BAD_REQUEST,
                    "INVALID_ANALYSIS_ANSWER",
                    "답변은 1자 이상 2,000자 이하로 입력해 주세요."
            );
        }

        boolean cancelled = rls.write(userId, jdbc -> {
            QuestionForAnswer question = jdbc.sql("""
                            select
                                j.status::text as job_status,
                                j.analysis_provider,
                                q.status as question_status,
                                q.question_key,
                                q.question_text,
                                q.input_type,
                                q.absence_scope,
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
                            rs.getString("analysis_provider"),
                            rs.getString("question_status"),
                            rs.getString("question_key"),
                            rs.getString("question_text"),
                            rs.getString("input_type"),
                            rs.getString("absence_scope"),
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

            boolean textQuestion = "TEXT".equals(question.inputType());
            String answerLabel;
            String canonicalAnswer;
            if (textQuestion) {
                answerLabel = normalizedAnswer;
                canonicalAnswer = normalizedAnswer;
            } else {
                if (normalizedAnswer.length() > 120) {
                    throw new ApiException(
                            HttpStatus.BAD_REQUEST,
                            "INVALID_ANALYSIS_ANSWER",
                            "제공된 선택지 중 하나를 선택해 주세요."
                    );
                }
                answerLabel = null;
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
                canonicalAnswer = "UNIFIED".equals(question.analysisProvider())
                        ? normalizedAnswer
                        : AnalysisClarificationNormalizer.answerValue(
                                AnalysisClarificationNormalizer.questionKey(
                                        question.questionKey()
                                ),
                                normalizedAnswer,
                                answerLabel
                        );
            }
            String answerStatus = AnalysisClarificationNormalizer.answerStatus(
                    requestedAnswerStatus,
                    question.absenceScope(),
                    answerLabel
            );
            boolean postingReviewCancellation =
                    "UNIFIED".equals(question.analysisProvider())
                            && question.questionKey().startsWith("posting-review-")
                            && "CANCEL".equals(canonicalAnswer);

            jdbc.sql("""
                            update analysis_questions
                            set
                                status = 'ANSWERED',
                                answer_value = :answerValue,
                                answer_status = :answerStatus,
                                answered_at = now()
                            where id = :questionId
                            """)
                    .param("answerValue", canonicalAnswer)
                    .param("answerStatus", answerStatus)
                    .param("questionId", questionId)
                    .update();

            if (postingReviewCancellation) {
                jdbc.sql("""
                                update analysis_jobs
                                set
                                    status = 'CANCELLED',
                                    stage = 'CANCELLED',
                                    stage_message = '사용자가 분석을 취소했어요',
                                    worker_id = null,
                                    locked_until = null,
                                    error_code = null,
                                    error_message = null,
                                    completed_at = now()
                                where id = :jobId
                                """)
                        .param("jobId", jobId)
                        .update();
            } else {
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
                                'USER',
                                'ANALYSIS_STATUS',
                                :answerLabel,
                                p.id,
                                j.id,
                                jsonb_build_object(
                                    'status', :messageStatus,
                                    'analysisJobId', cast(j.id as text),
                                    'questionId', cast(:questionId as text),
                                    'answerValue', :answerValue,
                                    'answerStatus', :answerStatus
                                )
                            from analysis_jobs j
                            join job_postings p on p.id = j.posting_id
                            where j.id = :jobId
                              and p.conversation_id is not null
                            """)
                    .param("userId", userId)
                    .param("answerLabel", answerLabel)
                    .param(
                            "messageStatus",
                            postingReviewCancellation ? "CANCELLED" : "ANSWERED"
                    )
                    .param("questionId", questionId)
                    .param("answerValue", canonicalAnswer)
                    .param("answerStatus", answerStatus)
                    .param("jobId", jobId)
                    .update();

            if (postingReviewCancellation) {
                jdbc.sql("select finish_analysis_job(:jobId, :userId)")
                        .param("jobId", jobId)
                        .param("userId", userId)
                        .query(Object.class)
                        .optional();
                jdbc.sql("""
                                delete from posting_analysis_leases
                                where owner_analysis_job_id = :jobId
                                """)
                        .param("jobId", jobId)
                        .update();
            } else {
                jdbc.sql("select requeue_analysis_job(:jobId, :userId)")
                        .param("jobId", jobId)
                        .param("userId", userId)
                        .query(Object.class)
                        .optional();
            }
            return postingReviewCancellation;
        });
        if (cancelled) {
            taskRegistry.cancel(jobId);
        }
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
                rs.getString("question_input_type"),
                readJson(rs.getString("question_options")),
                readJson(rs.getString("question_requirement_ids")),
                rs.getString("question_absence_scope"),
                rs.getInt("question_ordinal")
        );
    }

    public record AnalysisJobView(
            UUID id,
            UUID postingId,
            String status,
            String analysisProvider,
            String stage,
            String stageMessage,
            Integer queuePosition,
            int attemptCount,
            int questionCount,
            String errorCode,
            String errorMessage,
            JsonNode result,
            UUID changeSetId,
            String changeSetStatus,
            JsonNode proposal,
            JsonNode progressEvents,
            OffsetDateTime createdAt,
            OffsetDateTime startedAt,
            OffsetDateTime completedAt,
            PendingQuestion pendingQuestion,
            JsonNode questionHistory
    ) {
    }

    public record PendingQuestion(
            UUID id,
            String key,
            String text,
            String reason,
            String inputType,
            JsonNode options,
            JsonNode relatedRequirementIds,
            String absenceScope,
            int ordinal
    ) {
    }

    private record QuestionForAnswer(
            String jobStatus,
            String analysisProvider,
            String questionStatus,
            String questionKey,
            String questionText,
            String inputType,
            String absenceScope,
            JsonNode options
    ) {
    }
}
