package com.jobiss.backend.service;

import com.jobiss.backend.domain.Conversation;
import com.jobiss.backend.dto.chat.AskedFor;
import com.jobiss.backend.dto.chat.ChatAskRequest;
import com.jobiss.backend.dto.chat.ChatAskResponse;
import com.jobiss.backend.exception.ApiException;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import tools.jackson.databind.ObjectMapper;

import org.springframework.http.MediaType;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * 일반 대화 중계 — 웹은 사용자 발화를 그대로 AI(웹 브릿지 POST /chat)에 넘기고 답만 받는다.
 *
 * 분석(WebSocket)과는 다른 경로다. 분석은 "공고 하나를 판정"하는 긴 작업이고,
 * 이쪽은 "무엇이든 물어보기" — 오케스트레이터가 의도를 보고 담당 에이전트를 고른다.
 * 대화 맥락은 sessionId(사용자별 고정)로 AI 쪽 세션 저장소에 쌓인다.
 */
@Service
public class ChatService {

    private final ObjectMapper om;
    private final String agentHttpUrl;
    // HTTP/1.1 고정 — EvidenceImportService 와 같은 이유(업그레이드 헤더 오인 방지).
    private final HttpClient httpClient = HttpClient.newBuilder()
            .version(HttpClient.Version.HTTP_1_1)
            .connectTimeout(Duration.ofSeconds(5))
            .build();

    private final ConversationService conversationService;

    public ChatService(ObjectMapper om, @Value("${jobiss.agent.http-url}") String agentHttpUrl,
                       ConversationService conversationService) {
        this.om = om;
        this.agentHttpUrl = agentHttpUrl;
        this.conversationService = conversationService;
    }

