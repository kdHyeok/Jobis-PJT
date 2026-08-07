package com.jobiss.conversation;

import com.jobiss.analysis.AiContracts;
import com.jobiss.analysis.AiUsageLimitService;
import com.jobiss.common.ApiException;
import com.jobiss.db.RlsTransactionExecutor;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

import java.time.OffsetDateTime;
import java.net.URI;
import java.util.List;
import java.util.Locale;
import java.util.UUID;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

@Service
public class ChatReplyJobService {

    private static final Logger log = LoggerFactory.getLogger(ChatReplyJobService.class);
    private static final Pattern HTTP_URL = Pattern.compile("https?://[^\\s<>\\\"]+");

    private final RlsTransactionExecutor rls;
    private final AiUsageLimitService usageLimit;
    private final ObjectMapper objectMapper;
    private final ChatReplyTaskRegistry taskRegistry;
    private final com.jobiss.analysis.v3.V3SourceService v3SourceService;
    private final com.jobiss.security.SensitiveTextCipher sensitiveText;

    public ChatReplyJobService(
            RlsTransactionExecutor rls,
            AiUsageLimitService usageLimit,
            ObjectMapper objectMapper,
            ChatReplyTaskRegistry taskRegistry,
            com.jobiss.analysis.v3.V3SourceService v3SourceService,
            com.jobiss.security.SensitiveTextCipher sensitiveText
    ) {
        this.rls = rls;
        this.usageLimit = usageLimit;
        this.objectMapper = objectMapper;
        this.taskRegistry = taskRegistry;
        this.v3SourceService = v3SourceService;
        this.sensitiveText = sensitiveText;
    }

    /**
     * 적합도 판정(collected.outputs.analysis)이 적재된 턴에 로드맵용 V3 분석을 무음으로
     * 잇는다 — 대화·UI 에는 아무것도 남기지 않고 DB 적재만 한다. 공고가 들어온 즉시가
     * 아니라 이력서 대조가 끝난 뒤에 로드맵 재료를 만드는 순서를 코드로 고정한다.
     */
    public void startRoadmapAnalysisAfterFit(UUID userId, AiContracts.ChatResponse response) {
        JsonNode collected = response.collected();
        if (collected == null || !collected.path("outputs").path("analysis").isObject()) {
            return;
        }
        String rawText = firstUsablePostingText(
                collected.path("outputs").path("sessionState")
                        .path("job_posting").path("value").asString(""),
                collected.path("posting").path("rawText").asString(""),
                latestStoredPostingText(userId)
        );
        if (rawText.length() < 20) {
            return;
        }
        var acquired = v3SourceService.acquire(
                userId,
                new com.jobiss.analysis.v3.V3SourceService.AcquireCommand(
                        "TEXT", "CHAT", 1, null, rawText, null, null, null, null
                )
        );
        String verifiedText = acquired.sourceDocument().path("rawText").asString(rawText);
        v3SourceService.verify(
                userId,
                acquired.id(),
                new com.jobiss.analysis.v3.V3SourceService.VerifyCommand(
                        verifiedText, objectMapper.createArrayNode(), "USER", null
                )
        );
        v3SourceService.startAnalysis(userId, acquired.id(), null);
    }

    private static String firstUsablePostingText(String... candidates) {
        for (String candidate : candidates) {
            String text = candidate == null ? "" : candidate.trim();
            // 순수 URL 은 공고 본문이 아니다 — 다음 후보(수집된 원문)로 넘어간다.
            if (text.length() >= 20 && !text.matches("(?is)https?://\\S+")) {
                return text;
            }
        }
        return "";
    }

    private String latestStoredPostingText(UUID userId) {
        return rls.read(userId, jdbc -> jdbc.sql("""
                        select raw_text
                        from job_postings
                        where archived_at is null
                        order by created_at desc
                        limit 1
                        """)
                .query(String.class)
                .optional()
                .map(sensitiveText::decrypt)
                .orElse(""));
    }

    public UUID enqueue(UUID userId, UUID conversationId, UUID triggerMessageId) {
        return enqueue(
                userId,
                conversationId,
                triggerMessageId,
                objectMapper.createObjectNode().put("mode", "CAREER_CHAT")
        );
    }

