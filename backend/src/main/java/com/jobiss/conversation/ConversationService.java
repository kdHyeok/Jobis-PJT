package com.jobiss.conversation;

import com.jobiss.common.ApiException;
import com.jobiss.db.RlsTransactionExecutor;
import com.jobiss.posting.JobPostingService;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.time.OffsetDateTime;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;

@Service
public class ConversationService {

    private final RlsTransactionExecutor rls;
    private final JobPostingService postingService;
    private final ObjectMapper objectMapper;
    private final ChatReplyJobService chatReplyJobs;

    public ConversationService(
            RlsTransactionExecutor rls,
            JobPostingService postingService,
            ObjectMapper objectMapper,
            ChatReplyJobService chatReplyJobs
    ) {
        this.rls = rls;
        this.postingService = postingService;
        this.objectMapper = objectMapper;
        this.chatReplyJobs = chatReplyJobs;
    }

    public List<ConversationSummary> list(UUID userId) {
        return rls.read(userId, jdbc -> jdbc.sql("""
                        select
                            c.id,
                            c.title,
                            c.status,
                            c.last_message_at,
                            c.created_at,
                            exists (
                                select 1
                                from chat_reply_jobs pending_reply
                                where pending_reply.conversation_id = c.id
                                  and pending_reply.status in ('QUEUED', 'RUNNING')
                            ) as ai_reply_pending,
                            coalesce((
                                select recent_job.status = 'FAILED'
                                from (
                                    select reply.status::text as status, reply.updated_at
                                    from chat_reply_jobs reply
                                    where reply.conversation_id = c.id

                                    union all

                                    select analysis.status::text, analysis.updated_at
                                    from analysis_jobs analysis
                                    join job_postings posting on posting.id = analysis.posting_id
                                    where posting.conversation_id = c.id
                                ) recent_job
                                order by recent_job.updated_at desc
                                limit 1
                            ), false) as latest_job_failed,
                            coalesce((
                                select m.content
                                from conversation_messages m
                                where m.conversation_id = c.id
                                order by m.created_at desc, m.id desc
                                limit 1
                            ), '') as last_message,
                            coalesce((
                                select m.role::text
                                from conversation_messages m
                                where m.conversation_id = c.id
                                order by m.created_at desc, m.id desc
                                limit 1
                            ), '') as latest_message_role
                        from conversations c
                        order by c.last_message_at desc
                        limit 50
                        """)
                .query((rs, rowNum) -> new ConversationSummary(
                        rs.getObject("id", UUID.class),
                        rs.getString("title"),
                        rs.getString("status"),
                        rs.getString("last_message"),
                        rs.getObject("last_message_at", OffsetDateTime.class),
                        rs.getObject("created_at", OffsetDateTime.class),
                        rs.getBoolean("ai_reply_pending"),
                        rs.getBoolean("latest_job_failed"),
                        rs.getString("latest_message_role")
                ))
                .list());
    }