    public ChatAskResponse ask(Long userId, ChatAskRequest req) {
        Conversation conversation = resolveConversation(userId, req);
        try {
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(agentHttpUrl + "/chat"))
                    // 에이전트가 LLM 을 여러 번 부를 수 있어 넉넉히 준다.
                    .timeout(Duration.ofSeconds(180))
                    .header("Content-Type", "application/json; charset=utf-8")
                    .POST(HttpRequest.BodyPublishers.ofString(om.writeValueAsString(buildBody(conversation, req)), StandardCharsets.UTF_8))
                    .build();

            HttpResponse<String> response = httpClient.send(request,
                    HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() / 100 != 2) {
                throw new ApiException(HttpStatus.BAD_GATEWAY, "AI_CHAT_FAILED",
                        "대화 처리 실패(" + response.statusCode() + ")");
            }
            return finishTurn(conversation, req, om.readValue(response.body(), Map.class));
        } catch (ApiException e) {
            throw e;
        } catch (Exception e) {
            throw new ApiException(HttpStatus.BAD_GATEWAY, "AI_UNREACHABLE",
                    "AI 서버에 연결하지 못했어요. (웹 브릿지가 켜져 있나요?)");
        }
    }

    // 진행 스트림 전용 풀 — MVC 요청 스레드를 잡아두지 않는다.
    private static final ExecutorService STREAM_POOL = Executors.newCachedThreadPool();

    /**
     * 대화 한 턴 + 실시간 진행(SSE). 브릿지 /chat/stream 을 그대로 중계한다.
     *
     * 브릿지의 progress 이벤트는 해석 없이 통과시키고, done 이벤트만 /api/chat 응답과
     * 같은 형태(ChatAskResponse)로 바꿔 보낸다 — 프론트는 두 경로에서 같은 응답을 받는다.
     * 대화 이력 영속(appendTurn)도 done 시점에 동일하게 수행한다.
     */
    public SseEmitter askStream(Long userId, ChatAskRequest req) {
        Conversation conversation = resolveConversation(userId, req);
        SseEmitter emitter = new SseEmitter(300_000L);
        STREAM_POOL.submit(() -> {
            try {
                HttpRequest request = HttpRequest.newBuilder()
                        .uri(URI.create(agentHttpUrl + "/chat/stream"))
                        .timeout(Duration.ofSeconds(290))
                        .header("Content-Type", "application/json; charset=utf-8")
                        .POST(HttpRequest.BodyPublishers.ofString(om.writeValueAsString(buildBody(conversation, req)), StandardCharsets.UTF_8))
                        .build();
                HttpResponse<InputStream> response = httpClient.send(request,
                        HttpResponse.BodyHandlers.ofInputStream());
                if (response.statusCode() / 100 != 2) {
                    sendEvent(emitter, Map.of("type", "error", "message",
                            "대화 처리 실패(" + response.statusCode() + ")"));
                    emitter.complete();
                    return;
                }
                try (BufferedReader reader = new BufferedReader(
                        new InputStreamReader(response.body(), StandardCharsets.UTF_8))) {
                    String line;
                    while ((line = reader.readLine()) != null) {
                        if (!line.startsWith("data: ")) continue;
                        Map<String, Object> event = om.readValue(line.substring(6), Map.class);
                        if ("done".equals(String.valueOf(event.get("type")))
                                && event.get("response") instanceof Map<?, ?> parsed) {
                            ChatAskResponse done = finishTurn(conversation, req, (Map<String, Object>) parsed);
                            sendEvent(emitter, Map.of("type", "done", "response", done));
                        } else {
                            sendEvent(emitter, event);
                        }
                    }
                }
                emitter.complete();
            } catch (Exception e) {
                sendEvent(emitter, Map.of("type", "error", "message",
                        "AI 서버에 연결하지 못했어요. (웹 브릿지가 켜져 있나요?)"));
                emitter.complete();
            }
        });
        return emitter;
    }

    private void sendEvent(SseEmitter emitter, Map<String, Object> event) {
        try {
            emitter.send(SseEmitter.event().data(om.writeValueAsString(event), MediaType.APPLICATION_JSON));
        } catch (Exception ignored) {
            // 클라이언트가 끊었을 뿐 — 처리 실패가 아니다.
        }
    }

    /** 대화가 지정되지 않으면 새로 만든다 — 첫 발화만으로 사이드바에 대화창이 생긴다. */
    private Conversation resolveConversation(Long userId, ChatAskRequest req) {
        return (req.conversationId() == null)
                ? conversationService.create(userId, req.message())
                : conversationService.getOwned(userId, req.conversationId());
    }

    /** 브릿지에 보낼 요청 본문. 이 턴에 실린 자료를 첨부로 — 무엇을 할지는 AI 가 정한다. */
    private Map<String, Object> buildBody(Conversation conversation, ChatAskRequest req) {
        Map<String, Object> body = new LinkedHashMap<>();
        // 대화 단위 세션 — 대화마다 AI 쪽 맥락이 격리된다.
        body.put("sessionId", conversation.sessionId());
        body.put("message", req.message() == null ? "" : req.message());
        List<Map<String, Object>> attachments = new ArrayList<>();
        addAttachment(attachments, "resume", req.resumeText());
        addAttachment(attachments, "job_posting", req.postingText());
        // 빈 섹션 보완 입력 — AI 쪽에서 기존 이력서에 덧붙인다(교체 아님).
        addAttachment(attachments, "resume_extra", req.resumeExtraText());
        body.put("attachments", attachments);
        return body;
    }

    /** 브릿지 응답 → ChatAskResponse + 대화 이력 영속. /chat 과 /chat/stream 이 공유한다. */
    @SuppressWarnings("unchecked")
    private ChatAskResponse finishTurn(Conversation conversation, ChatAskRequest req,
                                       Map<String, Object> parsed) {
        List<String> dispatched = new ArrayList<>();
        if (parsed.get("dispatched") instanceof List<?> list) {
            for (Object o : list) {
                if (o != null) dispatched.add(String.valueOf(o));
            }
        }
        // 에이전트가 무엇을 요청했는지 — 프론트가 그 자료용 입력 카드를 그때 띄운다.
        List<AskedFor> askedFor = new ArrayList<>();
        if (parsed.get("followUpQuestions") instanceof List<?> list) {
            for (Object o : list) {
                if (!(o instanceof Map<?, ?> q)) continue;
                String question = str(q.get("question"));
                if (question.isBlank()) question = str(q.get("text"));
                if (question.isBlank()) continue;
                askedFor.add(new AskedFor(str(q.get("field")), question));
            }
        }
        String reply = parsed.get("reply") == null ? "" : String.valueOf(parsed.get("reply"));
        // 파싱된 공고·이력서 항목 — 해석하지 않고 그대로 중계한다(프론트 우측 패널용).
        Map<String, Object> context = (parsed.get("context") instanceof Map<?, ?> ctx)
                ? (Map<String, Object>) ctx : Map.of();
        // 사용자에게 보이는 이력은 DB 에 남긴다(AI 세션은 브릿지 메모리라 재시작 시 사라진다).
        conversationService.appendTurn(conversation.getId(), req.message(), reply, dispatched);
        return new ChatAskResponse(conversation.getId(), conversation.getTitle(), reply,
                str(parsed.get("intent")), dispatched, askedFor, context);
    }

    /** 빈 값이 아니면 첨부 목록에 추가. URL 로 보이면 sourceType 을 url 로 알려준다. */
    private static void addAttachment(List<Map<String, Object>> out, String kind, String value) {
        if (value == null || value.isBlank()) {
            return;
        }
        String trimmed = value.trim();
        boolean isUrl = trimmed.startsWith("http://") || trimmed.startsWith("https://");
        Map<String, Object> att = new LinkedHashMap<>();
        att.put("kind", kind);
        att.put("sourceType", isUrl ? "url" : "text");
        att.put("value", trimmed);
        out.add(att);
    }

    private static String str(Object o) {
        return o == null ? "" : String.valueOf(o);
    }
}
