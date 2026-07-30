package com.jobiss.backend.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import tools.jackson.databind.ObjectMapper;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 대화용 AI 어댑터. 판단은 AI가 하고, 웹은 전달만 한다.
 * <p>
 * AI가 죽어도 사용자를 막다른 길에 두지 않도록 안전한 기본 응답으로 되돌아간다.
 * 진짜 AI가 생기면 http-url 만 바꾸면 된다(계약 동일).
 */
@Component
public class ConversationAiClient {

    /** 이력서를 통째로 붙여넣는 경우가 있어, AI로 넘기기 전에 발화 길이를 제한한다. */
    private static final int MAX_CONTENT = 4000;

    private final HttpClient httpClient = HttpClient.newBuilder()
            .version(HttpClient.Version.HTTP_1_1)   // h2c 업그레이드 방지(가짜 AI가 ws 서버 겸용)
            .connectTimeout(Duration.ofSeconds(5))
            .build();

    private final ObjectMapper om;
    private final String agentHttpUrl;

    public ConversationAiClient(ObjectMapper om, @Value("${jobiss.agent.http-url}") String agentHttpUrl) {
        this.om = om;
        this.agentHttpUrl = agentHttpUrl;
    }

    /**
     * 자유 대화. AI는 sessionId로 대화 맥락을 이어가므로 백엔드의 UUID conversationId를
     * 그대로 세션 키로 전달한다. 세션 키가 없으면 AI의 공용 기본 세션으로 보내지 않는다.
     * 반환: {reply, action, actionLabel} — 실패해도 null 이 아닌 안전한 기본값.
     */
    public Map<String, Object> chat(String sessionId, String message) {
        if (sessionId == null || sessionId.isBlank()) return fallback();

        try {
            String content = message == null ? "" : message;
            if (content.length() > MAX_CONTENT) content = content.substring(0, MAX_CONTENT);

            Map<String, Object> body = new LinkedHashMap<>();
            body.put("sessionId", sessionId);
            body.put("message", content);
            body.put("attachments", List.of());

            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(agentHttpUrl + "/chat"))
                    .timeout(Duration.ofSeconds(150))   // LLM 호출이라 길게
                    .header("Content-Type", "application/json; charset=utf-8")
                    .POST(HttpRequest.BodyPublishers.ofString(om.writeValueAsString(body), StandardCharsets.UTF_8))
                    .build();

            HttpResponse<String> response = httpClient.send(request,
                    HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() / 100 != 2) return fallback();

            Map<String, Object> parsed = om.readValue(response.body(), Map.class);
            if (parsed.get("reply") == null) return fallback();
            return parsed;
        } catch (Exception e) {
            return fallback();   // AI가 죽어도 대화는 끊기지 않아야 한다
        }
    }

    private static Map<String, Object> fallback() {
        return Map.of(
                "reply", "지금은 답을 정리하지 못했어요. 잠시 후 다시 말씀해 주세요.",
                "action", "NONE", "actionLabel", "");
    }
}
