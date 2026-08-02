package com.jobiss.analysis;

import com.sun.net.httpserver.HttpServer;
import com.jobiss.config.JobissProperties;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import tools.jackson.databind.ObjectMapper;

import java.nio.charset.StandardCharsets;
import java.net.InetSocketAddress;
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class AiAnalysisClientTest {

    private final AiAnalysisClient client = client("http://localhost:8000");

    @Test
    void restClientReadsOctetStreamBeforeContractValidation() throws Exception {
        byte[] responseBody = """
                {
                  "message": "응답 완료",
                  "intent": "PROFILE_DISCOVERY",
                  "shouldRequestPosting": false,
                  "suggestedActions": []
                }
                """.getBytes(StandardCharsets.UTF_8);
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/v1/chat", exchange -> {
            exchange.getRequestBody().readAllBytes();
            exchange.getResponseHeaders().set(
                    "Content-Type",
                    MediaType.APPLICATION_OCTET_STREAM_VALUE
            );
            exchange.sendResponseHeaders(200, responseBody.length);
            exchange.getResponseBody().write(responseBody);
            exchange.close();
        });
        server.start();
        try {
            AiAnalysisClient httpClient = client(
                    "http://127.0.0.1:" + server.getAddress().getPort()
            );
            AiContracts.ChatResponse response = httpClient.chat(
                    new AiContracts.ChatRequest(
                            UUID.randomUUID(),
                            "Tester",
                            List.of(new AiContracts.ChatMessage("USER", "hello")),
                            new AiContracts.CareerSummary(
                                    List.of(),
                                    List.of(),
                                    List.of(),
                                    List.of()
                            )
                    )
            );

            assertThat(response.message()).isEqualTo("응답 완료");
        } finally {
            server.stop(0);
        }
    }

    @Test
    void parsesJsonBodyEvenWhenUpstreamUsesOctetStream() {
        byte[] body = """
                {
                  "message": "다음 경험부터 확인할게요.",
                  "intent": "PROFILE_DISCOVERY",
                  "shouldRequestPosting": false,
                  "suggestedActions": []
                }
                """.getBytes(StandardCharsets.UTF_8);

        AiContracts.ChatResponse response = client.parseResponse(
                body,
                MediaType.APPLICATION_OCTET_STREAM,
                AiContracts.ChatResponse.class
        );

        assertThat(response.message()).isEqualTo("다음 경험부터 확인할게요.");
        assertThat(response.intent()).isEqualTo("PROFILE_DISCOVERY");
    }

    @Test
    void reportsStableErrorForInvalidStructuredResponse() {
        byte[] body = "not-json".getBytes(StandardCharsets.UTF_8);

        assertThatThrownBy(() -> client.parseResponse(
                body,
                MediaType.APPLICATION_OCTET_STREAM,
                AiContracts.AnalysisResponse.class
        )).isInstanceOfSatisfying(AiServiceException.class, exception -> {
            assertThat(exception.code()).isEqualTo("INVALID_AI_RESPONSE");
            assertThat(exception.getMessage()).contains("application/octet-stream");
        });
    }

    private static AiAnalysisClient client(String baseUrl) {
        return new AiAnalysisClient(
                new JobissProperties(
                        new JobissProperties.Auth("test-secret", 3600, false),
                        new JobissProperties.Ai(
                                baseUrl,
                                "local-ai-secret",
                                false,
                                3000,
                                200
                        )
                ),
                new ObjectMapper()
        );
    }
}
