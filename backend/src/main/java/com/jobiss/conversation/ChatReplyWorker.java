package com.jobiss.conversation;

import com.jobiss.analysis.AiAnalysisClient;
import com.jobiss.analysis.AiContracts;
import com.jobiss.analysis.AiServiceException;
import com.jobiss.db.RlsTransactionExecutor;
import com.jobiss.security.SensitiveTextCipher;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.web.client.ResourceAccessException;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.JsonNode;

import java.net.InetAddress;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.FutureTask;
import java.util.concurrent.atomic.AtomicBoolean;

@Component
@ConditionalOnProperty(name = "jobiss.ai.worker-enabled", havingValue = "true")
public class ChatReplyWorker {

    private static final Logger log = LoggerFactory.getLogger(ChatReplyWorker.class);
    private static final int MAX_ATTEMPTS = 3;
    private static final int RETRY_DELAY_SECONDS = 15;

    private final JdbcClient jdbcClient;
    private final RlsTransactionExecutor rls;
    private final AiAnalysisClient aiClient;
    private final ObjectMapper objectMapper;
    private final ChatReplyJobService chatReplyJobService;
    private final ChatReplyTaskRegistry taskRegistry;
    private final SensitiveTextCipher sensitiveText;
    private final com.jobiss.analysis.v3.V3AnalysisRequestFactory roadmapFactory;
    private final String workerId;
    private final ExecutorService executor;
    private final AtomicBoolean active = new AtomicBoolean();

    public ChatReplyWorker(
            JdbcClient jdbcClient,
            RlsTransactionExecutor rls,
            AiAnalysisClient aiClient,
            ObjectMapper objectMapper,
            ChatReplyJobService chatReplyJobService,
            ChatReplyTaskRegistry taskRegistry,
            SensitiveTextCipher sensitiveText,
            com.jobiss.analysis.v3.V3AnalysisRequestFactory roadmapFactory
    ) {
        this.jdbcClient = jdbcClient;
        this.rls = rls;
        this.aiClient = aiClient;
        this.objectMapper = objectMapper;
        this.chatReplyJobService = chatReplyJobService;
        this.taskRegistry = taskRegistry;
        this.sensitiveText = sensitiveText;
        this.roadmapFactory = roadmapFactory;
        this.workerId = hostName() + "-chat-" + UUID.randomUUID();
        this.executor = Executors.newSingleThreadExecutor(runnable -> {
            Thread thread = new Thread(runnable);
            thread.setName("jobiss-chat-worker");
            thread.setDaemon(true);
            return thread;
        });
    }

    @Scheduled(fixedDelayString = "${jobiss.ai.poll-delay-ms:3000}")
    public void processOne() {
        if (!active.compareAndSet(false, true)) {
            return;
        }
        ClaimedJob job = claim();
        if (job == null) {
            active.set(false);
            return;
        }
        FutureTask<Void> task = new FutureTask<>(() -> {
            try {
                process(job);
            } finally {
                taskRegistry.complete(job.id());
                active.set(false);
            }
            return null;
        });
        taskRegistry.register(job.id(), task);
        executor.execute(task);
    }

    private void process(ClaimedJob job) {
        try {
            AiContracts.ChatRequest request = loadRequest(job);
            AiContracts.ChatResponse response = aiClient.chat(
                    request,
                    event -> persistProgress(job, event)
            );
            if (response == null || response.message() == null || response.message().isBlank()) {
                throw new IllegalStateException("AI response did not include a message");
            }
            complete(job, response);
            try {
                // 로드맵 재료(V3)는 두 경우에만, 무음(UI 노출 없음, DB 적재만)으로 만든다:
                // ① 적합도 판정이 적재된 턴 ② 사용자가 공고 기준 로드맵을 직접 청한 턴
                //    (requiresConsent=false 인 ANALYZE_POSTING 제안).
                chatReplyJobService.startRoadmapAnalysisAfterFit(job.userId(), response);
                chatReplyJobService.executeUserInitiatedAutomaticActions(
                        job.userId(), job.id(), response.proposedActions()
                );
            } catch (RuntimeException actionException) {
                log.warn(
                        "Silent roadmap analysis for chat reply job {} failed: {}",
                        job.id(), actionException.getMessage()
                );
            }
        } catch (Exception exception) {
            if (isTransportFailure(exception) && job.attemptCount() < MAX_ATTEMPTS) {
                log.warn(
                        "Chat reply job {} could not reach the AI server (attempt {}/{}); retrying in {}s: {}",
                        job.id(),
                        job.attemptCount(),
                        MAX_ATTEMPTS,
                        RETRY_DELAY_SECONDS,
                        exception.getMessage()
                );
                requeue(job, exception, RETRY_DELAY_SECONDS);
                return;
            }
            log.warn("Chat reply job {} failed: {}", job.id(), exception.getMessage());
            fail(job, exception);
        }
    }

