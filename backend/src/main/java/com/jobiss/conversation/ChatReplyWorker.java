package com.jobiss.conversation;

import com.jobiss.analysis.AiAnalysisClient;
import com.jobiss.analysis.AiContracts;
import com.jobiss.analysis.AnalysisClarificationNormalizer;
import com.jobiss.analysis.AiServiceException;
import com.jobiss.db.RlsTransactionExecutor;
import com.jobiss.posting.JobPostingService;
import com.jobiss.roadmap.RoadmapService;
import tools.jackson.databind.JsonNode;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.web.client.ResourceAccessException;
import tools.jackson.databind.ObjectMapper;

import java.net.InetAddress;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.Collectors;
import java.util.stream.Stream;

@Component
@ConditionalOnProperty(name = "jobiss.ai.worker-enabled", havingValue = "true")
public class ChatReplyWorker {

    private static final Logger log = LoggerFactory.getLogger(ChatReplyWorker.class);

    /** 큐의 재시도 상한과 같은 값이다(claim_chat_reply_job 의 {@code attempt_count < 3}). */
    private static final int MAX_ATTEMPTS = 3;

    /** 재시도까지 기다리는 시간 — 서버 재시작이 끝날 만큼(실측 공백 12초). */
    private static final int RETRY_DELAY_SECONDS = 15;

    private final JdbcClient jdbcClient;
    private final RlsTransactionExecutor rls;
    private final AiAnalysisClient aiClient;
    private final ObjectMapper objectMapper;
    private final JobPostingService postingService;
    private final RoadmapService roadmapService;
    private final String workerId;

