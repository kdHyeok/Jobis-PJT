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

    @SuppressWarnings("unchecked")
    public ChatAskResponse ask(Long userId, ChatAskRequest req) {
        // 대화가 지정되지 않으면 새로 만든다 — 첫 발화만으로 사이드바에 대화창이 생긴다.
        Conversation conversation = (req.conversationId() == null)
                ? conversationService.create(userId, req.message())
                : conversationService.getOwned(userId, req.conversationId());

        Map<String, Object> body = new LinkedHashMap<>();
        // 대화 단위 세션 — 대화마다 AI 쪽 맥락이 격리된다.
        body.put("sessionId", conversation.sessionId());
        body.put("message", req.message() == null ? "" : req.message());

        // 이 턴에 실린 자료를 첨부로 넘긴다. 무엇을 할지는 AI(오케스트레이터)가 정한다.
        List<Map<String, Object>> attachments = new ArrayList<>();
        addAttachment(attachments, "resume", req.resumeText());
        addAttachment(attachments, "job_posting", req.postingText());
        body.put("attachments", attachments);

        try {
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(agentHttpUrl + "/chat"))
                    // 에이전트가 LLM 을 여러 번 부를 수 있어 넉넉히 준다.
                    .timeout(Duration.ofSeconds(180))
                    .header("Content-Type", "application/json; charset=utf-8")
                    .POST(HttpRequest.BodyPublishers.ofString(om.writeValueAsString(body), StandardCharsets.UTF_8))
                    .build();

            HttpResponse<String> response = httpClient.send(request,
                    HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() / 100 != 2) {
                throw new ApiException(HttpStatus.BAD_GATEWAY, "AI_CHAT_FAILED",
                        "대화 처리 실패(" + response.statusCode() + ")");
            }

            Map<String, Object> parsed = om.readValue(response.body(), Map.class);
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
            // 사용자에게 보이는 이력은 DB 에 남긴다(AI 세션은 브릿지 메모리라 재시작 시 사라진다).
            conversationService.appendTurn(conversation.getId(), req.message(), reply, dispatched);
            return new ChatAskResponse(conversation.getId(), conversation.getTitle(), reply,
                    str(parsed.get("intent")), dispatched, askedFor);
        } catch (ApiException e) {
            throw e;
        } catch (Exception e) {
            throw new ApiException(HttpStatus.BAD_GATEWAY, "AI_UNREACHABLE",
                    "AI 서버에 연결하지 못했어요. (웹 브릿지가 켜져 있나요?)");
        }
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