    public ConversationPage search(
            UUID userId,
            String query,
            String status,
            int page,
            int size
    ) {
        int safePage = Math.max(0, page);
        int safeSize = Math.min(100, Math.max(1, size));
        String normalizedQuery = query == null ? "" : query.trim();
        String normalizedStatus = status == null ? "ACTIVE" : status.trim().toUpperCase();
        if (!Set.of("ACTIVE", "ARCHIVED", "ALL").contains(normalizedStatus)) {
            throw invalidContext("대화 상태는 ACTIVE, ARCHIVED, ALL 중 하나여야 합니다.");
        }
        return rls.read(userId, jdbc -> {
            String sql = """
                    select
                        c.id,
                        c.title,
                        c.status,
                        c.last_message_at,
                        c.created_at,
                        exists (
                            select 1
                            from chat_reply_jobs pending_reply
                            where pending_reply.conversation_id = c.id
                              and pending_reply.status in ('QUEUED', 'RUNNING')
                        ) as ai_reply_pending,
                        coalesce((
                            select recent_job.status = 'FAILED'
                            from (
                                select reply.status::text as status, reply.updated_at
                                from chat_reply_jobs reply
                                where reply.conversation_id = c.id

                                union all

                                select analysis.status::text, analysis.updated_at
                                from analysis_jobs analysis
                                join job_postings posting on posting.id = analysis.posting_id
                                where posting.conversation_id = c.id
                            ) recent_job
                            order by recent_job.updated_at desc
                            limit 1
                        ), false) as latest_job_failed,
                        coalesce((
                            select m.content
                            from conversation_messages m
                            where m.conversation_id = c.id
                            order by m.created_at desc, m.id desc
                            limit 1
                        ), '') as last_message,
                        coalesce((
                            select m.role::text
                            from conversation_messages m
                            where m.conversation_id = c.id
                            order by m.created_at desc, m.id desc
                            limit 1
                        ), '') as latest_message_role,
                        count(*) over() as total_count
                    from conversations c
                    where (
                        :query = ''
                        or c.title ilike concat('%', :query, '%')
                        or exists (
                            select 1
                            from conversation_messages m
                            where m.conversation_id = c.id
                              and m.content ilike concat('%', :query, '%')
                        )
                    )
                      and (:status = 'ALL' or c.status::text = :status)
                    order by c.last_message_at desc, c.id desc
                    limit :limit offset :offset
                    """;
            var statement = jdbc.sql(sql)
                    .param("query", normalizedQuery)
                    .param("status", normalizedStatus)
                    .param("limit", safeSize)
                    .param("offset", safePage * safeSize);
            List<ConversationRow> rows = statement
                    .query((rs, rowNum) -> new ConversationRow(
                            new ConversationSummary(
                                    rs.getObject("id", UUID.class),
                                    rs.getString("title"),
                                    rs.getString("status"),
                                    rs.getString("last_message"),
                                    rs.getObject("last_message_at", OffsetDateTime.class),
                                    rs.getObject("created_at", OffsetDateTime.class),
                                    rs.getBoolean("ai_reply_pending"),
                                    rs.getBoolean("latest_job_failed"),
                                    rs.getString("latest_message_role")
                            ),
                            rs.getInt("total_count")
                    ))
                    .list();
            int total = rows.isEmpty() ? 0 : rows.get(0).total();
            return new ConversationPage(
                    rows.stream().map(ConversationRow::summary).toList(),
                    safePage,
                    safeSize,
                    total
            );
        });
    }

    public ConversationView create(UUID userId) {
        return rls.write(userId, jdbc -> {
            UUID id = jdbc.sql("""
                            insert into conversations (user_id)
                            values (:userId)
                            returning id
                            """)
                    .param("userId", userId)
                    .query(UUID.class)
                    .single();
            return load(jdbc, id);
        });
    }

    public ConversationView get(UUID userId, UUID conversationId) {
        return rls.read(userId, jdbc -> load(jdbc, conversationId));
    }

    public MessagePage messagesBefore(
            UUID userId,
            UUID conversationId,
            OffsetDateTime beforeCreatedAt,
            UUID beforeId,
            int limit
    ) {
        return rls.read(userId, jdbc -> {
            ensureConversationExists(jdbc, conversationId);
            int safeLimit = Math.min(200, Math.max(1, limit));
            List<MessageView> rows = new ArrayList<>(jdbc.sql("""
                            select *
                            from (
                                select
                                    id,
                                    role,
                                    kind,
                                    content,
                                    posting_id,
                                    analysis_job_id,
                                    metadata::text as metadata,
                                    created_at
                                from conversation_messages
                                where conversation_id = :conversationId
                                  and (created_at, id) < (:beforeCreatedAt, :beforeId)
                                order by created_at desc, id desc
                                limit :queryLimit
                            ) previous_messages
                            order by created_at, id
                            """)
                    .param("conversationId", conversationId)
                    .param("beforeCreatedAt", beforeCreatedAt)
                    .param("beforeId", beforeId)
                    .param("queryLimit", safeLimit + 1)
                    .query(this::mapMessage)
                    .list());
            boolean hasMore = rows.size() > safeLimit;
            if (hasMore) rows.remove(0);
            return new MessagePage(List.copyOf(rows), hasMore);
        });
    }

    public ConversationSummary rename(UUID userId, UUID conversationId, String title) {
        return rls.write(userId, jdbc -> {
            int updated = jdbc.sql("""
                            update conversations
                            set title = :title
                            where id = :conversationId
                            """)
                    .param("title", title.trim())
                    .param("conversationId", conversationId)
                    .update();
            if (updated == 0) throw notFound();
            return loadSummary(jdbc, conversationId);
        });
    }

