package com.jobiss.conversation;

import com.jobiss.analysis.AiAnalysisClient;
import com.jobiss.analysis.AiContracts;
import com.jobiss.analysis.AiServiceException;
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
public class ChatReplyWorker {

    private static final Logger log = LoggerFactory.getLogger(ChatReplyWorker.class);

    private final JdbcClient jdbcClient;
    private final RlsTransactionExecutor rls;
    private final AiAnalysisClient aiClient;
    private final ObjectMapper objectMapper;
    private final String workerId;

    public ChatReplyWorker(
            JdbcClient jdbcClient,
            RlsTransactionExecutor rls,
            AiAnalysisClient aiClient,
            ObjectMapper objectMapper
    ) {
        this.jdbcClient = jdbcClient;
        this.rls = rls;
        this.aiClient = aiClient;
        this.objectMapper = objectMapper;
        this.workerId = hostName() + "-chat-" + UUID.randomUUID();
    }

    @Scheduled(fixedDelayString = "${jobiss.ai.poll-delay-ms:3000}")
    public void processOne() {
        ClaimedJob job = claim();
        if (job == null) {
            return;
        }
        try {
            AiContracts.ChatRequest request = loadRequest(job);
            AiContracts.ChatResponse response = aiClient.chat(request);
            if (response == null || response.message() == null || response.message().isBlank()) {
                throw new IllegalStateException("AI response did not include a message");
            }
            complete(job, response);
        } catch (Exception exception) {
            log.warn("Chat reply job {} failed: {}", job.id(), exception.getMessage());
            fail(job, exception);
        }
    }