    public ChatReplyWorker(
            JdbcClient jdbcClient,
            RlsTransactionExecutor rls,
            AiAnalysisClient aiClient,
            ObjectMapper objectMapper,
            JobPostingService postingService,
            RoadmapService roadmapService
    ) {
        this.jdbcClient = jdbcClient;
        this.rls = rls;
        this.aiClient = aiClient;
        this.objectMapper = objectMapper;
        this.postingService = postingService;
        this.roadmapService = roadmapService;
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
            AiContracts.ChatResponse response = aiClient.chat(
                    request,
                    step -> recordChatProgress(job, step)
            );
            if (response == null || response.message() == null || response.message().isBlank()) {
                throw new IllegalStateException("AI response did not include a message");
            }
            // 스트림을 지원하지 않는 AI 서버로 폴백한 턴은 진행 단계가 실시간으로 오지
            // 않는다 — 최종 응답에 같은 단계가 담겨 오므로 여기서 되메운다. 실시간이
            // 아닐 뿐, 어느 담당이 무엇을 했는지가 사라지지는 않는다.
            if (job.sequence().get() == 0) {
                for (AiContracts.ProgressStep step : response.progress() == null
                        ? List.<AiContracts.ProgressStep>of()
                        : response.progress()) {
                    recordChatProgress(job, step);
                }
            }
            complete(job, response);
            // 답변을 저장한 뒤에 적재한다 — 적재가 실패해도 대화는 이미 끝나 있어야 한다
            // (진행 기록과 같은 규칙: 부가 기록이 대화를 죽이지 않는다).
            ingestCollected(job, response.collected());
        } catch (Exception exception) {
            // AI 서버가 잠깐 없었을 뿐이면 남은 시도로 되돌린다 — 판정까지 다 끝낸 턴을
            // 서버 재시작 하나로 잃지 않게. 상한(3회)은 큐가 그대로 쥔다.
            if (isTransportFailure(exception) && job.attemptCount() < MAX_ATTEMPTS) {
                log.warn("Chat reply job {} could not reach the AI server (attempt {}/{}), "
                                + "requeueing in {}s: {}",
                        job.id(), job.attemptCount(), MAX_ATTEMPTS,
                        RETRY_DELAY_SECONDS, exception.getMessage());
                requeue(job, exception, RETRY_DELAY_SECONDS);
                return;
            }
            log.warn("Chat reply job {} failed: {}", job.id(), exception.getMessage());
            fail(job, exception);
        }
    }

    /**
     * AI 가 흘려 보낸 진행 단계를 기록한다 — 프론트는 이 작업 행을 이미 폴링한다.
     *
     * <p>공고를 채팅에 붙여넣는 흐름에는 분석 작업(analysis job)이 없어 진행 휠도 없다.
     * 그래서 "어느 담당이 무슨 도구로 무엇을 하는지"를 보여줄 통로가 이것뿐이다.
     *
     * <p>두 군데에 쓴다. {@code stage}/{@code stage_message} 는 <b>지금</b>을 가리키는 한
     * 칸이고(옛 한 줄 표시 유지), {@code chat_reply_agent_events} 는 <b>순서</b>를 남긴다 —
     * 대화창은 에이전트별 말풍선을 순서대로 그려야 하므로 한 칸으로는 부족하다(덮어쓰면
     * 마지막 단계만 남는다). 공고 분석 쪽 {@code analysis_agent_events} 와 같은 구조다.
     *
     * <p><b>진행 기록이 실패해도 대화를 죽이지 않는다.</b> 이건 창문이지 대화의 일부가
     * 아니다 — 실패하면 로그만 남기고 넘어간다.
     */
    private void recordChatProgress(ClaimedJob job, AiContracts.ProgressStep step) {
        if (step == null) {
            return;
        }
        String stage = clip(step.step(), 40);
        String message = Stream.of(step.label(), step.detail())
                .filter(part -> part != null && !part.isBlank())
                .collect(Collectors.joining(" · "));
        if (stage.isBlank() && message.isBlank()) {
            return;
        }
        int sequence = job.nextSequence();
        try {
            String eventData = objectMapper.writeValueAsString(step);
            rls.write(job.userId(), jdbc -> {
                jdbc.sql("""
                                update chat_reply_jobs
                                set
                                    stage = coalesce(nullif(:stage, ''), stage),
                                    stage_message = coalesce(nullif(:message, ''), stage_message),
                                    updated_at = now()
                                where id = :jobId
                                  and status = 'RUNNING'
                                """)
                        .param("stage", stage)
                        .param("message", clip(message, 2000))
                        .param("jobId", job.id())
                        .update();
                jdbc.sql("""
                                insert into chat_reply_agent_events (
                                    user_id,
                                    chat_reply_job_id,
                                    sequence,
                                    event_data
                                )
                                values (
                                    :userId,
                                    :jobId,
                                    :sequence,
                                    cast(:eventData as jsonb)
                                )
                                on conflict (chat_reply_job_id, sequence)
                                do update set event_data = excluded.event_data
                                """)
                        .param("userId", job.userId())
                        .param("jobId", job.id())
                        .param("sequence", sequence)
                        .param("eventData", eventData)
                        .update();
                return null;
            });
        } catch (RuntimeException exception) {
            log.debug("Chat progress not recorded for {}: {}", job.id(), exception.getMessage());
        }
    }

    private static String clip(String value, int limit) {
        String text = value == null ? "" : value.strip();
        return text.length() <= limit ? text : text.substring(0, limit);
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

            // 재시도는 처음부터 다시 실행한다 — 지난 시도의 단계를 남겨 두면 대화창에
            // 같은 에이전트가 두 번 말한 것처럼 보인다(분석 워커와 같은 규약).
            jdbc.sql("""
                            delete from chat_reply_agent_events
                            where chat_reply_job_id = :jobId
                            """)
                    .param("jobId", job.id())
                    .update();

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
                                  -- POSTING 도 사용자가 한 말이다. 공고 첨부 메시지는 내용이
                                  -- TEXT 와 똑같고(주소 또는 원문) kind 만 다른데, 전에는 첨부가
                                  -- AI 대화를 타지 않아 걸러도 무해했다. 첨부에도 답변 작업을
                                  -- 만들면서 그 전제가 깨졌다 — 실측(08-03): 첨부 턴이
                                  -- "사용자 발화가 없어요"로 실패했다(같은 URL 을 채팅창에 쓰면
                                  -- 되는데 왼쪽 박스로 넣으면 안 되던 이유가 이 한 줄이다).
                                  -- ANALYSIS_STATUS 는 계속 제외한다: 사용자의 말도 에이전트의
                                  -- 말도 아닌 시스템 알림이라, 넣으면 AI 가 "백그라운드 분석을
                                  -- 시작했어요"를 자기가 한 말로 읽는다.
                                  and kind in ('TEXT', 'POSTING')
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

            // 등록된 이력서 원문 — AI 가 세션 파일 없이도 이 대화를 이어갈 수 있게 턴마다 싣는다.
            // 폐기(archived_at)된 것과 원문이 빈 것은 뺀다. 최신 우선 5건 — 더 보내도 AI 쪽
            // 라이브러리 상한에서 잘린다.
            List<AiContracts.StoredResume> resumes = jdbc.sql("""
                            select id, title, source_type, raw_text, created_at
                            from career_sources
                            where user_id = :userId
                              and archived_at is null
                              and raw_text is not null
                              and btrim(raw_text) <> ''
                            order by created_at desc
                            limit 5
                            """)
                    .param("userId", job.userId())
                    .query((rs, rowNum) -> new AiContracts.StoredResume(
                            rs.getObject("id", UUID.class),
                            rs.getString("title"),
                            rs.getString("source_type"),
                            rs.getString("raw_text"),
                            rs.getObject("created_at", OffsetDateTime.class)
                    ))
                    .list();

            // 적재해 둔 선호·지속 사실을 되돌려 준다 — AI 가 세션 파일 없이 맥락을 세운다.
            ChatProfile profile = jdbc.sql("""
                            select chat_preferences, chat_facts
                            from user_goal_profiles
                            where user_id = :userId
                            """)
                    .param("userId", job.userId())
                    .query((rs, rowNum) -> new ChatProfile(
                            readJson(rs.getString("chat_preferences")),
                            readStringList(rs.getString("chat_facts"))
                    ))
                    .optional()
                    .orElse(new ChatProfile(null, List.of()));

            // 이 대화의 공고들 — parsed_data 를 함께 보내 AI 가 다시 파싱하지 않게 한다.
            List<AiContracts.StoredPosting> postings = jdbc.sql("""
                            select id, source_type, source_url, raw_text, parsed_data, created_at
                            from job_postings
                            where user_id = :userId
                              and conversation_id = :conversationId
                              and archived_at is null
                            order by created_at desc
                            limit 5
                            """)
                    .param("userId", job.userId())
                    .param("conversationId", trigger.conversationId())
                    .query((rs, rowNum) -> new AiContracts.StoredPosting(
                            rs.getObject("id", UUID.class),
                            rs.getString("source_type"),
                            rs.getString("source_url"),
                            rs.getString("raw_text"),
                            readJson(rs.getString("parsed_data")),
                            rs.getObject("created_at", OffsetDateTime.class)
                    ))
                    .list();

            // 여러 턴에 걸친 약속과 면접 진행 — AI 가 세션 파일 없이도 이어갈 수 있게 되돌려 준다.
            JsonNode sessionState = jdbc.sql("""
                            select state
                            from agent_session_state
                            where conversation_id = :conversationId
                            """)
                    .param("conversationId", trigger.conversationId())
                    .query((rs, rowNum) -> readJson(rs.getString("state")))
                    .optional()
                    .orElse(null);
            JsonNode interviewState = jdbc.sql("""
                            select state
                            from interview_sessions
                            where conversation_id = :conversationId
                            """)
                    .param("conversationId", trigger.conversationId())
                    .query((rs, rowNum) -> readJson(rs.getString("state")))
                    .optional()
                    .orElse(null);

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
                            savedEvidence,
                            resumes,
                            profile.preferences(),
                            profile.facts(),
                            postings,
                            sessionState,
                            interviewState
                    )
            );
        });
    }

    /**
     * 대화로 확보한 자산을 이 서비스의 테이블에 적재한다.
     *
     * <p>사용자가 채팅에 공고 URL 을 붙이면 AI 는 그것을 수집·파싱해 분석까지 하는데, 지금까지
     * 그 사실이 우리 쪽으로 돌아오지 않았다 — {@code ConversationService.send} 는 공고 첨부 UI
     * 경로에서만 공고를 만들고 채팅 요청은 메시지 본문만 싣는다. 그래서 대화로 준 공고는
     * 채용공고 페이지에도, 커리어지도에도 나타나지 않았다. <b>AI 세션은 캐시이고 진실의 출처는
     * 이 테이블이다.</b>
     *
     * <p>공고는 첨부 경로가 쓰는 {@code JobPostingService.create} 를 그대로 부른다 — 중복 지문
     * 처리·사용량 제한·분석 작업 큐잉이 전부 그 안에 있으므로 여기서 다시 만들지 않는다.
     *
     * <p>실패는 대화를 죽이지 않는다(경고만) — 답변은 이미 저장돼 있고, 적재는 다음 턴에 같은
     * 자산이 오면 다시 시도된다.
     */
    private void ingestCollected(ClaimedJob job, AiContracts.CollectedAssets collected) {
        if (collected == null) {
            return;
        }
        UUID conversationId = rls.read(job.userId(), jdbc -> jdbc.sql("""
                        select conversation_id from chat_reply_jobs where id = :jobId
                        """)
                .param("jobId", job.id())
                .query(UUID.class)
                .single());

        AiContracts.CollectedPosting posting = collected.posting();
        if (posting != null && posting.rawText() != null && !posting.rawText().isBlank()) {
            try {
                JobPostingService.CreatedPosting created = postingService.create(
                        job.userId(),
                        new JobPostingService.CreatePosting(
                                posting.sourceType(),
                                posting.sourceUrl(),
                                posting.rawText(),
                                conversationId
                        )
                );
                log.info("Chat-collected posting stored: job={} posting={} analysis={} reused={}",
                        job.id(), created.postingId(), created.analysisJobId(),
                        created.reusedAnalysis());
            } catch (Exception exception) {
                log.warn("Chat-collected posting was not stored (job {}): {}",
                        job.id(), exception.getMessage());
            }
        }

        ingestOutputs(job, conversationId, collected.outputs());

        AiContracts.CollectedResume resume = collected.resume();
        if (resume != null && resume.rawText() != null && !resume.rawText().isBlank()) {
            try {
                rls.write(job.userId(), jdbc -> jdbc.sql("""
                                insert into career_sources (
                                    user_id,
                                    source_type,
                                    title,
                                    raw_text,
                                    status
                                )
                                values (
                                    :userId,
                                    'TEXT',
                                    :title,
                                    :rawText,
                                    'QUEUED'
                                )
                                """)
                        .param("userId", job.userId())
                        .param("title", resume.title() == null || resume.title().isBlank()
                                ? "대화로 받은 이력서" : resume.title())
                        .param("rawText", resume.rawText())
                        .update());
                log.info("Chat-collected resume stored as a career source: job={}", job.id());
            } catch (Exception exception) {
                log.warn("Chat-collected resume was not stored (job {}): {}",
                        job.id(), exception.getMessage());
            }
        }

        boolean hasPreferences = collected.preferences() != null
                && !collected.preferences().isNull();
        boolean hasFacts = collected.facts() != null && !collected.facts().isEmpty();
        if (hasPreferences || hasFacts) {
            try {
                // 전량 upsert — AI 가 누적 전체를 보내므로 멱등이다. 온 것만 덮고 나머지는
                // 그대로 둔다(선호만 바뀐 턴에 사실을 지우지 않는다).
                rls.write(job.userId(), jdbc -> jdbc.sql("""
                                insert into user_goal_profiles (
                                    user_id,
                                    chat_preferences,
                                    chat_facts
                                )
                                values (
                                    :userId,
                                    cast(:preferences as jsonb),
                                    cast(:facts as jsonb)
                                )
                                on conflict (user_id) do update set
                                    chat_preferences = coalesce(
                                        excluded.chat_preferences,
                                        user_goal_profiles.chat_preferences
                                    ),
                                    chat_facts = coalesce(
                                        excluded.chat_facts,
                                        user_goal_profiles.chat_facts
                                    ),
                                    updated_at = now()
                                """)
                        .param("userId", job.userId())
                        .param("preferences", hasPreferences
                                ? objectMapper.writeValueAsString(collected.preferences())
                                : null)
                        .param("facts", hasFacts
                                ? objectMapper.writeValueAsString(collected.facts())
                                : null)
                        .update());
                log.info("Chat-collected profile stored: job={} preferences={} facts={}",
                        job.id(), hasPreferences,
                        hasFacts ? collected.facts().size() : 0);
            } catch (Exception exception) {
                log.warn("Chat-collected profile was not stored (job {}): {}",
                        job.id(), exception.getMessage());
            }
        }
    }

    /**
     * 대화가 만든 산출물을 이 서비스의 테이블에 적재한다(V23).
     *
     * <p>전에는 이 값들이 AI 세션 파일에만 남아, 그 파일을 지우면 판정·로드맵·초안이 사라졌다.
     * 각 항목은 <b>그 턴에 만들어졌을 때만</b> 온다 — 매 턴 전량을 받으면 append 형 테이블에
     * 같은 행이 계속 쌓인다.
     *
     * <p>실패는 대화를 죽이지 않는다(경고만). 답변은 이미 저장돼 있다.
     */
    private void ingestOutputs(
            ClaimedJob job,
            UUID conversationId,
            AiContracts.CollectedOutputs outputs
    ) {
        if (outputs == null) {
            return;
        }
        try {
            rls.write(job.userId(), jdbc -> {
                // 판정·로드맵·판정근거는 한 행에 모인다 — analysis_jobs.engine_result.
                // result_data(v2 형식)는 건드리지 않는다: writer 가 둘이 되면 갈린다.
                if (outputs.analysis() != null) {
                    jdbc.sql("""
                                    update analysis_jobs
                                    set engine_result = cast(:payload as jsonb),
                                        updated_at = now()
                                    where id = (
                                        select j.id
                                        from analysis_jobs j
                                        join job_postings p on p.id = j.posting_id
                                        where p.conversation_id = :conversationId
                                          and j.user_id = :userId
                                        order by j.created_at desc
                                        limit 1
                                    )
                                    """)
                            .param("payload", writeJson(mergeEngineResult(outputs)))
                            .param("conversationId", conversationId)
                            .param("userId", job.userId())
                            .update();
                }
                if (outputs.profile() != null) {
                    jdbc.sql("""
                                    insert into ai_user_profiles (user_id, profile)
                                    values (:userId, cast(:payload as jsonb))
                                    on conflict (user_id) do update set
                                        profile = excluded.profile,
                                        updated_at = now()
                                    """)
                            .param("userId", job.userId())
                            .param("payload", writeJson(outputs.profile()))
                            .update();
                }
                if (outputs.recommendations() != null) {
                    jdbc.sql("""
                                    insert into posting_recommendations (
                                        user_id, conversation_id, recommendations
                                    )
                                    values (:userId, :conversationId, cast(:payload as jsonb))
                                    """)
                            .param("userId", job.userId())
                            .param("conversationId", conversationId)
                            .param("payload", writeJson(outputs.recommendations()))
                            .update();
                }
                if (outputs.coverletter() != null) {
                    jdbc.sql("""
                                    insert into coverletter_drafts (
                                        user_id, conversation_id, draft
                                    )
                                    values (:userId, :conversationId, cast(:payload as jsonb))
                                    """)
                            .param("userId", job.userId())
                            .param("conversationId", conversationId)
                            .param("payload", writeJson(outputs.coverletter()))
                            .update();
                }
                if (outputs.interview() != null) {
                    // 면접은 여러 턴에 걸친 진행 상태다 — 대화당 한 행을 갱신한다.
                    jdbc.sql("""
                                    insert into interview_sessions (
                                        user_id, conversation_id, state
                                    )
                                    values (:userId, :conversationId, cast(:payload as jsonb))
                                    on conflict (conversation_id) do update set
                                        state = excluded.state,
                                        updated_at = now()
                                    """)
                            .param("userId", job.userId())
                            .param("conversationId", conversationId)
                            .param("payload", writeJson(outputs.interview()))
                            .update();
                }
                if (outputs.applicationPlan() != null) {
                    jdbc.sql("""
                                    insert into application_plans (
                                        user_id, conversation_id, plan
                                    )
                                    values (:userId, :conversationId, cast(:payload as jsonb))
                                    """)
                            .param("userId", job.userId())
                            .param("conversationId", conversationId)
                            .param("payload", writeJson(outputs.applicationPlan()))
                            .update();
                }
                if (outputs.preparationPeriodWeeks() != null
                        || outputs.availableHoursPerWeek() != null) {
                    jdbc.sql("""
                                    insert into user_goal_profiles (
                                        user_id,
                                        preparation_period_weeks,
                                        available_hours_per_week
                                    )
                                    values (:userId, :weeks, :hours)
                                    on conflict (user_id) do update set
                                        preparation_period_weeks = coalesce(
                                            excluded.preparation_period_weeks,
                                            user_goal_profiles.preparation_period_weeks
                                        ),
                                        available_hours_per_week = coalesce(
                                            excluded.available_hours_per_week,
                                            user_goal_profiles.available_hours_per_week
                                        ),
                                        updated_at = now()
                                    """)
                            .param("userId", job.userId())
                            .param("weeks", outputs.preparationPeriodWeeks())
                            .param("hours", outputs.availableHoursPerWeek())
                            .update();
                }
                if (outputs.competencyProposal() != null && outputs.jobContext() == null) {
                    // 불완전한 캐시는 만들지 않는다. 전에는 아직 분석 전인 job_postings 열로
                    // job 을 지어냈는데 primaryTrack·experienceRequirement 가 비어, 그 캐시를
                    // 재사용한 분석 작업이 NOT NULL 위반·NPE 로 죽었다(실측 08-04 01:13).
                    // 재료 없이 넣는 것보다 이번 캐시를 포기하는 쪽이 싸다 — 분석 작업이
                    // 엔진을 새로 돌면 완전한 결과가 같은 자리에 저장된다. (§2-6: 폴백은
                    // 이유를 삼키지 않는다)
                    log.warn("Chat-collected proposal without jobContext; "
                            + "skipping shared-analysis cache: job={}", job.id());
                }
                if (outputs.competencyProposal() != null && outputs.jobContext() != null) {
                    // 대화가 만든 지도 재료를 **공용 공고 분석**으로 저장한다. 이 공고의 분석
                    // 작업이 기존 재사용 경로(AnalysisWorker.reuseSharedAnalysis)로 집어
                    // user_competencies·posting_competency_requirements·
                    // posting_target_projects 에 적재하고, 그 뒤 지도가 자동으로 그려진다(D146).
                    //
                    // 적재 SQL 을 여기 복제하지 않는 이유: 그 코드는 노드 연결·준비도 계산과
                    // 얽힌 500줄이고, writer 가 둘이 되면 두 경로의 지도가 갈린다.
                    // clarification_fingerprint 는 **되묻기 없는 분석의 지문과 같은 값**이어야
                    // 분석 작업의 재사용 조회가 적중한다. 리터럴 '' 을 쓰면 영원히 빗나간다 —
                    // 조회 키는 fingerprint(빈 답변) = sha256("") 이다(실측 08-04: use_count 0,
                    // 분석 작업이 엔진을 다시 돌다 이력서 요청으로 실패해 지도가 안 그려졌다).
                    // job 은 AI 가 보낸 jobContext 만 쓴다 — 위 가드가 없는 캐시를 걸러 준다.
                    jdbc.sql("""
                                    insert into posting_analysis_cache (
                                        content_fingerprint,
                                        clarification_fingerprint,
                                        normalized_analysis
                                    )
                                    select
                                        posting.content_fingerprint,
                                        :clarificationFingerprint,
                                        jsonb_build_object(
                                            'job', cast(:jobContext as jsonb),
                                            'competencyProposal', cast(:proposal as jsonb)
                                        )
                                    from job_postings posting
                                    where posting.conversation_id = :conversationId
                                      and posting.user_id = :userId
                                      and posting.archived_at is null
                                    order by posting.created_at desc
                                    limit 1
                                    on conflict (content_fingerprint, clarification_fingerprint)
                                    do update set
                                        normalized_analysis = excluded.normalized_analysis,
                                        last_used_at = now()
                                    """)
                            .param("proposal", writeJson(outputs.competencyProposal()))
                            .param("jobContext", writeJson(outputs.jobContext()))
                            .param(
                                    "clarificationFingerprint",
                                    AnalysisClarificationNormalizer.fingerprint(List.of())
                            )
                            .param("conversationId", conversationId)
                            .param("userId", job.userId())
                            .update();
                }
                if (outputs.sessionState() != null) {
                    jdbc.sql("""
                                    insert into agent_session_state (
                                        conversation_id, user_id, state
                                    )
                                    values (:conversationId, :userId, cast(:payload as jsonb))
                                    on conflict (conversation_id) do update set
                                        state = excluded.state,
                                        updated_at = now()
                                    """)
                            .param("conversationId", conversationId)
                            .param("userId", job.userId())
                            .param("payload", writeJson(outputs.sessionState()))
                            .update();
                }
                return null;
            });
            log.info("Chat-collected outputs stored: job={}", job.id());
            // 대화가 만든 재료로도 지도를 자동으로 그린다 — 분석 작업 경로와 **같은 메서드**다.
            roadmapService.autoGenerateAfterAnalysis(job.userId());
        } catch (Exception exception) {
            log.warn("Chat-collected outputs were not stored (job {}): {}",
                    job.id(), exception.getMessage());
        }
    }

    /** 판정·로드맵·판정근거를 한 JSON 으로 — engine_result 한 칸에 모아 둔다. */
    private JsonNode mergeEngineResult(AiContracts.CollectedOutputs outputs) {
        var merged = objectMapper.createObjectNode();
        merged.set("analysis", outputs.analysis());
        if (outputs.roadmap() != null) {
            merged.set("roadmap", outputs.roadmap());
        }
        if (outputs.judgmentSummary() != null) {
            merged.set("judgmentSummary", outputs.judgmentSummary());
        }
        return merged;
    }

    private String writeJson(Object value) {
        return objectMapper.writeValueAsString(value);
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

    /**
     * AI 서버에 닿지 못한 실패인가 — 답변 내용과 무관한 전송 실패인가.
     *
     * <p>실측(08-04 09:20): 대화 도중 AI 서버가 재시작되자 "Connection reset"(진행 중이던
     * 턴)과 "Connection refused"(그 사이 큐에 들어온 턴)로 두 턴이 한 번에 죽었다. 이건
     * 답변이 틀린 것도, AI 가 거절한 것도 아니라 <b>말을 걸지 못한 것</b>이다 — 다시 걸면
     * 된다. 반대로 AI 가 스스로 낸 오류({@link AiServiceException})는 다시 걸어도 같은
     * 답이 나올 가능성이 높아 여기 넣지 않는다: 재시도는 매번 LLM 비용을 새로 쓴다.
     */
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

    /**
     * 전송 실패는 최종 실패가 아니다 — 큐에 남은 시도를 쓰게 되돌린다.
     *
     * <p>큐는 처음부터 3회를 허용했는데(claim_chat_reply_job 의 {@code attempt_count < 3})
     * 워커가 전송 실패까지 FAILED 로 닫아 그 예산을 한 번도 쓰지 않았다. 되돌릴 때
     * <b>{@link #finish} 를 부르지 않는다</b> — 큐 행을 지우면 다음 등록에서 시도 횟수가
     * 0 으로 돌아가 상한이 사라진다.
     *
     * <p>지연을 두는 이유: 서버 재시작은 십수 초가 걸리는데 워커는 3초마다 폴링한다.
     * 즉시 되돌리면 남은 두 번을 서버가 뜨기도 전에 태운다(실측의 공백은 12초였다).
     */
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
                            """)
                    .param("errorCode", classify(exception))
                    .param("errorMessage", safeMessage(exception))
                    .param("jobId", job.id())
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

    /**
     * 잡아 둔 작업 하나. {@code sequence} 는 이 턴의 진행 단계 번호를 매기는 카운터다 —
     * AI 스트림은 순번을 주지 않고, 순서를 잃으면 대화창이 단계를 뒤섞어 그린다.
     * 워커는 한 번에 한 작업만 처리하므로 이 카운터를 공유하는 스레드는 없다.
     */
    private record ClaimedJob(
            UUID id,
            UUID userId,
            int attemptCount,
            AtomicInteger sequence
    ) {
        ClaimedJob(UUID id, UUID userId, int attemptCount) {
            this(id, userId, attemptCount, new AtomicInteger());
        }

        int nextSequence() {
            return sequence.incrementAndGet();
        }
    }

    private record Trigger(
            UUID conversationId,
            UUID triggerMessageId,
            java.time.OffsetDateTime createdAt
    ) {
    }

    /** 되돌려 줄 선호·지속 사실({@code user_goal_profiles}). */
    private record ChatProfile(JsonNode preferences, List<String> facts) {
    }

    /** jsonb 문자열 → JsonNode. 비었거나 깨졌으면 null — 맥락 전달이 대화를 죽이지 않는다. */
    private JsonNode readJson(String raw) {
        if (raw == null || raw.isBlank()) {
            return null;
        }
        try {
            return objectMapper.readTree(raw);
        } catch (RuntimeException exception) {
            log.debug("chat_preferences not readable: {}", exception.getMessage());
            return null;
        }
    }

    /** jsonb 배열 문자열 → 문자열 목록. 비었거나 깨졌으면 빈 목록. */
    private List<String> readStringList(String raw) {
        JsonNode node = readJson(raw);
        if (node == null || !node.isArray()) {
            return List.of();
        }
        List<String> values = new ArrayList<>();
        node.forEach(item -> {
            String text = item.stringValue("");
            if (!text.isBlank()) {
                values.add(text);
            }
        });
        return values;
    }
}
