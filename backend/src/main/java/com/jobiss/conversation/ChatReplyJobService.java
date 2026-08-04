package com.jobiss.conversation;

import com.jobiss.analysis.AiUsageLimitService;
import com.jobiss.common.ApiException;
import com.jobiss.db.RlsTransactionExecutor;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

@Service
public class ChatReplyJobService {

    private final RlsTransactionExecutor rls;
    private final AiUsageLimitService usageLimit;
    private final ObjectMapper objectMapper;

    public ChatReplyJobService(
            RlsTransactionExecutor rls,
            AiUsageLimitService usageLimit,
            ObjectMapper objectMapper
    ) {
        this.rls = rls;
        this.usageLimit = usageLimit;
        this.objectMapper = objectMapper;
    }

    public UUID enqueue(UUID userId, UUID conversationId, UUID triggerMessageId) {
        usageLimit.consume(userId, AiUsageLimitService.Kind.CHAT);
        return rls.write(userId, jdbc -> jdbc.sql("""
                        insert into chat_reply_jobs (
                            user_id,
                            conversation_id,
                            trigger_message_id
                        )
                        values (:userId, :conversationId, :triggerMessageId)
                        on conflict (trigger_message_id)
                        do update set trigger_message_id = excluded.trigger_message_id
                        returning id
                        """)
                .param("userId", userId)
                .param("conversationId", conversationId)
                .param("triggerMessageId", triggerMessageId)
                .query(UUID.class)
                .single());
    }

    public ChatReplyJobView get(UUID userId, UUID jobId) {
        return rls.read(userId, jdbc -> jdbc.sql("""
                        select
                            id,
                            conversation_id,
                            trigger_message_id,
                            status,
                            stage,
                            stage_message,
                            attempt_count,
                            error_code,
                            error_message,
                            created_at,
                            started_at,
                            completed_at,
                            (
                                select coalesce(
                                    jsonb_agg(event_data order by sequence),
                                    '[]'::jsonb
                                )::text
                                from chat_reply_agent_events
                                where chat_reply_job_id = chat_reply_jobs.id
                            ) as progress_steps
                        from chat_reply_jobs
                        where id = :jobId
                        """)
                .param("jobId", jobId)
                .query(this::map)
                .optional()
                .orElseThrow(ChatReplyJobService::notFound));
    }

    public List<ChatReplyJobView> list(UUID userId, UUID conversationId) {
        return rls.read(userId, jdbc -> jdbc.sql("""
                        select
                            id,
                            conversation_id,
                            trigger_message_id,
                            status,
                            stage,
                            stage_message,
                            attempt_count,
                            error_code,
                            error_message,
                            created_at,
                            started_at,
                            completed_at,
                            (
                                select coalesce(
                                    jsonb_agg(event_data order by sequence),
                                    '[]'::jsonb
                                )::text
                                from chat_reply_agent_events
                                where chat_reply_job_id = chat_reply_jobs.id
                            ) as progress_steps
                        from chat_reply_jobs
                        where conversation_id = :conversationId
                        order by created_at, id
                        limit 200
                        """)
                .param("conversationId", conversationId)
                .query(this::map)
                .list());
    }

    public void retry(UUID userId, UUID jobId) {
        usageLimit.consume(userId, AiUsageLimitService.Kind.CHAT);
        rls.write(userId, jdbc -> {
            int updated = jdbc.sql("""
                            update chat_reply_jobs
                            set
                                status = 'QUEUED',
                                stage = 'QUEUED',
                                stage_message = '답변 재시도 대기 중',
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
                        "CHAT_REPLY_NOT_RETRYABLE",
                        "현재 상태에서는 AI 답변을 재시도할 수 없습니다."
                );
            }
            jdbc.sql("select requeue_chat_reply_job(:jobId, :userId)")
                    .param("jobId", jobId)
                    .param("userId", userId)
                    .query(Object.class)
                    .optional();
            return null;
        });
    }

    private ChatReplyJobView map(java.sql.ResultSet rs, int rowNum)
            throws java.sql.SQLException {
        return new ChatReplyJobView(
                rs.getObject("id", UUID.class),
                rs.getObject("conversation_id", UUID.class),
                rs.getObject("trigger_message_id", UUID.class),
                rs.getString("status"),
                rs.getString("stage"),
                rs.getString("stage_message"),
                rs.getInt("attempt_count"),
                rs.getString("error_code"),
                rs.getString("error_message"),
                rs.getObject("created_at", OffsetDateTime.class),
                rs.getObject("started_at", OffsetDateTime.class),
                rs.getObject("completed_at", OffsetDateTime.class),
                readJson(rs.getString("progress_steps"))
        );
    }

    /**
     * 저장된 진행 단계를 그대로 통과시킨다 — AI 가 만든 화자 키·문구를 백엔드가 다시
     * 해석하지 않는다(분석 작업의 progressEvents 와 같은 규약).
     */
    private JsonNode readJson(String value) {
        if (value == null) {
            return null;
        }
        try {
            return objectMapper.readTree(value);
        } catch (RuntimeException exception) {
            throw new IllegalStateException("Stored chat progress JSON is invalid", exception);
        }
    }

    private static ApiException notFound() {
        return new ApiException(
                HttpStatus.NOT_FOUND,
                "CHAT_REPLY_JOB_NOT_FOUND",
                "AI 답변 작업을 찾을 수 없습니다."
        );
    }

    public record ChatReplyJobView(
            UUID id,
            UUID conversationId,
            UUID triggerMessageId,
            String status,
            String stage,
            String stageMessage,
            int attemptCount,
            String errorCode,
            String errorMessage,
            OffsetDateTime createdAt,
            OffsetDateTime startedAt,
            OffsetDateTime completedAt,
            /**
             * 이 턴에서 어느 에이전트가 무엇을 했는지 순서대로 —
             * {@code [{agent, step, label, detail, elapsedMs}, …]}. 화면은 {@code agent} 키로
             * 에이전트별 색·로고를 붙여 말풍선을 그린다.
             */
            JsonNode progressSteps
    ) {
    }
}