    public SendResult send(UUID userId, UUID conversationId, SendCommand command) {
        AgentContext agentContext = normalizeContext(command.context());
        if (command.posting() == null) {
            validateAgentContext(userId, agentContext);
        }
        ExistingMessage duplicate = rls.read(userId, jdbc -> {
            ensureConversation(jdbc, conversationId);
            if (command.clientMessageId() == null) {
                return null;
            }
            return jdbc.sql("""
                            select id, created_at
                            from conversation_messages
                            where conversation_id = :conversationId
                              and client_message_id = :clientMessageId
                            """)
                    .param("conversationId", conversationId)
                    .param("clientMessageId", command.clientMessageId())
                    .query((rs, rowNum) -> new ExistingMessage(
                            rs.getObject("id", UUID.class),
                            rs.getObject("created_at", OffsetDateTime.class)
                    ))
                    .optional()
                    .orElse(null);
        });
        if (duplicate != null) {
            return rls.read(userId, jdbc -> loadExistingResult(jdbc, conversationId, duplicate));
        }

        MessageView userMessage = rls.write(userId, jdbc -> {
            var metadata = objectMapper.createObjectNode();
            if (command.posting() == null) {
                metadata.set("agentContext", objectMapper.valueToTree(agentContext));
            }
            // 공고 첨부는 발화 뒤에 원문(또는 URL)을 이어 붙여 에이전트가 읽게 한다 —
            // kind 를 TEXT 로 두어야 채팅 이력 조회(kind='TEXT')에 실린다.
            String content = command.content().trim();
            PostingAttachment attachment = command.posting();
            if (attachment != null) {
                String body = attachment.sourceUrl() != null && !attachment.sourceUrl().isBlank()
                        ? attachment.sourceUrl().trim()
                        : attachment.rawText();
                content = (content + "\n\n" + (body == null ? "" : body.trim())).trim();
            }
            return insertMessage(
                    jdbc,
                    userId,
                    conversationId,
                    "USER",
                    "TEXT",
                    content,
                    null,
                    null,
                    command.clientMessageId(),
                    metadata
            );
        });

        // 공고 첨부라고 해서 에이전트를 우회하지 않는다 — 대화를 받아 말하는 주체는 언제나
        // 에이전트다. 종전에는 여기서 자체 분석을 시작하고 조립 문구를 ASSISTANT 로 넣었다.
        // 공고 원문이 있으면 발화에 이어 붙여 일반 채팅 파이프라인(붙여넣기 공고 승격)을 태운다.

        UUID chatReplyJobId = chatReplyJobs.enqueue(
                userId,
                conversationId,
                userMessage.id(),
                objectMapper.valueToTree(agentContext)
        );
        rls.write(userId, jdbc -> {
            jdbc.sql("""
                            update conversation_messages
                            set metadata = metadata || jsonb_build_object(
                                'chatReplyJobId',
                                cast(:chatReplyJobId as text)
                            )
                            where id = :messageId
                            """)
                    .param("chatReplyJobId", chatReplyJobId)
                    .param("messageId", userMessage.id())
                    .update();
            return null;
        });
        return new SendResult(userMessage, null, null, chatReplyJobId, true);
    }

    public void archive(UUID userId, UUID conversationId) {
        rls.write(userId, jdbc -> {
            int updated = jdbc.sql("""
                            update conversations
                            set status = 'ARCHIVED'
                            where id = :conversationId
                            """)
                    .param("conversationId", conversationId)
                    .update();
            if (updated == 0) {
                throw notFound();
            }
            return null;
        });
    }

    public void restore(UUID userId, UUID conversationId) {
        rls.write(userId, jdbc -> {
            int updated = jdbc.sql("""
                            update conversations
                            set status = 'ACTIVE'
                            where id = :conversationId
                            """)
                    .param("conversationId", conversationId)
                    .update();
            if (updated == 0) throw notFound();
            return null;
        });
    }

    public void delete(UUID userId, UUID conversationId) {
        rls.write(userId, jdbc -> {
            int deleted = jdbc.sql("""
                            delete from conversations
                            where id = :conversationId
                            """)
                    .param("conversationId", conversationId)
                    .update();
            if (deleted == 0) {
                throw notFound();
            }
            return null;
        });
    }

