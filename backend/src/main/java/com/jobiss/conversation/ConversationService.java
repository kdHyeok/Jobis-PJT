package com.jobiss.conversation;

import com.jobiss.common.ApiException;
import com.jobiss.db.RlsTransactionExecutor;
import com.jobiss.posting.JobPostingService;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

@Service
public class ConversationService {

    /**
     * 공고 원문으로 인정하는 최소 길이.
     *
     * <p><b>이 숫자는 AI 가 정한다</b> — {@code AI/src/jobis_ai/orchestrator/attachment_kind.py}
     * 의 {@code MIN_ASSET_CHARS}. 이보다 짧으면 AI 가 자산으로 승격하지 않으므로, 여기서
     * 통과시키면 "저장은 됐는데 분석이 안 되는" 공고가 생긴다. AI 쪽 값이 바뀌면 같이 바꾼다.
     */
    private static final int POSTING_MIN_CHARS = 40;

    private static final String GREETING = """
            안녕하세요. 지금 어떤 일을 해왔고 앞으로 어디로 가고 싶은지부터 편하게 이야기해 주세요.
            공고가 있다면 나중에 첨부해도 되고, 아직 없다면 직무 탐색부터 함께 시작할 수 있어요.
            """;

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
                            coalesce((
                                select m.content
                                from conversation_messages m
                                where m.conversation_id = c.id
                                order by m.created_at desc, m.id desc
                                limit 1
                            ), '') as last_message
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
                        rs.getObject("created_at", OffsetDateTime.class)
                ))
                .list());
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
            insertMessage(
                    jdbc,
                    userId,
                    id,
                    "ASSISTANT",
                    "TEXT",
                    GREETING,
                    null,
                    null,
                    null,
                    objectMapper.createObjectNode()
            );
            return load(jdbc, id);
        });
    }

    public ConversationView get(UUID userId, UUID conversationId) {
        return rls.read(userId, jdbc -> load(jdbc, conversationId));
    }

    public SendResult send(UUID userId, UUID conversationId, SendCommand command) {
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

        MessageView userMessage = rls.write(userId, jdbc -> insertMessage(
                jdbc,
                userId,
                conversationId,
                "USER",
                command.posting() == null ? "TEXT" : "POSTING",
                command.content().trim(),
                null,
                null,
                command.clientMessageId(),
                objectMapper.createObjectNode()
        ));

        if (command.posting() != null) {
            PostingAttachment attachment = command.posting();
            JobPostingService.CreatedPosting created = postingService.create(
                    userId,
                    new JobPostingService.CreatePosting(
                            attachment.sourceType(),
                            attachment.sourceUrl(),
                            postingBody(attachment),
                            conversationId
                    )
            );
            MessageView assistant = rls.write(userId, jdbc -> {
                jdbc.sql("""
                                update conversation_messages
                                set posting_id = :postingId, analysis_job_id = :analysisJobId
                                where id = :messageId
                                """)
                        .param("postingId", created.postingId())
                        .param("analysisJobId", created.analysisJobId())
                        .param("messageId", userMessage.id())
                        .update();
                var metadata = objectMapper.createObjectNode();
                metadata.put("analysisJobId", created.analysisJobId().toString());
                metadata.put("postingId", created.postingId().toString());
                metadata.put("status", created.status());
                metadata.put("reusedAnalysis", created.reusedAnalysis());
                return insertMessage(
                        jdbc,
                        userId,
                        conversationId,
                        "ASSISTANT",
                        "ANALYSIS_STATUS",
                        created.reusedAnalysis() ? created.reuseMessage() :
                        "공고를 저장했고 백그라운드 분석을 시작했어요. 다른 대화를 계속해도 완료되면 알려드릴게요.",
                        created.postingId(),
                        created.analysisJobId(),
                        null,
                        metadata
                );
            });
            return new SendResult(
                    userMessage,
                    assistant,
                    created.analysisJobId(),
                    null,
                    true
            );
        }

        UUID chatReplyJobId = chatReplyJobs.enqueue(
                userId,
                conversationId,
                userMessage.id()
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
                        order by created_at, id
                        limit 200
                        """)
                .param("conversationId", conversationId)
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
        return new ConversationView(
                header.id(),
                header.title(),
                header.status(),
                messages,
                header.lastMessageAt(),
                header.createdAt()
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

    /**
     * 저장할 공고 본문.
     *
     * <p>URL 만 준 경우 원문이 없다 — 그건 정상이다. AI 가 URL 자산을 수집해 내용을 채운다
     * ({@code posting_fetch}). 다만 {@code job_postings.raw_text} 는 NOT NULL 이고 AI 계약도
     * 최소 1자를 요구하므로, 수집 전까지의 자리표시로 <b>주소 자체</b>를 넣는다. 빈 문자열을
     * 넣으면 "원문을 받았는데 비어 있다"와 구분되지 않는다.
     *
     * <p>둘 다 비면 예외 — 무엇을 분석할지가 없다.
     */
    private static String postingBody(PostingAttachment attachment) {
        String body = attachment.rawText() == null ? "" : attachment.rawText().trim();
        String url = attachment.sourceUrl() == null ? "" : attachment.sourceUrl().trim();
        boolean hasUrl = url.startsWith("http://") || url.startsWith("https://");

        if (body.length() >= POSTING_MIN_CHARS) {
            return body;
        }
        if (hasUrl) {
            return url;
        }
        throw new ApiException(
                HttpStatus.BAD_REQUEST,
                "POSTING_CONTENT_REQUIRED",
                "공고 주소(http/https)나 원문 " + POSTING_MIN_CHARS + "자 이상 중 하나는 있어야 합니다."
        );
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
            PostingAttachment posting
    ) {
    }

    public record ConversationSummary(
            UUID id,
            String title,
            String status,
            String lastMessage,
            OffsetDateTime lastMessageAt,
            OffsetDateTime createdAt
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
            OffsetDateTime lastMessageAt,
            OffsetDateTime createdAt
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