    @PreDestroy
    void shutdown() {
        interruptActiveJob();
        taskRegistry.cancelAll();
        executor.shutdownNow();
    }

    private void interruptActiveJob() {
        try {
            jdbcClient.sql("select interrupt_auxiliary_ai_jobs(:workerId)")
                    .param("workerId", workerId)
                    .query(Integer.class)
                    .single();
        } catch (RuntimeException exception) {
            log.warn("Could not release active chat job during shutdown: {}", exception.getMessage());
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
        // 에이전트가 사용자의 서비스 상태(로드맵)를 보고 대화하도록 매 턴 싣는다.
        JsonNode roadmap = roadmapFactory.currentRoadmap(job.userId());
        return rls.write(job.userId(), jdbc -> {
            Trigger trigger = jdbc.sql("""
                            select
                                j.conversation_id,
                                j.trigger_message_id,
                                j.request_context::text,
                                m.created_at
                            from chat_reply_jobs j
                            join conversation_messages m on m.id = j.trigger_message_id
                            where j.id = :jobId
                            """)
                    .param("jobId", job.id())
                    .query((rs, rowNum) -> new Trigger(
                            rs.getObject("conversation_id", UUID.class),
                            rs.getObject("trigger_message_id", UUID.class),
                            rs.getString("request_context"),
                            rs.getObject("created_at", java.time.OffsetDateTime.class)
                    ))
                    .single();
            AgentSelection selection = resolveAutomaticAssets(
                    jdbc,
                    parseSelection(trigger.requestContext())
            );

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
                                error_message = null,
                                progress_events = jsonb_build_array(
                                    jsonb_build_object(
                                        'agentId', 'context_reader',
                                        'label', '맥락 정리',
                                        'status', 'RUNNING',
                                        'message', '선택한 공고와 커리어 자료를 확인하고 있어요',
                                        'occurredAt', cast(now() as text)
                                    )
                                )
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

            // 사용자 DB의 이력서·공고 원문을 요약이 아니라 원문으로 싣는다 — 에이전트가
            // "저장된 이력서로 분석할까요?" 를 실제 자료를 보고 판단·수행할 수 있게.
            List<AiContracts.StoredResume> resumes = jdbc.sql("""
                            select id, title, source_type, raw_text, created_at
                            from career_sources
                            where status = 'CONFIRMED'
                              and archived_at is null
                            order by created_at desc
                            limit 5
                            """)
                    .query((rs, rowNum) -> new AiContracts.StoredResume(
                            rs.getObject("id", UUID.class),
                            rs.getString("title"),
                            rs.getString("source_type"),
                            clip(sensitiveText.decrypt(rs.getString("raw_text")), 20_000),
                            rs.getObject("created_at", OffsetDateTime.class)
                    ))
                    .list();
            List<AiContracts.StoredPosting> storedPostings = jdbc.sql("""
                            select p.id, p.source_type, p.source_url, p.raw_text,
                                   p.parsed_data::text as parsed_data, p.created_at,
                                   (
                                       select cache.structured_posting::text
                                       from analysis_jobs job
                                       join ai_v3_verified_posting_snapshots snap
                                         on snap.id = job.v3_snapshot_id
                                       join ai_v3_posting_structure_cache cache
                                         on cache.snapshot_hash = snap.snapshot_hash
                                        and cache.invalidated_at is null
                                       where job.posting_id = p.id
                                       order by job.created_at desc
                                       limit 1
                                   ) as structured_posting
                            from job_postings p
                            where p.archived_at is null
                            order by p.created_at desc
                            limit 5
                            """)
                    .query((rs, rowNum) -> new AiContracts.StoredPosting(
                            rs.getObject("id", UUID.class),
                            rs.getString("source_type"),
                            rs.getString("source_url"),
                            clip(sensitiveText.decrypt(rs.getString("raw_text")), 20_000),
                            rs.getString("parsed_data") == null
                                    ? null : objectMapper.readTree(rs.getString("parsed_data")),
                            rs.getString("structured_posting") == null
                                    ? null : objectMapper.readTree(rs.getString("structured_posting")),
                            rs.getObject("created_at", OffsetDateTime.class)
                    ))
                    .list();

            GoalProfileRow goalProfile = jdbc.sql("""
                            select chat_preferences::text as chat_preferences,
                                   chat_facts::text as chat_facts,
                                   preparation_period_weeks,
                                   available_hours_per_week
                            from user_goal_profiles
                            where user_id = :userId
                            """)
                    .param("userId", job.userId())
                    .query((rs, rowNum) -> new GoalProfileRow(
                            rs.getString("chat_preferences"),
                            rs.getString("chat_facts"),
                            rs.getObject("preparation_period_weeks", Integer.class),
                            rs.getObject("available_hours_per_week", Integer.class)
                    ))
                    .optional()
                    .orElse(new GoalProfileRow(null, null, null, null));

            List<AiContracts.ChatPostingAsset> postingAssets = loadPostingAssets(
                    jdbc,
                    selection.postingIds()
            );
            List<AiContracts.ChatCareerSourceAsset> sourceAssets = loadCareerSourceAssets(
                    jdbc,
                    selection.careerSourceIds()
            );
            ensureSelectedAssetsAvailable(selection, postingAssets, sourceAssets);

            String progress = objectMapper.writeValueAsString(List.of(
                    new ProgressEvent(
                            "context_reader",
                            "맥락 정리",
                            "COMPLETED",
                            "선택한 자료와 기존 커리어 맥락을 정리했어요",
                            OffsetDateTime.now()
                    )
            ));

            jdbc.sql("""
                            update chat_reply_jobs
                            set
                                stage = 'AGENT_PLANNING',
                                stage_message = '대화에 맞는 담당 에이전트를 선택하고 있어요',
                                progress_events = cast(:progress as jsonb)
                            where id = :jobId
                            """)
                    .param("progress", progress)
                    .param("jobId", job.id())
                    .update();

            JsonNode workspaceState = jdbc.sql("""
                            select state::text
                            from agent_workspace_states
                            where user_id = :userId
                              and conversation_id = :conversationId
                            """)
                    .param("userId", job.userId())
                    .param("conversationId", trigger.conversationId())
                    .query(String.class)
                    .optional()
                    .map(objectMapper::readTree)
                    .orElseGet(objectMapper::createObjectNode);

            return new AiContracts.ChatRequest(
                    trigger.conversationId(),
                    displayName,
                    messages,
                    new AiContracts.CareerSummary(
                            completedNodes,
                            activeGoals,
                            recentPostings,
                            savedEvidence,
                            resumes,
                            storedPostings,
                            roadmap,
                            goalProfile.preferences() == null
                                    ? null : objectMapper.readTree(goalProfile.preferences()),
                            // AI 계약의 facts 는 null 을 받지 않는 list — 없으면 빈 배열로.
                            goalProfile.facts() == null
                                    ? objectMapper.createArrayNode()
                                    : objectMapper.readTree(goalProfile.facts()),
                            goalProfile.preparationPeriodWeeks(),
                            goalProfile.availableHoursPerWeek()
                    ),
                    new AiContracts.ChatTaskContext(
                            selection.mode(),
                            postingAssets,
                            sourceAssets
                    ),
                    workspaceState
            );
        });
    }

    private List<AiContracts.ChatPostingAsset> loadPostingAssets(
            JdbcClient jdbc,
            List<UUID> postingIds
    ) {
        if (postingIds.isEmpty()) {
            return List.of();
        }
        return jdbc.sql("""
                        select
                            p.id,
                            p.company_name,
                            p.role_title,
                            p.source_url,
                            p.experience_text,
                            p.lifecycle_status,
                            p.raw_text,
                            (
                                select analysis.result_data -> 'evaluation' ->> 'summary'
                                from analysis_jobs analysis
                                where analysis.posting_id = p.id
                                  and analysis.status = 'SUCCEEDED'
                                order by analysis.completed_at desc nulls last
                                limit 1
                            ) as analysis_summary
                        from job_postings p
                        where p.id in (:postingIds)
                          and p.archived_at is null
                        order by p.created_at desc
                        """)
                .param("postingIds", postingIds)
                .query((rs, rowNum) -> new AiContracts.ChatPostingAsset(
                        rs.getObject("id", UUID.class),
                        rs.getString("company_name"),
                        rs.getString("role_title"),
                        rs.getString("source_url"),
                        rs.getString("experience_text"),
                        rs.getString("lifecycle_status"),
                        clip(sensitiveText.decrypt(rs.getString("raw_text")), 20_000),
                        rs.getString("analysis_summary")
                ))
                .list();
    }

    private List<AiContracts.ChatCareerSourceAsset> loadCareerSourceAssets(
            JdbcClient jdbc,
            List<UUID> sourceIds
    ) {
        if (sourceIds.isEmpty()) {
            return List.of();
        }
        List<CareerSourceRow> rows = jdbc.sql("""
                        select id, source_type, title, source_url, summary, raw_text
                        from career_sources
                        where id in (:sourceIds)
                          and status = 'CONFIRMED'
                          and archived_at is null
                        order by created_at desc
                        """)
                .param("sourceIds", sourceIds)
                .query((rs, rowNum) -> new CareerSourceRow(
                        rs.getObject("id", UUID.class),
                        rs.getString("source_type"),
                        rs.getString("title"),
                        rs.getString("source_url"),
                        rs.getString("summary"),
                        clip(sensitiveText.decrypt(rs.getString("raw_text")), 20_000)
                ))
                .list();
        List<AiContracts.ChatCareerSourceAsset> assets = new ArrayList<>();
        for (CareerSourceRow row : rows) {
            List<AiContracts.ChatCareerFragment> fragments = jdbc.sql("""
                            select kind, title, description
                            from career_fragments
                            where source_id = :sourceId
                              and review_status = 'CONFIRMED'
                              and archived_at is null
                            order by updated_at desc
                            limit 100
                            """)
                    .param("sourceId", row.id())
                    .query((rs, rowNum) -> new AiContracts.ChatCareerFragment(
                            rs.getString("kind"),
                            rs.getString("title"),
                            clip(rs.getString("description"), 2_000)
                    ))
                    .list();
            assets.add(new AiContracts.ChatCareerSourceAsset(
                    row.id(),
                    row.sourceType(),
                    row.title(),
                    row.sourceUrl(),
                    row.summary(),
                    row.rawText(),
                    fragments
            ));
        }
        return List.copyOf(assets);
    }

    private AgentSelection parseSelection(String value) {
        JsonNode context = value == null || value.isBlank()
                ? objectMapper.createObjectNode()
                : objectMapper.readTree(value);
        String mode = context.path("mode").stringValue("AUTO");
        return new AgentSelection(
                mode,
                readUuidList(context.path("postingIds")),
                readUuidList(context.path("careerSourceIds"))
        );
    }

    private AgentSelection resolveAutomaticAssets(
            JdbcClient jdbc,
            AgentSelection selection
    ) {
        if (!"AUTO".equals(selection.mode())) {
            return selection;
        }
        List<UUID> postingIds = selection.postingIds().isEmpty()
                ? jdbc.sql("""
                                select id
                                from job_postings
                                where archived_at is null
                                order by updated_at desc, created_at desc
                                limit 5
                                """)
                        .query(UUID.class)
                        .list()
                : selection.postingIds();
        List<UUID> sourceIds = selection.careerSourceIds().isEmpty()
                ? jdbc.sql("""
                                select id
                                from career_sources
                                where status = 'CONFIRMED'
                                  and archived_at is null
                                order by updated_at desc, created_at desc
                                limit 5
                                """)
                        .query(UUID.class)
                        .list()
                : selection.careerSourceIds();
        return new AgentSelection("AUTO", postingIds, sourceIds);
    }

    private List<UUID> readUuidList(JsonNode node) {
        if (!node.isArray()) {
            return List.of();
        }
        List<UUID> values = new ArrayList<>();
        for (JsonNode item : node) {
            try {
                values.add(UUID.fromString(item.stringValue("")));
            } catch (IllegalArgumentException ignored) {
                throw new IllegalStateException("AI 작업에 선택한 자료 ID가 올바르지 않습니다.");
            }
        }
        return List.copyOf(values);
    }

    private void ensureSelectedAssetsAvailable(
            AgentSelection selection,
            List<AiContracts.ChatPostingAsset> postings,
            List<AiContracts.ChatCareerSourceAsset> sources
    ) {
        if (postings.size() != selection.postingIds().size()
                || sources.size() != selection.careerSourceIds().size()) {
            throw new IllegalStateException(
                    "선택한 공고 또는 커리어 자료가 삭제되었거나 더 이상 사용할 수 없습니다."
            );
        }
    }

    private String clip(String value, int limit) {
        if (value == null || value.length() <= limit) {
            return value == null ? "" : value;
        }
        return value.substring(0, limit);
    }

    private void persistProgress(
            ClaimedJob job,
            AiContracts.ChatStreamEvent event
    ) {
        if ("PLAN".equals(event.type()) && event.plan() != null) {
            String plan = objectMapper.writeValueAsString(event.plan());
            rls.write(job.userId(), jdbc -> {
                jdbc.sql("""
                                update chat_reply_jobs
                                set
                                    stage = 'AGENT_PLAN',
                                    stage_message = '에이전트 실행 경로를 구성했어요',
                                    result_data = jsonb_set(
                                        result_data,
                                        '{plan}',
                                        cast(:plan as jsonb),
                                        true
                                    ),
                                    locked_until = now() + interval '15 minutes'
                                where id = :jobId
                                  and status = 'RUNNING'
                                """)
                        .param("plan", plan)
                        .param("jobId", job.id())
                        .update();
                return null;
            });
            return;
        }
        if (!"PROGRESS".equals(event.type()) && !"ERROR".equals(event.type())) {
            return;
        }
        String agentId = valueOr(event.agentId(), "agent_orchestrator");
        String label = valueOr(event.label(), "에이전트 실행");
        String status = valueOr(event.status(), "RUNNING");
        String message = valueOr(event.message(), "요청을 처리하고 있어요.");
        rls.write(job.userId(), jdbc -> {
            jdbc.sql("""
                            update chat_reply_jobs
                            set
                                stage = :stage,
                                stage_message = :stageMessage,
                                progress_events = progress_events || jsonb_build_array(
                                    jsonb_build_object(
                                        'agentId', :agentId,
                                        'label', :label,
                                        'status', :status,
                                        'message', :message,
                                        'occurredAt', :occurredAt
                                    )
                                ),
                                locked_until = now() + interval '15 minutes'
                            where id = :jobId
                              and status = 'RUNNING'
                            """)
                    .param("stage", "AGENT_" + agentId.toUpperCase())
                    .param("stageMessage", message)
                    .param("agentId", agentId)
                    .param("label", label)
                    .param("status", status)
                    .param("message", message)
                    .param(
                            "occurredAt",
                            event.occurredAt() == null
                                    ? OffsetDateTime.now().toString()
                                    : event.occurredAt().toString()
                    )
                    .param("jobId", job.id())
                    .update();
            return null;
        });
    }

    private String valueOr(String value, String fallback) {
        return value == null || value.isBlank() ? fallback : value;
    }

    private void complete(ClaimedJob job, AiContracts.ChatResponse response) {
        rls.write(job.userId(), jdbc -> {
            UUID conversationId = jdbc.sql("""
                            select conversation_id
                            from chat_reply_jobs
                            where id = :jobId
                              and status = 'RUNNING'
                              and worker_id = :workerId
                            for update
                            """)
                    .param("jobId", job.id())
                    .param("workerId", workerId)
                    .query(UUID.class)
                    .optional()
                    .orElse(null);
            if (conversationId == null) {
                return null;
            }
            String metadata = objectMapper.writeValueAsString(response);
            String completedProgress = objectMapper.writeValueAsString(
                    canonicalProgress(response)
            );
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
                                result_data = cast(:resultData as jsonb),
                                progress_events = cast(:progressEvents as jsonb),
                                completed_at = now(),
                                locked_until = null
                            where id = :jobId
                              and status = 'RUNNING'
                              and worker_id = :workerId
                            """)
                    .param("resultData", metadata)
                    .param("progressEvents", completedProgress)
                    .param("jobId", job.id())
                    .param("workerId", workerId)
                    .update();
            persistWorkspaceState(jdbc, job, conversationId, response.workspaceState());
            persistWorkProducts(jdbc, job, conversationId, response);
            persistCollectedAssets(jdbc, job, conversationId, response.collected());
            finish(jdbc, job);
            return null;
        });
    }

    /**
     * AI가 대화 턴에서 수집한 자산(collected)을 도메인 테이블로 투영한다.
     * persistence_map.py 계약: 대화에 붙인 공고 → job_postings, 이력서 → career_sources.
     * 이력서는 기본 상태(QUEUED)로 넣어 CareerExtractionWorker가 조각 추출까지 잇는다.
     */
    private void persistCollectedAssets(
            JdbcClient jdbc,
            ClaimedJob job,
            UUID conversationId,
            JsonNode collected
    ) {
        if (collected == null || !collected.isObject()) {
            return;
        }
        JsonNode posting = collected.path("posting");
        String postingText = posting.path("rawText").asString("").trim();
        if (!postingText.isEmpty()) {
            String fingerprint = sensitiveText.fingerprint(
                    postingText.replaceAll("\\s+", " ").toLowerCase(java.util.Locale.ROOT)
            );
            JsonNode parsed = collected.path("outputs").path("postingSummary");
            UUID existing = jdbc.sql("""
                            select id
                            from job_postings
                            where content_fingerprint = :fingerprint
                              and archived_at is null
                            limit 1
                            """)
                    .param("fingerprint", fingerprint)
                    .query(UUID.class)
                    .optional()
                    .orElse(null);
            if (existing == null) {
                jdbc.sql("""
                                insert into job_postings (
                                    user_id, source_type, source_url, raw_text,
                                    conversation_id, content_fingerprint,
                                    company_name, role_title, parsed_data
                                )
                                values (
                                    :userId, cast(:sourceType as posting_source), :sourceUrl,
                                    :rawText, :conversationId, :fingerprint,
                                    :companyName, :roleTitle, cast(:parsedData as jsonb)
                                )
                                """)
                        .param("userId", job.userId())
                        .param("sourceType", posting.path("sourceType").asString("TEXT"))
                        .param("sourceUrl", posting.path("sourceUrl").asString(null))
                        .param("rawText", sensitiveText.encrypt(postingText))
                        .param("conversationId", conversationId)
                        .param("fingerprint", fingerprint)
                        .param("companyName", parsed.path("companyName").asString(null))
                        .param("roleTitle", parsed.path("jobTitle").asString(null))
                        .param("parsedData", parsed.isObject()
                                ? objectMapper.writeValueAsString(parsed) : null)
                        .update();
            } else if (parsed.isObject()) {
                jdbc.sql("""
                                update job_postings
                                set parsed_data = cast(:parsedData as jsonb),
                                    company_name = coalesce(company_name, :companyName),
                                    role_title = coalesce(role_title, :roleTitle),
                                    updated_at = now()
                                where id = :id
                                """)
                        .param("parsedData", objectMapper.writeValueAsString(parsed))
                        .param("companyName", parsed.path("companyName").asString(null))
                        .param("roleTitle", parsed.path("jobTitle").asString(null))
                        .param("id", existing)
                        .update();
            }
            // 대화방 제목은 사용자가 가장 최근에 낸 공고의 회사명을 따른다.
            String companyName = parsed.path("companyName").asString("").trim();
            if (!companyName.isEmpty()) {
                jdbc.sql("""
                                update conversations
                                set title = :title
                                where id = :conversationId
                                """)
                        .param("title", clip(companyName, 80))
                        .param("conversationId", conversationId)
                        .update();
            }
        }
        JsonNode resume = collected.path("resume");
        String resumeText = resume.path("rawText").asString("").trim();
        if (!resumeText.isEmpty()) {
            jdbc.sql("""
                            insert into career_sources (
                                user_id, source_type, title, raw_text
                            )
                            values (:userId, 'TEXT', :title, :rawText)
                            """)
                    .param("userId", job.userId())
                    .param("title", resume.path("title").asString("대화로 받은 이력서"))
                    .param("rawText", sensitiveText.encrypt(resumeText))
                    .update();
        }
        JsonNode preferences = collected.path("preferences");
        JsonNode facts = collected.path("facts");
        JsonNode outputs = collected.path("outputs");
        Integer prepWeeks = outputs.path("preparationPeriodWeeks").isNumber()
                ? outputs.path("preparationPeriodWeeks").asInt() : null;
        Integer hoursPerWeek = outputs.path("availableHoursPerWeek").isNumber()
                ? outputs.path("availableHoursPerWeek").asInt() : null;
        if (preferences.isObject() || facts.isArray()
                || prepWeeks != null || hoursPerWeek != null) {
            jdbc.sql("""
                            insert into user_goal_profiles (
                                user_id, chat_preferences, chat_facts,
                                preparation_period_weeks, available_hours_per_week
                            )
                            values (
                                :userId, cast(:preferences as jsonb), cast(:facts as jsonb),
                                :prepWeeks, :hoursPerWeek
                            )
                            on conflict (user_id) do update set
                                chat_preferences = coalesce(
                                        excluded.chat_preferences,
                                        user_goal_profiles.chat_preferences),
                                chat_facts = coalesce(
                                        excluded.chat_facts,
                                        user_goal_profiles.chat_facts),
                                preparation_period_weeks = coalesce(
                                        excluded.preparation_period_weeks,
                                        user_goal_profiles.preparation_period_weeks),
                                available_hours_per_week = coalesce(
                                        excluded.available_hours_per_week,
                                        user_goal_profiles.available_hours_per_week),
                                updated_at = now()
                            """)
                    .param("userId", job.userId())
                    .param("preferences", preferences.isObject()
                            ? objectMapper.writeValueAsString(preferences) : null)
                    .param("facts", facts.isArray()
                            ? objectMapper.writeValueAsString(facts) : null)
                    .param("prepWeeks", prepWeeks)
                    .param("hoursPerWeek", hoursPerWeek)
                    .update();
        }
    }

    private void persistWorkspaceState(
            JdbcClient jdbc,
            ClaimedJob job,
            UUID conversationId,
            JsonNode workspaceState
    ) {
        if (workspaceState == null || !workspaceState.isObject()) {
            return;
        }
        jdbc.sql("""
                        insert into agent_workspace_states (
                            user_id, conversation_id, state
                        ) values (
                            :userId, :conversationId, cast(:state as jsonb)
                        )
                        on conflict (user_id, conversation_id) do update
                        set state = excluded.state, updated_at = now()
                        """)
                .param("userId", job.userId())
                .param("conversationId", conversationId)
                .param("state", objectMapper.writeValueAsString(workspaceState))
                .update();
    }

    private void persistWorkProducts(
            JdbcClient jdbc,
            ClaimedJob job,
            UUID conversationId,
            AiContracts.ChatResponse response
    ) {
        if (response.workProducts() == null || response.workProducts().isEmpty()) {
            return;
        }
        UUID postingId = response.plan() == null
                || response.plan().selectedPostingIds() == null
                || response.plan().selectedPostingIds().isEmpty()
                ? null
                : response.plan().selectedPostingIds().get(0);
        for (int ordinal = 0; ordinal < response.workProducts().size(); ordinal++) {
            AiContracts.ChatAgentWorkProduct product = response.workProducts().get(ordinal);
            String payload = objectMapper.writeValueAsString(product);
            String sources = objectMapper.writeValueAsString(
                    product.replySources() == null ? List.of() : product.replySources()
            );
            UUID productId = jdbc.sql("""
                            insert into agent_work_products (
                                user_id, conversation_id, chat_reply_job_id, ordinal,
                                agent_id, product_type, title, summary, payload, reply_sources
                            ) values (
                                :userId, :conversationId, :jobId, :ordinal,
                                :agentId, :productType, :title, :summary,
                                cast(:payload as jsonb), cast(:sources as jsonb)
                            )
                            on conflict (chat_reply_job_id, ordinal) do update set
                                agent_id = excluded.agent_id,
                                product_type = excluded.product_type,
                                title = excluded.title,
                                summary = excluded.summary,
                                payload = excluded.payload,
                                reply_sources = excluded.reply_sources
                            returning id
                            """)
                    .param("userId", job.userId())
                    .param("conversationId", conversationId)
                    .param("jobId", job.id())
                    .param("ordinal", ordinal)
                    .param("agentId", product.agentId())
                    .param("productType", product.productType())
                    .param("title", product.title())
                    .param("summary", product.summary())
                    .param("payload", payload)
                    .param("sources", sources)
                    .query(UUID.class)
                    .single();
            persistTypedWorkProduct(
                    jdbc, job.userId(), conversationId, postingId,
                    productId, product, response.detailedStatus()
            );
        }
    }

    private void persistTypedWorkProduct(
            JdbcClient jdbc,
            UUID userId,
            UUID conversationId,
            UUID postingId,
            UUID productId,
            AiContracts.ChatAgentWorkProduct product,
            String detailedStatus
    ) {
        JsonNode dataNode = product.data() == null
                ? objectMapper.createObjectNode()
                : product.data();
        String data = objectMapper.writeValueAsString(dataNode);
        switch (product.productType()) {
            case "PREFERENCES" -> jdbc.sql("""
                            insert into user_agent_preferences (
                                user_id, preferences, source_work_product_id
                            ) values (
                                :userId, cast(:data as jsonb), :productId
                            )
                            on conflict (user_id) do update set
                                preferences = excluded.preferences,
                                source_work_product_id = excluded.source_work_product_id,
                                updated_at = now()
                            """)
                    .param("userId", userId)
                    .param("data", data)
                    .param("productId", productId)
                    .update();
            case "INTERVIEW_SET" -> jdbc.sql("""
                            insert into interview_sessions (
                                user_id, conversation_id, posting_id,
                                source_work_product_id, state
                            ) values (
                                :userId, :conversationId, :postingId,
                                :productId, cast(:data as jsonb)
                            )
                            on conflict (source_work_product_id) do update
                            set state = excluded.state, updated_at = now()
                            """)
                    .param("userId", userId)
                    .param("conversationId", conversationId)
                    .param("postingId", postingId)
                    .param("productId", productId)
                    .param("data", data)
                    .update();
            case "COVER_LETTER_DRAFT" -> jdbc.sql("""
                            insert into cover_letter_drafts (
                                user_id, posting_id, source_work_product_id,
                                title, content
                            ) values (
                                :userId, :postingId, :productId,
                                :title, cast(:data as jsonb)
                            )
                            on conflict (source_work_product_id) do update
                            set title = excluded.title,
                                content = excluded.content,
                                updated_at = now()
                            """)
                    .param("userId", userId)
                    .param("postingId", postingId)
                    .param("productId", productId)
                    .param("title", product.title())
                    .param("data", data)
                    .update();
            case "APPLICATION_PLAN" -> jdbc.sql("""
                            insert into application_plans (
                                user_id, posting_id, source_work_product_id,
                                detailed_status, plan
                            ) values (
                                :userId, :postingId, :productId,
                                :detailedStatus, cast(:data as jsonb)
                            )
                            on conflict (source_work_product_id) do update
                            set detailed_status = excluded.detailed_status,
                                plan = excluded.plan,
                                updated_at = now()
                            """)
                    .param("userId", userId)
                    .param("postingId", postingId)
                    .param("productId", productId)
                    .param("detailedStatus", detailedStatus)
                    .param("data", data)
                    .update();
            default -> {
                // Generic products remain available through agent_work_products.
            }
        }
    }

    private List<ProgressEvent> canonicalProgress(
            AiContracts.ChatResponse response
    ) {
        if (response.progress() == null || response.progress().isEmpty()) {
            return List.of(
                    new ProgressEvent(
                            "response_writer",
                            "결과 정리",
                            "COMPLETED",
                            "검토 가능한 답변을 완성했어요.",
                            OffsetDateTime.now()
                    )
            );
        }
        return response.progress().stream()
                .map(item -> new ProgressEvent(
                        valueOr(item.agentId(), "agent_orchestrator"),
                        valueOr(item.label(), "에이전트 실행"),
                        valueOr(item.status(), "COMPLETED"),
                        valueOr(item.message(), "작업을 완료했어요."),
                        OffsetDateTime.now()
                ))
                .toList();
    }

    static boolean isTransportFailure(Throwable exception) {
        for (Throwable cause = exception; cause != null; cause = cause.getCause()) {
            if (cause instanceof AiServiceException) {
                return false;
            }
            if (cause instanceof ResourceAccessException) {
                return true;
            }
            if (cause.getCause() == cause) {
                break;
            }
        }
        return false;
    }

    private void requeue(ClaimedJob job, Exception exception, int delaySeconds) {
        rls.write(job.userId(), jdbc -> {
            jdbc.sql("""
                            update chat_reply_jobs
                            set
                                status = 'QUEUED',
                                stage = 'QUEUED',
                                stage_message = 'AI 서버에 다시 연결하는 중이에요',
                                worker_id = null,
                                locked_until = null,
                                error_code = :errorCode,
                                error_message = :errorMessage
                            where id = :jobId
                              and status = 'RUNNING'
                              and worker_id = :workerId
                            """)
                    .param("errorCode", classify(exception))
                    .param("errorMessage", safeMessage(exception))
                    .param("jobId", job.id())
                    .param("workerId", workerId)
                    .update();
            jdbc.sql("select requeue_chat_reply_job(:jobId, :userId, :delaySeconds)")
                    .param("jobId", job.id())
                    .param("userId", job.userId())
                    .param("delaySeconds", delaySeconds)
                    .query(Object.class)
                    .optional();
            return null;
        });
    }

    private void fail(ClaimedJob job, Exception exception) {
        rls.write(job.userId(), jdbc -> {
            int updated = jdbc.sql("""
                            update chat_reply_jobs
                            set
                                status = 'FAILED',
                                stage = 'FAILED',
                                stage_message = '답변을 만들지 못했어요',
                                error_code = :errorCode,
                                error_message = :errorMessage,
                                progress_events = progress_events || jsonb_build_array(
                                    jsonb_build_object(
                                        'agentId', 'agent_error_boundary',
                                        'label', '오류 격리',
                                        'status', 'FAILED',
                                        'message', '현재 작업의 오류를 다른 대화와 분리했어요',
                                        'occurredAt', cast(now() as text)
                                    )
                                ),
                                completed_at = now(),
                                locked_until = null
                            where id = :jobId
                              and status = 'RUNNING'
                              and worker_id = :workerId
                            """)
                    .param("errorCode", classify(exception))
                    .param("errorMessage", safeMessage(exception))
                    .param("jobId", job.id())
                    .param("workerId", workerId)
                    .update();
            if (updated > 0) {
                finish(jdbc, job);
            }
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
            String requestContext,
            java.time.OffsetDateTime createdAt
    ) {
    }

    private record AgentSelection(
            String mode,
            List<UUID> postingIds,
            List<UUID> careerSourceIds
    ) {
    }

    private record GoalProfileRow(
            String preferences,
            String facts,
            Integer preparationPeriodWeeks,
            Integer availableHoursPerWeek
    ) {
    }

    private record CareerSourceRow(
            UUID id,
            String sourceType,
            String title,
            String sourceUrl,
            String summary,
            String rawText
    ) {
    }

    private record ProgressEvent(
            String agentId,
            String label,
            String status,
            String message,
            OffsetDateTime occurredAt
    ) {
    }
}