    private ConversationView load(
            org.springframework.jdbc.core.simple.JdbcClient jdbc,
            UUID conversationId
    ) {
        ConversationHeader header = jdbc.sql("""
                        select id, title, status, last_message_at, created_at
                        from conversations
                        where id = :conversationId
                        """)
                .param("conversationId", conversationId)
                .query((rs, rowNum) -> new ConversationHeader(
                        rs.getObject("id", UUID.class),
                        rs.getString("title"),
                        rs.getString("status"),
                        rs.getObject("last_message_at", OffsetDateTime.class),
                        rs.getObject("created_at", OffsetDateTime.class)
                ))
                .optional()
                .orElseThrow(this::notFound);
        List<MessageView> messages = new ArrayList<>(jdbc.sql("""
                        select *
                        from (
                            select
                                id,
                                role,
                                kind,
                                content,
                                posting_id,
                                analysis_job_id,
                                metadata::text as metadata,
                                created_at
                            from conversation_messages
                            where conversation_id = :conversationId
                            order by created_at desc, id desc
                            limit 201
                        ) recent_messages
                        order by created_at, id
                        """)
                .param("conversationId", conversationId)
                .query(this::mapMessage)
                .list());
        boolean hasOlderMessages = messages.size() > 200;
        if (hasOlderMessages) messages.remove(0);
        return new ConversationView(
                header.id(),
                header.title(),
                header.status(),
                List.copyOf(messages),
                hasOlderMessages,
                header.lastMessageAt(),
                header.createdAt()
        );
    }

    private ConversationSummary loadSummary(
            org.springframework.jdbc.core.simple.JdbcClient jdbc,
            UUID conversationId
    ) {
        return jdbc.sql("""
                        select
                            c.id,
                            c.title,
                            c.status,
                            c.last_message_at,
                            c.created_at,
                            exists (
                                select 1
                                from chat_reply_jobs pending_reply
                                where pending_reply.conversation_id = c.id
                                  and pending_reply.status in ('QUEUED', 'RUNNING')
                            ) as ai_reply_pending,
                            coalesce((
                                select recent_job.status = 'FAILED'
                                from (
                                    select reply.status::text as status, reply.updated_at
                                    from chat_reply_jobs reply
                                    where reply.conversation_id = c.id

                                    union all

                                    select analysis.status::text, analysis.updated_at
                                    from analysis_jobs analysis
                                    join job_postings posting on posting.id = analysis.posting_id
                                    where posting.conversation_id = c.id
                                ) recent_job
                                order by recent_job.updated_at desc
                                limit 1
                            ), false) as latest_job_failed,
                            coalesce((
                                select m.content
                                from conversation_messages m
                                where m.conversation_id = c.id
                                order by m.created_at desc, m.id desc
                                limit 1
                            ), '') as last_message,
                            coalesce((
                                select m.role::text
                                from conversation_messages m
                                where m.conversation_id = c.id
                                order by m.created_at desc, m.id desc
                                limit 1
                            ), '') as latest_message_role
                        from conversations c
                        where c.id = :conversationId
                        """)
                .param("conversationId", conversationId)
                .query((rs, rowNum) -> new ConversationSummary(
                        rs.getObject("id", UUID.class),
                        rs.getString("title"),
                        rs.getString("status"),
                        rs.getString("last_message"),
                        rs.getObject("last_message_at", OffsetDateTime.class),
                        rs.getObject("created_at", OffsetDateTime.class),
                        rs.getBoolean("ai_reply_pending"),
                        rs.getBoolean("latest_job_failed"),
                        rs.getString("latest_message_role")
                ))
                .optional()
                .orElseThrow(this::notFound);
    }

    private MessageView mapMessage(ResultSet rs, int rowNum) throws SQLException {
        return new MessageView(
                rs.getObject("id", UUID.class),
                rs.getString("role"),
                rs.getString("kind"),
                rs.getString("content"),
                rs.getObject("posting_id", UUID.class),
                rs.getObject("analysis_job_id", UUID.class),
                readJson(rs.getString("metadata")),
                rs.getObject("created_at", OffsetDateTime.class)
        );
    }

    private void ensureConversation(
            org.springframework.jdbc.core.simple.JdbcClient jdbc,
            UUID conversationId
    ) {
        boolean exists = jdbc.sql("""
                        select exists (
                            select 1 from conversations
                            where id = :conversationId and status = 'ACTIVE'
                        )
                        """)
                .param("conversationId", conversationId)
                .query(Boolean.class)
                .single();
        if (!exists) {
            throw notFound();
        }
    }

    private void ensureConversationExists(
            org.springframework.jdbc.core.simple.JdbcClient jdbc,
            UUID conversationId
    ) {
        boolean exists = jdbc.sql("""
                        select exists (
                            select 1 from conversations
                            where id = :conversationId
                        )
                        """)
                .param("conversationId", conversationId)
                .query(Boolean.class)
                .single();
        if (!exists) throw notFound();
    }