    private ClaimedJob claim() {
        return jdbcClient.sql("""
                        select id, user_id, attempt_count
                        from claim_chat_reply_job(:workerId)
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

    private AiContracts.ChatRequest loadRequest(ClaimedJob job) {
        return rls.write(job.userId(), jdbc -> {
            Trigger trigger = jdbc.sql("""
                            select j.conversation_id, j.trigger_message_id, m.created_at
                            from chat_reply_jobs j
                            join conversation_messages m on m.id = j.trigger_message_id
                            where j.id = :jobId
                            """)
                    .param("jobId", job.id())
                    .query((rs, rowNum) -> new Trigger(
                            rs.getObject("conversation_id", UUID.class),
                            rs.getObject("trigger_message_id", UUID.class),
                            rs.getObject("created_at", java.time.OffsetDateTime.class)
                    ))
                    .single();

            jdbc.sql("""
                            update chat_reply_jobs
                            set
                                status = 'RUNNING',
                                stage = 'CONTEXT',
                                stage_message = '대화와 커리어 맥락을 정리하고 있어요',
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

            String displayName = jdbc.sql("select display_name from users where id = :userId")
                    .param("userId", job.userId())
                    .query(String.class)
                    .single();
            List<AiContracts.ChatMessage> messages = jdbc.sql("""
                            select role, content
                            from (
                                select role, content, created_at, id
                                from conversation_messages
                                where conversation_id = :conversationId
                                  and role in ('USER', 'ASSISTANT')
                                  and kind = 'TEXT'
                                  and (
                                    created_at < :triggerCreatedAt
                                    or (created_at = :triggerCreatedAt and id <= :triggerMessageId)
                                  )
                                order by created_at desc, id desc
                                limit 30
                            ) recent
                            order by created_at, id
                            """)
                    .param("conversationId", trigger.conversationId())
                    .param("triggerCreatedAt", trigger.createdAt())
                    .param("triggerMessageId", trigger.triggerMessageId())
                    .query((rs, rowNum) -> new AiContracts.ChatMessage(
                            rs.getString("role"),
                            rs.getString("content")
                    ))
                    .list();
            List<String> completedNodes = jdbc.sql("""
                            select n.title
                            from career_nodes n
                            join node_progress p on p.node_id = n.id
                            where p.status = 'COMPLETED'
                            order by p.completed_at desc nulls last
                            limit 100
                            """)
                    .query(String.class)
                    .list();
            List<String> recentPostings = jdbc.sql("""
                            select concat_ws(' · ', company_name, role_title)
                            from job_postings
                            where archived_at is null
                              and (company_name is not null or role_title is not null)
                            order by created_at desc
                            limit 20
                            """)
                    .query(String.class)
                    .list();
            List<String> savedEvidence = jdbc.sql("""
                            select concat_ws(' · ', kind, title)
                            from career_fragments
                            where review_status = 'CONFIRMED'
                              and archived_at is null
                            order by updated_at desc
                            limit 100
                            """)
                    .query(String.class)
                    .list();
            List<String> activeGoals = jdbc.sql("""
                            select goal_text
                            from (
                                select concat_ws(
                                    ' · ',
                                    posting.company_name,
                                    posting.role_title
                                ) as goal_text,
                                1 as priority
                                from user_goal_profiles goal
                                join job_postings posting
                                  on posting.id = goal.current_goal_posting_id
                                where goal.user_id = :userId
                                union all
                                select final_goal_text, 2
                                from user_goal_profiles
                                where user_id = :userId
                                  and final_goal_text is not null
                            ) goals
                            where goal_text is not null
                              and goal_text <> ''
                            order by priority
                            """)
                    .param("userId", job.userId())
                    .query(String.class)
                    .list();

            jdbc.sql("""
                            update chat_reply_jobs
                            set stage = 'AI_REPLY', stage_message = 'JOBISS가 답변을 정리하고 있어요'
                            where id = :jobId
                            """)
                    .param("jobId", job.id())
                    .update();

            return new AiContracts.ChatRequest(
                    trigger.conversationId(),
                    displayName,
                    messages,
                    new AiContracts.CareerSummary(
                            completedNodes,
                            activeGoals,
                            recentPostings,
                            savedEvidence
                    )
            );
        });
    }

    private void complete(ClaimedJob job, AiContracts.ChatResponse response) {
        rls.write(job.userId(), jdbc -> {
            UUID conversationId = jdbc.sql("""
                            select conversation_id from chat_reply_jobs where id = :jobId
                            """)
                    .param("jobId", job.id())
                    .query(UUID.class)
                    .single();
            String metadata = objectMapper.writeValueAsString(response);
            jdbc.sql("""
                            insert into conversation_messages (
                                user_id,
                                conversation_id,
                                role,
                                kind,
                                content,
                                metadata
                            )
                            values (
                                :userId,
                                :conversationId,
                                'ASSISTANT',
                                'TEXT',
                                :content,
                                cast(:metadata as jsonb) || jsonb_build_object(
                                    'chatReplyJobId',
                                    cast(:jobId as text)
                                )
                            )
                            """)
                    .param("userId", job.userId())
                    .param("conversationId", conversationId)
                    .param("content", response.message())
                    .param("metadata", metadata)
                    .param("jobId", job.id())
                    .update();
            jdbc.sql("""
                            update chat_reply_jobs
                            set
                                status = 'SUCCEEDED',
                                stage = 'COMPLETED',
                                stage_message = '답변 완료',
                                completed_at = now(),
                                locked_until = null
                            where id = :jobId
                            """)
                    .param("jobId", job.id())
                    .update();
            finish(jdbc, job);
            return null;
        });
    }

    private void fail(ClaimedJob job, Exception exception) {
        rls.write(job.userId(), jdbc -> {
            jdbc.sql("""
                            update chat_reply_jobs
                            set
                                status = 'FAILED',
                                stage = 'FAILED',
                                stage_message = '답변을 만들지 못했어요',
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
            finish(jdbc, job);
            return null;
        });
    }

    private void finish(JdbcClient jdbc, ClaimedJob job) {
        jdbc.sql("select finish_chat_reply_job(:jobId, :userId)")
                .param("jobId", job.id())
                .param("userId", job.userId())
                .query(Object.class)
                .optional();
    }

    private String classify(Exception exception) {
        if (exception instanceof AiServiceException aiException) {
            return aiException.code();
        }
        return "AI_CHAT_FAILED";
    }

    private String safeMessage(Exception exception) {
        String message = exception.getMessage();
        if (message == null || message.isBlank()) {
            return "AI 답변을 생성하지 못했습니다.";
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

    private record ClaimedJob(UUID id, UUID userId, int attemptCount) {
    }

    private record Trigger(
            UUID conversationId,
            UUID triggerMessageId,
            java.time.OffsetDateTime createdAt
    ) {
    }
}
