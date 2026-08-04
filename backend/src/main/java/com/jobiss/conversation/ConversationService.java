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
                        // **사용자향 문장은 에이전트가 쓴다.** 이 행은 진행 휠이 붙는 자리
                        // (analysis_job_id 를 실은 메시지)라 필요하지만, 그 말까지 우리가
                        // 지으면 같은 턴에 에이전트가 하는 답과 겹쳐 두 번 말하는 셈이 된다
                        // — 첨부에도 답변 작업을 만들면서(D145) 에이전트가 이 턴에 답한다.
                        // 재사용 안내는 그대로 둔다: 그건 이 서비스가 아는 사실(같은 공고의
                        // 기존 분석을 이어 쓴다)이고 에이전트는 모른다.
                        created.reusedAnalysis() ? created.reuseMessage() : "",
                        created.postingId(),
                        created.analysisJobId(),
                        null,
                        metadata
                );
            });
            // 공고 첨부도 **대화**다 — 에이전트가 답해야 한다.
            //
            // 전에는 여기서 chatReplyJobId 를 null 로 돌려줘 AI 대화 서버가 아예 불리지 않았다.
            // 그래서 같은 URL 을 채팅 본문에 쓰면 에이전트가 공고를 정리해 주는데, 왼쪽 첨부
            // 버튼으로 넣으면 "백그라운드 분석을 시작했어요" 한 줄만 오고 대화가 없었다 —
            // 사용자에게 그 둘은 같은 행동이므로 결과도 같아야 한다.
            //
            // 발화(userMessage.content)에 이미 주소나 원문이 들어 있으므로 AI 쪽은 채팅 본문에
            // URL 을 쓴 경우와 **같은 경로**를 탄다(chat.py 의 URL 인테이크). 여기서 따로 실어
            // 보낼 것은 없다.
            UUID attachmentChatJobId = enqueueChatReply(userId, conversationId, userMessage.id());
            return new SendResult(
                    userMessage,
                    assistant,
                    created.analysisJobId(),
                    attachmentChatJobId,
                    true
            );
        }

        UUID chatReplyJobId = enqueueChatReply(userId, conversationId, userMessage.id());
        return new SendResult(userMessage, null, null, chatReplyJobId, true);
    }

    /**
     * 사용자 메시지에 대한 AI 답변 작업을 큐에 넣고, 그 id 를 메시지 메타데이터에 심는다.
     *
     * <p>일반 발화 경로와 공고 첨부 경로가 **같은 함수**를 쓴다 — 두 벌로 두면 한쪽만 고쳐지고
     * (실제로 첨부 경로에는 이 호출이 아예 없어서 대화가 끊겼다) 화면 동작이 갈린다.
     */
    private UUID enqueueChatReply(UUID userId, UUID conversationId, UUID messageId) {
        UUID chatReplyJobId = chatReplyJobs.enqueue(userId, conversationId, messageId);
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
                    .param("messageId", messageId)
                    .update();
            return null;
        });
        return chatReplyJobId;
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