    private MessageView insertMessage(
            org.springframework.jdbc.core.simple.JdbcClient jdbc,
            UUID userId,
            UUID conversationId,
            String role,
            String kind,
            String content,
            UUID postingId,
            UUID analysisJobId,
            UUID clientMessageId,
            JsonNode metadata
    ) {
        return jdbc.sql("""
                        insert into conversation_messages (
                            user_id,
                            conversation_id,
                            role,
                            kind,
                            content,
                            posting_id,
                            analysis_job_id,
                            client_message_id,
                            metadata
                        )
                        values (
                            :userId,
                            :conversationId,
                            cast(:role as message_role),
                            cast(:kind as message_kind),
                            :content,
                            :postingId,
                            :analysisJobId,
                            :clientMessageId,
                            cast(:metadata as jsonb)
                        )
                        returning
                            id,
                            role,
                            kind,
                            content,
                            posting_id,
                            analysis_job_id,
                            metadata::text,
                            created_at
                        """)
                .param("userId", userId)
                .param("conversationId", conversationId)
                .param("role", role)
                .param("kind", kind)
                .param("content", content)
                .param("postingId", postingId)
                .param("analysisJobId", analysisJobId)
                .param("clientMessageId", clientMessageId)
                .param("metadata", writeJson(metadata))
                .query((rs, rowNum) -> new MessageView(
                        rs.getObject("id", UUID.class),
                        rs.getString("role"),
                        rs.getString("kind"),
                        rs.getString("content"),
                        rs.getObject("posting_id", UUID.class),
                        rs.getObject("analysis_job_id", UUID.class),
                        readJson(rs.getString("metadata")),
                        rs.getObject("created_at", OffsetDateTime.class)
                ))
                .single();
    }

    private SendResult loadExistingResult(
            org.springframework.jdbc.core.simple.JdbcClient jdbc,
            UUID conversationId,
            ExistingMessage existing
    ) {
        List<MessageView> messages = jdbc.sql("""
                        select
                            id,
                            role,
                            kind,
                            content,
                            posting_id,
                            analysis_job_id,
                            metadata::text,
                            created_at
                        from conversation_messages
                        where conversation_id = :conversationId
                          and created_at >= :createdAt
                        order by created_at, id
                        limit 2
                        """)
                .param("conversationId", conversationId)
                .param("createdAt", existing.createdAt())
                .query((rs, rowNum) -> new MessageView(
                        rs.getObject("id", UUID.class),
                        rs.getString("role"),
                        rs.getString("kind"),
                        rs.getString("content"),
                        rs.getObject("posting_id", UUID.class),
                        rs.getObject("analysis_job_id", UUID.class),
                        readJson(rs.getString("metadata")),
                        rs.getObject("created_at", OffsetDateTime.class)
                ))
                .list();
        MessageView user = messages.stream()
                .filter(message -> message.id().equals(existing.id()))
                .findFirst()
                .orElseThrow(this::notFound);
        MessageView assistant = messages.stream()
                .filter(message -> "ASSISTANT".equals(message.role()))
                .findFirst()
                .orElse(null);
        UUID chatReplyJobId = jdbc.sql("""
                        select id
                        from chat_reply_jobs
                        where trigger_message_id = :messageId
                        """)
                .param("messageId", user.id())
                .query(UUID.class)
                .optional()
                .orElse(null);
        return new SendResult(
                user,
                assistant,
                user.analysisJobId(),
                chatReplyJobId,
                true
        );
    }

    private JsonNode readJson(String value) {
        return value == null ? objectMapper.createObjectNode() : objectMapper.readTree(value);
    }

    private AgentContext normalizeContext(AgentContext context) {
        if (context == null || context.mode() == null || context.mode().isBlank()) {
            return AgentContext.automatic();
        }
        return new AgentContext(
                context.mode(),
                uniqueIds(context.postingIds()),
                uniqueIds(context.careerSourceIds())
        );
    }

    private List<UUID> uniqueIds(List<UUID> ids) {
        if (ids == null || ids.isEmpty()) {
            return List.of();
        }
        Set<UUID> unique = new LinkedHashSet<>(ids);
        if (unique.contains(null) || unique.size() > 5) {
            throw invalidContext("한 번에 선택할 수 있는 자료는 종류별 최대 5개입니다.");
        }
        return List.copyOf(unique);
    }

