package com.jobiss.backend.controller;

import com.jobiss.backend.service.agent.FakeAgentClient;
import org.springframework.messaging.handler.annotation.DestinationVariable;
import org.springframework.messaging.handler.annotation.MessageMapping;
import org.springframework.messaging.handler.annotation.Payload;
import org.springframework.stereotype.Controller;
import tools.jackson.databind.ObjectMapper;

import java.util.Map;

/**
 * 브라우저 → 백엔드 STOMP 메시지 수신 (전화선 2의 클라→서버 방향).
 * 브라우저가 채팅에서 답변/질문을 보내면 여기서 받아 가짜 AI로 전달한다.
 *
 * 목적지: /app/agent/{analysisId}/message
 * 본문(JSON 문자열): { "text": "...", "replyTo": "q1" }
 */
@Controller
public class AgentStompController {

    private final FakeAgentClient agentClient;
    private final ObjectMapper om;

    public AgentStompController(FakeAgentClient agentClient, ObjectMapper om) {
        this.agentClient = agentClient;
        this.om = om;
    }

    @MessageMapping("/agent/{analysisId}/message")
    @SuppressWarnings("unchecked")
    public void onUserMessage(@DestinationVariable String analysisId, @Payload String body) {
        Map<String, Object> m = om.readValue(body, Map.class);
        String text = String.valueOf(m.get("text"));
        Object replyTo = m.get("replyTo");
        agentClient.sendUserMessage(analysisId, text, replyTo);
    }
}
