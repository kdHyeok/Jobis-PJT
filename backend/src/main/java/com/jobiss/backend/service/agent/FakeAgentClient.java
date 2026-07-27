package com.jobiss.backend.service.agent;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.stereotype.Component;
import tools.jackson.databind.ObjectMapper;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.WebSocket;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.CompletionStage;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 가짜 AI 에이전트 서버(ws://localhost:8000)에 접속하는 WebSocket 클라이언트 (전화선 1).
 *
 * 3단계: 받은 신호(PROGRESS/QUESTION/AGENT_MESSAGE/DONE)를 그대로
 *        /topic/analysis/{analysisId} 로 중계 → 그 분석을 구독한 브라우저에 실시간 도착.
 *        QUESTION 자동응답은 제거. 답은 브라우저에서 STOMP로 오고,
 *        sendUserMessage() 로 가짜 AI에 다시 전달한다.
 */
@Component
public class FakeAgentClient {

    private static final Logger log = LoggerFactory.getLogger(FakeAgentClient.class);

    private final ObjectMapper om;
    private final AgentResultService resultService;
    private final SimpMessagingTemplate messaging;
    private final String agentUrl;
    private final HttpClient httpClient = HttpClient.newHttpClient();

    /** analysisId -> 가짜 AI 와의 WebSocket 연결 (브라우저 답을 되보내기 위해 보관). */
    private final Map<String, WebSocket> sessions = new ConcurrentHashMap<>();
    /** 이미 시작한 분석 id (재연결·중복 begin 방어). startSession 진입 시 원자적으로 표시. */
    private final Set<String> started = ConcurrentHashMap.newKeySet();

    public FakeAgentClient(ObjectMapper om, AgentResultService resultService,
                           SimpMessagingTemplate messaging,
                           @Value("${jobiss.agent.url}") String agentUrl) {
        this.om = om;
        this.resultService = resultService;
        this.messaging = messaging;
        this.agentUrl = agentUrl;
    }

    /** 가짜 AI 서버에 접속해서 START(startJson)를 보내고 신호를 처리한다(비동기·멱등). */
    public void startSession(String analysisId, String startJson) {
        if (!started.add(analysisId)) {   // 이미 시작됨 → 중복 접속 방지(재연결 대비)
            log.info("[AI 세션 중복 요청 무시] analysisId={}", analysisId);
            return;
        }
        log.info("[AI 접속 시도] {} (analysisId={})", agentUrl, analysisId);
        httpClient.newWebSocketBuilder()
                .buildAsync(URI.create(agentUrl), new AgentListener(analysisId, startJson))
                .exceptionally(ex -> {
                    log.error("[AI 연결 실패] {} — 가짜 AI 서버(node server.js)가 켜져 있나요?", ex.getMessage());
                    started.remove(analysisId);
                    resultService.fail(analysisId, "AI 서버 연결 실패");
                    relayError(analysisId, "AI_UNREACHABLE", "AI 서버에 연결하지 못했어요. 가짜 AI 서버가 켜져 있는지 확인하고 다시 시도해 주세요.");
                    return null;
                });
    }

    /** 브라우저에서 온 사용자 메시지(답변/질문)를 가짜 AI 로 전달한다. */
    public void sendUserMessage(String analysisId, String text, Object replyTo) {
        WebSocket ws = sessions.get(analysisId);
        if (ws == null) {
            log.warn("[사용자→AI] 세션 없음: {}", analysisId);
            return;
        }
        Map<String, Object> msg = new LinkedHashMap<>();
        msg.put("type", "USER_MESSAGE");
        msg.put("analysisId", analysisId);
        msg.put("text", text);
        msg.put("replyTo", replyTo);
        ws.sendText(om.writeValueAsString(msg), true);
        log.info("[사용자→AI] {}", text);
    }

    /** 가짜 AI 신호를 그 분석을 구독한 브라우저로 중계. */
    private void relay(String analysisId, String rawJson) {
        messaging.convertAndSend("/topic/analysis/" + analysisId, rawJson);
    }

    /** 백엔드 발(연결 실패·끊김) 오류를 브라우저로 중계 — 복구 가능 표시 + 다음 행동 제시. */
    private void relayError(String analysisId, String code, String message) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("type", "ERROR");
        m.put("analysisId", analysisId);
        m.put("code", code);
        m.put("message", message);
        m.put("recoverable", true);
        m.put("actions", java.util.List.of("다시 시도", "공고 원문 붙여넣기", "새 분석 시작"));
        relay(analysisId, om.writeValueAsString(m));
    }

    private static String str(Object o) {
        return o == null ? null : String.valueOf(o);
    }

    private class AgentListener implements WebSocket.Listener {
        private final String analysisId;
        private final String startJson;
        private final StringBuilder buffer = new StringBuilder();
        private volatile boolean completed = false;   // DONE/ERROR로 정상 종료됐는지 — onClose에서 무한 ANALYZING 방지

        AgentListener(String analysisId, String startJson) {
            this.analysisId = analysisId;
            this.startJson = startJson;
        }

        @Override
        public void onOpen(WebSocket webSocket) {
            log.info("[AI 접속됨] START 전송 (analysisId={})", analysisId);
            sessions.put(analysisId, webSocket);
            webSocket.request(1);
            webSocket.sendText(startJson, true);
        }

        @Override
        public CompletionStage<?> onText(WebSocket webSocket, CharSequence data, boolean last) {
            buffer.append(data);
            if (last) {
                String message = buffer.toString();
                buffer.setLength(0);
                try {
                    handle(webSocket, message);
                } catch (Exception e) {
                    log.error("[메시지 처리 오류] {}", e.getMessage(), e);
                }
            }
            webSocket.request(1);
            return null;
        }

        @Override
        public void onError(WebSocket webSocket, Throwable error) {
            log.error("[AI 연결 오류] {}", error.getMessage());
            sessions.remove(analysisId);
            started.remove(analysisId);
            if (!completed) {
                completed = true;
                resultService.fail(analysisId, "연결 오류");
                relayError(analysisId, "CONNECTION_ERROR", "AI 연결 중 오류가 났어요. 다시 시도해 주세요.");
            }
        }

        @Override
        public CompletionStage<?> onClose(WebSocket webSocket, int statusCode, String reason) {
            sessions.remove(analysisId);
            started.remove(analysisId);
            if (!completed) {   // DONE/ERROR 없이 끊김 → 무한 ANALYZING 방지: FAILED로 종료 + 브라우저 통지
                completed = true;
                resultService.fail(analysisId, "완료 전 연결 종료");
                relayError(analysisId, "CONNECTION_LOST", "분석이 완료되기 전에 연결이 끊겼어요. 다시 시도해 주세요.");
            }
            return null;
        }

        @SuppressWarnings("unchecked")
        private void handle(WebSocket webSocket, String message) {
            // 1) 모든 신호를 브라우저로 실시간 중계 (원문 그대로)
            relay(analysisId, message);

            // 2) 서버 측 처리 (로그 + DONE 저장). QUESTION 자동응답은 하지 않는다.
            Map<String, Object> msg = om.readValue(message, Map.class);
            String type = String.valueOf(msg.get("type"));
            switch (type) {
                case "JOB_CONTEXT" -> {
                    String stackJson = om.writeValueAsString(msg.getOrDefault("stack", java.util.List.of()));
                    resultService.saveJobContext(analysisId,
                            str(msg.get("company")), str(msg.get("role")), str(msg.get("career")), stackJson);
                    log.info("  [중계+저장] JOB_CONTEXT · {} / {}", msg.get("company"), msg.get("role"));
                }
                case "PROGRESS" -> log.info("  [중계] PROGRESS {}% · {}", msg.get("percent"), msg.get("stage"));
                case "QUESTION" -> log.info("  [중계] QUESTION → 브라우저 (사용자 답변 대기)");
                case "AGENT_MESSAGE" -> log.info("  [중계] AGENT: {}", msg.get("text"));
                case "DONE" -> {
                    completed = true;
                    String resultJson = om.writeValueAsString(msg.get("result"));
                    resultService.complete(analysisId, resultJson);
                    log.info("  [중계+저장] DONE → analysis_results 저장 (COMPLETED)");
                    sessions.remove(analysisId);
                    webSocket.sendClose(WebSocket.NORMAL_CLOSURE, "done");
                }
                case "ERROR" -> {
                    completed = true;
                    log.error("  [중계] ERROR: {}", msg.get("message"));
                    resultService.fail(analysisId, String.valueOf(msg.get("message")));
                    sessions.remove(analysisId);
                    started.remove(analysisId);
                    webSocket.sendClose(WebSocket.NORMAL_CLOSURE, "error");
                }
                default -> log.info("  [중계] {} ", type);
            }
        }
    }
}