    private void validateAgentContext(UUID userId, AgentContext context) {
        int postingMinimum = switch (context.mode()) {
            case "POSTING_QA", "INTERVIEW_PREP", "APPLICATION_PLAN" -> 1;
            case "POSTING_COMPARE" -> 2;
            case "COVER_LETTER" -> 1;
            default -> 0;
        };
        int sourceMinimum = switch (context.mode()) {
            case "RESUME_DIAGNOSIS" -> 1;
            case "RESUME_COMPARE" -> 2;
            case "COVER_LETTER" -> 1;
            default -> 0;
        };
        if (context.postingIds().size() < postingMinimum) {
            throw invalidContext("이 작업에는 공고를 " + postingMinimum + "개 이상 선택해야 합니다.");
        }
        if (context.careerSourceIds().size() < sourceMinimum) {
            throw invalidContext("이 작업에는 커리어 자료를 " + sourceMinimum + "개 이상 선택해야 합니다.");
        }

        rls.read(userId, jdbc -> {
            if (!context.postingIds().isEmpty()) {
                int found = jdbc.sql("""
                                select count(*)
                                from job_postings
                                where id in (:postingIds)
                                  and archived_at is null
                                """)
                        .param("postingIds", context.postingIds())
                        .query(Integer.class)
                        .single();
                if (found != context.postingIds().size()) {
                    throw invalidContext("선택한 공고 중 사용할 수 없는 항목이 있습니다.");
                }
            }
            if (!context.careerSourceIds().isEmpty()) {
                int found = jdbc.sql("""
                                select count(*)
                                from career_sources
                                where id in (:sourceIds)
                                  and status = 'CONFIRMED'
                                  and archived_at is null
                                """)
                        .param("sourceIds", context.careerSourceIds())
                        .query(Integer.class)
                        .single();
                if (found != context.careerSourceIds().size()) {
                    throw invalidContext("선택한 커리어 자료 중 사용할 수 없는 항목이 있습니다.");
                }
            }
            return null;
        });
    }

    private ApiException invalidContext(String message) {
        return new ApiException(
                HttpStatus.BAD_REQUEST,
                "INVALID_AGENT_CONTEXT",
                message
        );
    }

    private String writeJson(Object value) {
        return objectMapper.writeValueAsString(value);
    }

    private ApiException notFound() {
        return new ApiException(
                HttpStatus.NOT_FOUND,
                "CONVERSATION_NOT_FOUND",
                "대화를 찾을 수 없습니다."
        );
    }

    private record ConversationHeader(
            UUID id,
            String title,
            String status,
            OffsetDateTime lastMessageAt,
            OffsetDateTime createdAt
    ) {
    }

    private record ExistingMessage(UUID id, OffsetDateTime createdAt) {
    }

    private record ConversationRow(ConversationSummary summary, int total) {
    }

    public record PostingAttachment(
            String sourceType,
            String sourceUrl,
            String rawText
    ) {
    }

    public record SendCommand(
            UUID clientMessageId,
            String content,
            PostingAttachment posting,
            AgentContext context
    ) {
    }

    public record AgentContext(
            String mode,
            List<UUID> postingIds,
            List<UUID> careerSourceIds
    ) {
        public static AgentContext automatic() {
            return new AgentContext("AUTO", List.of(), List.of());
        }
    }

    public record ConversationSummary(
            UUID id,
            String title,
            String status,
            String lastMessage,
            OffsetDateTime lastMessageAt,
            OffsetDateTime createdAt,
            boolean aiReplyPending,
            boolean latestJobFailed,
            String latestMessageRole
    ) {
    }

    public record MessageView(
            UUID id,
            String role,
            String kind,
            String content,
            UUID postingId,
            UUID analysisJobId,
            JsonNode metadata,
            OffsetDateTime createdAt
    ) {
    }

    public record ConversationView(
            UUID id,
            String title,
            String status,
            List<MessageView> messages,
            boolean hasOlderMessages,
            OffsetDateTime lastMessageAt,
            OffsetDateTime createdAt
    ) {
    }

    public record MessagePage(
            List<MessageView> items,
            boolean hasMore
    ) {
    }

    public record ConversationPage(
            List<ConversationSummary> items,
            int page,
            int size,
            int total
    ) {
    }

    public record SendResult(
            MessageView userMessage,
            MessageView assistantMessage,
            UUID analysisJobId,
            UUID chatReplyJobId,
            boolean aiAvailable
    ) {
    }
}
