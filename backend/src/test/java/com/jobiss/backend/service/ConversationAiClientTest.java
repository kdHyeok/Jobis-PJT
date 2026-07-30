package com.jobiss.backend.service;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;

class ConversationAiClientTest {

    private HttpServer server;

    @AfterEach
    void stopServer() {
        if (server != null) server.stop(0);
    }

    @Test
    void sendsConversationIdUsingTheV2ChatContract() throws Exception {
        ObjectMapper objectMapper = new ObjectMapper();
        AtomicReference<Map<String, Object>> capturedBody = new AtomicReference<>();

        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/chat", exchange -> {
            capturedBody.set(readJson(exchange, objectMapper));
            byte[] response = "{\"reply\":\"ok\",\"intent\":\"career_chat\"}"
                    .getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
            exchange.sendResponseHeaders(200, response.length);
            exchange.getResponseBody().write(response);
            exchange.close();
        });
        server.start();

        ConversationAiClient client = new ConversationAiClient(
                objectMapper, "http://127.0.0.1:" + server.getAddress().getPort());

        Map<String, Object> response = client.chat("conversation-uuid", "안녕하세요");

        assertEquals("ok", response.get("reply"));
        assertNotNull(capturedBody.get());
        assertEquals(Set.of("sessionId", "message", "attachments"), capturedBody.get().keySet());
        assertEquals("conversation-uuid", capturedBody.get().get("sessionId"));
        assertEquals("안녕하세요", capturedBody.get().get("message"));
        assertEquals(List.of(), capturedBody.get().get("attachments"));
        assertFalse(capturedBody.get().containsKey("messages"));
        assertFalse(capturedBody.get().containsKey("context"));
    }

    private static Map<String, Object> readJson(HttpExchange exchange, ObjectMapper objectMapper)
            throws IOException {
        String json = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
        return objectMapper.readValue(json, Map.class);
    }
}