    public UUID enqueue(
            UUID userId,
            UUID conversationId,
            UUID triggerMessageId,
            JsonNode requestContext
    ) {
        return rls.write(userId, jdbc -> {
            jdbc.sql("select pg_advisory_xact_lock(hashtextextended(:key, 0))")
                    .param("key", triggerMessageId.toString())
                    .query(Object.class)
                    .optional();
            UUID existing = jdbc.sql("""
                            select id
                            from chat_reply_jobs
                            where trigger_message_id = :triggerMessageId
                            """)
                    .param("triggerMessageId", triggerMessageId)
                    .query(UUID.class)
                    .optional()
                    .orElse(null);
            if (existing != null) {
                return existing;
            }
            usageLimit.consume(jdbc, userId, AiUsageLimitService.Kind.CHAT);
            return jdbc.sql("""
                        insert into chat_reply_jobs (
                            user_id,
                            conversation_id,
                            trigger_message_id,
                            request_context
                        )
                        values (
                            :userId,
                            :conversationId,
                            :triggerMessageId,
                            cast(:requestContext as jsonb)
                        )
                        returning id
                        """)
                .param("userId", userId)
                .param("conversationId", conversationId)
                .param("triggerMessageId", triggerMessageId)
                .param("requestContext", objectMapper.writeValueAsString(requestContext))
                .query(UUID.class)
                .single();
        });
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
                            request_context::text,
                            progress_events::text,
                            result_data::text,
                            created_at,
                            started_at,
                            completed_at
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
                            request_context::text,
                            progress_events::text,
                            result_data::text,
                            created_at,
                            started_at,
                            completed_at
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
                                progress_events = '[]'::jsonb,
                                result_data = '{}'::jsonb,
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
                        "CHAT_REPLY_NOT_RETRYABLE",
                        "현재 상태에서는 AI 답변을 재시도할 수 없습니다."
                );
            }
            usageLimit.consume(jdbc, userId, AiUsageLimitService.Kind.CHAT);
            jdbc.sql("select requeue_chat_reply_job(:jobId, :userId)")
                    .param("jobId", jobId)
                    .param("userId", userId)
                    .query(Object.class)
                    .optional();
            return null;
        });
    }

    public void cancel(UUID userId, UUID jobId) {
        rls.write(userId, jdbc -> {
            int updated = jdbc.sql("""
                            update chat_reply_jobs
                            set
                                status = 'CANCELLED',
                                stage = 'CANCELLED',
                                stage_message = '사용자가 답변 생성을 취소했어요',
                                worker_id = null,
                                locked_until = null,
                                error_code = null,
                                error_message = null,
                                completed_at = now()
                            where id = :jobId
                              and status in ('QUEUED', 'RUNNING')
                            """)
                    .param("jobId", jobId)
                    .update();
            if (updated == 0) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "CHAT_REPLY_NOT_CANCELLABLE",
                        "현재 상태에서는 답변 생성을 취소할 수 없습니다."
                );
            }
            jdbc.sql("select finish_chat_reply_job(:jobId, :userId)")
                    .param("jobId", jobId)
                    .param("userId", userId)
                    .query(Object.class)
                    .optional();
            return null;
        });
        taskRegistry.cancel(jobId);
    }

    public AgentActionExecution executeAction(
            UUID userId,
            UUID jobId,
            String actionId
    ) {
        return rls.write(userId, jdbc -> {
            ActionJob actionJob = jdbc.sql("""
                            select
                                job.conversation_id,
                                job.trigger_message_id,
                                message.content as trigger_content,
                                job.status,
                                job.result_data::text
                            from chat_reply_jobs job
                            join conversation_messages message
                              on message.id = job.trigger_message_id
                            where job.id = :jobId
                            for update of job
                            """)
                    .param("jobId", jobId)
                    .query((rs, rowNum) -> new ActionJob(
                            rs.getObject("conversation_id", UUID.class),
                            rs.getObject("trigger_message_id", UUID.class),
                            rs.getString("trigger_content"),
                            rs.getString("status"),
                            rs.getString("result_data")
                    ))
                    .optional()
                    .orElseThrow(ChatReplyJobService::notFound);
            if (!"SUCCEEDED".equals(actionJob.status())) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "AGENT_ACTION_NOT_READY",
                        "AI 답변이 완료된 뒤 제안을 실행할 수 있습니다."
                );
            }

            ObjectNode result = requireObject(actionJob.resultData());
            JsonNode previous = result.path("actionExecutions").path(actionId);
            if ("SUCCEEDED".equals(previous.path("status").stringValue(""))) {
                return executionFrom(previous);
            }

            JsonNode proposed = findProposedAction(result, actionId);
            ChatAgentActionValidator.ValidatedAction action =
                    ChatAgentActionValidator.require(proposed, actionId);
            AgentActionExecution execution = executeValidatedAction(
                    jdbc, userId, jobId, actionJob, actionId, action
            );

            ObjectNode executions = result.path("actionExecutions").isObject()
                    ? (ObjectNode) result.path("actionExecutions")
                    : objectMapper.createObjectNode();
            executions.set(actionId, objectMapper.valueToTree(execution));
            result.set("actionExecutions", executions);
            jdbc.sql("""
                            update chat_reply_jobs
                            set result_data = cast(:resultData as jsonb)
                            where id = :jobId
                            """)
                    .param("resultData", objectMapper.writeValueAsString(result))
                    .param("jobId", jobId)
                    .update();

            jdbc.sql("""
                            update conversation_messages
                            set metadata = metadata || jsonb_build_object(
                                'actionExecutions', cast(:executions as jsonb)
                            )
                            where conversation_id = :conversationId
                              and role = 'ASSISTANT'
                              and metadata ->> 'chatReplyJobId' = :jobIdText
                            """)
                    .param("executions", objectMapper.writeValueAsString(executions))
                    .param("conversationId", actionJob.conversationId())
                    .param("jobIdText", jobId.toString())
                    .update();

            if (execution.postingId() != null && execution.analysisJobId() != null) {
                ObjectNode metadata = objectMapper.createObjectNode();
                metadata.put("analysisJobId", execution.analysisJobId().toString());
                metadata.put("postingId", execution.postingId().toString());
                metadata.put("status", "QUEUED");
                metadata.put("reusedAnalysis", execution.reusedAnalysis());
                metadata.put("agentActionId", actionId);
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
                            values (
                                :userId,
                                :conversationId,
                                'ASSISTANT',
                                'ANALYSIS_STATUS',
                                :content,
                                :postingId,
                                :analysisJobId,
                                cast(:metadata as jsonb)
                            )
                            """)
                        .param("userId", userId)
                        .param("conversationId", actionJob.conversationId())
                        .param("content", execution.message())
                        .param("postingId", execution.postingId())
                        .param("analysisJobId", execution.analysisJobId())
                        .param("metadata", objectMapper.writeValueAsString(metadata))
                        .update();
            }
            return execution;
        });
    }

    public void executeUserInitiatedAutomaticActions(
            UUID userId,
            UUID jobId,
            List<AiContracts.ProposedAgentAction> actions
    ) {
        if (actions == null || actions.isEmpty()) {
            return;
        }
        for (AiContracts.ProposedAgentAction action : actions) {
            if (action == null
                    || action.requiresConsent()
                    || !"ANALYZE_POSTING".equals(action.actionType())
                    || action.payload() == null) {
                continue;
            }
            if (!automaticAnalysisMatchesTrigger(userId, jobId, action)) {
                log.warn(
                        "Skipped automatic posting analysis {} because it was not bound to its trigger message",
                        action.actionId()
                );
                continue;
            }
            executeAction(userId, jobId, action.actionId());
        }
    }

    private boolean automaticAnalysisMatchesTrigger(
            UUID userId,
            UUID jobId,
            AiContracts.ProposedAgentAction proposed
    ) {
        return rls.read(userId, jdbc -> {
            TriggerMessage trigger = jdbc.sql("""
                            select message.id, message.content
                            from chat_reply_jobs job
                            join conversation_messages message
                              on message.id = job.trigger_message_id
                             and message.role = 'USER'
                            where job.id = :jobId
                            """)
                    .param("jobId", jobId)
                    .query((rs, rowNum) -> new TriggerMessage(
                            rs.getObject("id", UUID.class),
                            rs.getString("content")
                    ))
                    .optional()
                    .orElse(null);
            if (trigger == null || !containsExplicitAnalysisIntent(trigger.content())) {
                return false;
            }

            ChatAgentActionValidator.PostingAnalysisAction action;
            try {
                action = ChatAgentActionValidator.requirePostingAnalysis(
                        objectMapper.valueToTree(proposed),
                        proposed.actionId()
                );
            } catch (RuntimeException exception) {
                return false;
            }
            if ("URL".equals(action.sourceType())) {
                return urlsIn(trigger.content()).stream()
                        .anyMatch(url -> sameUrl(url, action.sourceUrl()));
            }
            String triggerText = normalizeText(trigger.content());
            String proposedText = normalizeText(action.rawText());
            if (triggerText.length() < 120 || proposedText.length() < 120) {
                return false;
            }
            String sample = proposedText.substring(0, Math.min(240, proposedText.length()));
            return triggerText.contains(sample);
        });
    }

    private boolean containsExplicitAnalysisIntent(String content) {
        String normalized = content == null ? "" : content.toLowerCase(Locale.ROOT);
        return normalized.contains("분석")
                || normalized.contains("준비도")
                || normalized.contains("평가해")
                || normalized.contains("analyze")
                || normalized.contains("analyse")
                || normalized.contains("evaluate");
    }

    private List<String> urlsIn(String content) {
        if (content == null || content.isBlank()) {
            return List.of();
        }
        java.util.ArrayList<String> urls = new java.util.ArrayList<>();
        Matcher matcher = HTTP_URL.matcher(content);
        while (matcher.find()) {
            urls.add(matcher.group().replaceAll("[),.\\]}>]+$", ""));
        }
        return List.copyOf(urls);
    }

    private boolean sameUrl(String left, String right) {
        if (left == null || right == null) {
            return false;
        }
        try {
            URI a = URI.create(left.trim()).normalize();
            URI b = URI.create(right.trim()).normalize();
            return a.getScheme().equalsIgnoreCase(b.getScheme())
                    && a.getHost().equalsIgnoreCase(b.getHost())
                    && normalizedPort(a) == normalizedPort(b)
                    && normalizedPath(a).equals(normalizedPath(b))
                    && java.util.Objects.equals(a.getRawQuery(), b.getRawQuery());
        } catch (RuntimeException exception) {
            return false;
        }
    }

    private int normalizedPort(URI uri) {
        if (uri.getPort() >= 0) return uri.getPort();
        return "https".equalsIgnoreCase(uri.getScheme()) ? 443 : 80;
    }

    private String normalizedPath(URI uri) {
        String path = uri.getPath() == null || uri.getPath().isBlank() ? "/" : uri.getPath();
        return path.length() > 1 && path.endsWith("/")
                ? path.substring(0, path.length() - 1)
                : path;
    }

    private String normalizeText(String value) {
        return value == null
                ? ""
                : value.toLowerCase(Locale.ROOT).replaceAll("\\s+", " ").trim();
    }

    private AgentActionExecution executeValidatedAction(
            JdbcClient jdbc,
            UUID userId,
            UUID jobId,
            ActionJob actionJob,
            String actionId,
            ChatAgentActionValidator.ValidatedAction action
    ) {
        return switch (action.actionType()) {
            case "ANALYZE_POSTING" -> executePostingAnalysis(
                    jdbc, userId, actionJob, actionId, action.postingAnalysis()
            );
            case "SAVE_DRAFT" -> executeDraftSave(jdbc, jobId, actionId);
            case "START_INTERVIEW" -> executeInterviewStart(jdbc, jobId, actionId);
            case "FIND_ALTERNATIVES" -> navigationExecution(
                    actionId,
                    action.actionType(),
                    "/postings",
                    "조건에 맞는 대체 공고를 확인할 수 있어요."
            );
            case "NAVIGATE" -> navigationExecution(
                    actionId,
                    action.actionType(),
                    allowedRoute(action.payload().path("route").stringValue("")),
                    "요청한 화면으로 이동할 수 있어요."
            );
            case "COMPARE" -> new AgentActionExecution(
                    actionId, "SUCCEEDED", action.actionType(),
                    "WORK_PRODUCT", null, null, null, false,
                    "비교 결과가 현재 답변에 표시되어 있어요.",
                    action.payload()
            );
            default -> throw new IllegalStateException("지원하지 않는 에이전트 작업입니다.");
        };
    }

    private AgentActionExecution executePostingAnalysis(
            JdbcClient jdbc,
            UUID userId,
            ActionJob actionJob,
            String actionId,
            ChatAgentActionValidator.PostingAnalysisAction action
    ) {
        // 에이전트가 정리한 공고로 V3 소스 등록 → 원문 확인 → 분석 시작까지 서버가 잇는다.
        // 종전에는 여기서 ID 없이 카드만 돌려주고 프론트가 같은 원문을 처음부터 재등록해
        // 이중 경로가 생겼다. 확인 게이트는 꺼져 있어 분석이 곧장 끝까지 진행된다.
        // V3 는 무음 배경 작업이다 — 대화에는 아무 행도 남기지 않고(DB 적재만),
        // 채팅 UI 는 에이전트 발화만 보여준다. 그래서 conversationId 를 넘기지 않는다.
        var acquired = v3SourceService.acquire(
                userId,
                new com.jobiss.analysis.v3.V3SourceService.AcquireCommand(
                        "TEXT", "CHAT", 1, null,
                        action.rawText(), null, null, null, null
                )
        );
        // 원문을 그대로 확인 처리한다 — 사용자가 고친 게 없는데 에이전트 정리본을
        // 사용자 확인본으로 기록하면 안 되고, 계약상 원문과 다른 verifiedText 는
        // corrections 없이는 거부된다(SourceVerificationRequest.validate_verification).
        String verifiedText = acquired.sourceDocument().path("rawText")
                .asString(action.rawText());
        v3SourceService.verify(
                userId,
                acquired.id(),
                new com.jobiss.analysis.v3.V3SourceService.VerifyCommand(
                        verifiedText, objectMapper.createArrayNode(), "USER", null
                )
        );
        var started = v3SourceService.startAnalysis(userId, acquired.id(), null);

        ObjectNode detail = objectMapper.createObjectNode();
        detail.put("sourceType", action.sourceType());
        if (action.sourceUrl() == null) {
            detail.putNull("sourceUrl");
        } else {
            detail.put("sourceUrl", action.sourceUrl());
        }
        detail.put("rawText", action.rawText());
        detail.put("reviewText", action.reviewText());
        detail.put("sourceId", acquired.id().toString());
        return new AgentActionExecution(
                actionId, "SUCCEEDED", "ANALYZE_POSTING",
                "POSTING_REVIEW", acquired.id(),
                started.postingId(), started.analysisJobId(),
                started.reusedAnalysis(),
                started.reusedAnalysis() && started.reuseMessage() != null
                        ? started.reuseMessage()
                        : "정리한 공고로 분석을 시작했어요.",
                detail
        );
    }

    private AgentActionExecution executeDraftSave(
            JdbcClient jdbc,
            UUID jobId,
            String actionId
    ) {
        UUID draftId = jdbc.sql("""
                        select draft.id
                        from cover_letter_drafts draft
                        join agent_work_products product
                          on product.id = draft.source_work_product_id
                        where product.chat_reply_job_id = :jobId
                        order by product.ordinal
                        limit 1
                        """)
                .param("jobId", jobId)
                .query(UUID.class)
                .optional()
                .orElseThrow(() -> invalidProduct("저장할 자소서 초안을 찾을 수 없습니다."));
        jdbc.sql("""
                        update cover_letter_drafts
                        set status = 'SAVED', updated_at = now()
                        where id = :draftId
                        """)
                .param("draftId", draftId)
                .update();
        return new AgentActionExecution(
                actionId, "SUCCEEDED", "SAVE_DRAFT", "COVER_LETTER_DRAFT",
                draftId, null, null, false,
                "자소서 초안을 저장했어요.", objectMapper.createObjectNode()
        );
    }

    private AgentActionExecution executeInterviewStart(
            JdbcClient jdbc,
            UUID jobId,
            String actionId
    ) {
        UUID sessionId = jdbc.sql("""
                        select interview.id
                        from interview_sessions interview
                        join agent_work_products product
                          on product.id = interview.source_work_product_id
                        where product.chat_reply_job_id = :jobId
                        order by product.ordinal
                        limit 1
                        """)
                .param("jobId", jobId)
                .query(UUID.class)
                .optional()
                .orElseThrow(() -> invalidProduct("시작할 면접 질문을 찾을 수 없습니다."));
        jdbc.sql("""
                        update interview_sessions
                        set status = 'IN_PROGRESS', updated_at = now()
                        where id = :sessionId
                        """)
                .param("sessionId", sessionId)
                .update();
        return new AgentActionExecution(
                actionId, "SUCCEEDED", "START_INTERVIEW", "INTERVIEW_SESSION",
                sessionId, null, null, false,
                "면접 연습을 시작했어요.", objectMapper.createObjectNode()
        );
    }

    private AgentActionExecution navigationExecution(
            String actionId,
            String actionType,
            String route,
            String message
    ) {
        ObjectNode result = objectMapper.createObjectNode();
        result.put("route", route);
        return new AgentActionExecution(
                actionId, "SUCCEEDED", actionType, "NAVIGATION", null,
                null, null, false, message, result
        );
    }

    private String allowedRoute(String route) {
        return switch (route) {
            case "/chat", "/storage", "/postings", "/career-map", "/settings" -> route;
            default -> throw invalidProduct("이동할 수 없는 화면입니다.");
        };
    }

    private static ApiException invalidProduct(String message) {
        return new ApiException(HttpStatus.CONFLICT, "AGENT_PRODUCT_NOT_FOUND", message);
    }

    private JsonNode findProposedAction(JsonNode result, String actionId) {
        for (JsonNode action : result.path("proposedActions")) {
            if (actionId.equals(action.path("actionId").stringValue(""))) {
                return action;
            }
        }
        return null;
    }

    private ObjectNode requireObject(String value) {
        JsonNode result = readJson(value, false);
        if (!(result instanceof ObjectNode object)) {
            throw new ApiException(
                    HttpStatus.CONFLICT,
                    "INVALID_AGENT_RESULT",
                    "저장된 AI 응답 형식이 올바르지 않습니다."
            );
        }
        return object;
    }

    private AgentActionExecution executionFrom(JsonNode value) {
        return new AgentActionExecution(
                value.path("actionId").stringValue(""),
                value.path("status").stringValue(""),
                value.path("actionType").stringValue("ANALYZE_POSTING"),
                value.path("resourceType").stringValue("ANALYSIS_JOB"),
                uuidOrNull(value.path("resourceId")),
                uuidOrNull(value.path("postingId")),
                uuidOrNull(value.path("analysisJobId")),
                value.path("reusedAnalysis").booleanValue(),
                value.path("message").stringValue(""),
                value.path("result")
        );
    }

    private UUID uuidOrNull(JsonNode value) {
        String text = value.stringValue("");
        return text.isBlank() ? null : UUID.fromString(text);
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
                readJson(rs.getString("request_context"), false),
                readJson(rs.getString("progress_events"), true),
                readJson(rs.getString("result_data"), false),
                rs.getObject("created_at", OffsetDateTime.class),
                rs.getObject("started_at", OffsetDateTime.class),
                rs.getObject("completed_at", OffsetDateTime.class)
        );
    }

    private JsonNode readJson(String value, boolean array) {
        if (value == null || value.isBlank()) {
            return array ? objectMapper.createArrayNode() : objectMapper.createObjectNode();
        }
        return objectMapper.readTree(value);
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
            JsonNode requestContext,
            JsonNode progressEvents,
            JsonNode result,
            OffsetDateTime createdAt,
            OffsetDateTime startedAt,
            OffsetDateTime completedAt
    ) {
    }

    public record AgentActionExecution(
            String actionId,
            String status,
            String actionType,
            String resourceType,
            UUID resourceId,
            UUID postingId,
            UUID analysisJobId,
            boolean reusedAnalysis,
            String message,
            JsonNode result
    ) {
    }

    private record ActionJob(
            UUID conversationId,
            UUID triggerMessageId,
            String triggerContent,
            String status,
            String resultData
    ) {
    }

    private record TriggerMessage(UUID id, String content) {
    }
}
