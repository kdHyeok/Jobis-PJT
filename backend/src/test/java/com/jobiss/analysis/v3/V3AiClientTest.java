package com.jobiss.analysis.v3;

import com.jobiss.analysis.AiServiceException;
import com.jobiss.analysis.AiAnalysisClient;
import com.jobiss.config.JobissProperties;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class V3AiClientTest {

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    void sendsContractHeadersWhenAcquiringSource() throws Exception {
        byte[] response = """
                {
                  "contractVersion":"jobis.ai.v3alpha1",
                  "sourceDocumentId":"source-1"
                }
                """.getBytes(StandardCharsets.UTF_8);
        List<String> received = new ArrayList<>();
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/v1/sources/acquire", exchange -> {
            received.add(exchange.getRequestHeaders().getFirst("X-JOBIS-AI-SECRET"));
            received.add(exchange.getRequestHeaders().getFirst("X-JOBIS-AI-CONTRACT"));
            exchange.getRequestBody().readAllBytes();
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, response.length);
            exchange.getResponseBody().write(response);
            exchange.close();
        });
        server.start();
        try {
            AiAnalysisClient client = client(server);
            JsonNode result = client.acquireSource(objectMapper.readTree("{}"));

            assertThat(result.path("sourceDocumentId").stringValue())
                    .isEqualTo("source-1");
            assertThat(received).containsExactly(
                    "test-v3-secret-123",
                    "jobis.ai.v3alpha1"
            );
        } finally {
            server.stop(0);
        }
    }

    @Test
    void acceptsVerificationContractOnNestedDocuments() throws Exception {
        byte[] response = """
                {
                  "sourceDocument": {
                    "contractVersion":"jobis.ai.v3alpha1",
                    "sourceDocumentId":"source-1"
                  },
                  "verifiedSnapshot": {
                    "contractVersion":"jobis.ai.v3alpha1",
                    "verifiedSnapshotId":"snapshot-1"
                  }
                }
                """.getBytes(StandardCharsets.UTF_8);
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/v1/sources/source-1/verify", exchange -> {
            exchange.getRequestBody().readAllBytes();
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, response.length);
            exchange.getResponseBody().write(response);
            exchange.close();
        });
        server.start();
        try {
            JsonNode result = client(server).verifySource(
                    "source-1",
                    objectMapper.readTree("{}")
            );

            assertThat(result.path("verifiedSnapshot")
                    .path("verifiedSnapshotId").stringValue())
                    .isEqualTo("snapshot-1");
        } finally {
            server.stop(0);
        }
    }

    @Test
    void rejectsVerificationWhenNestedContractIsMissing() throws Exception {
        byte[] response = """
                {
                  "sourceDocument": {
                    "contractVersion":"jobis.ai.v3alpha1",
                    "sourceDocumentId":"source-1"
                  },
                  "verifiedSnapshot": {
                    "verifiedSnapshotId":"snapshot-1"
                  }
                }
                """.getBytes(StandardCharsets.UTF_8);
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/v1/sources/source-1/verify", exchange -> {
            exchange.getRequestBody().readAllBytes();
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, response.length);
            exchange.getResponseBody().write(response);
            exchange.close();
        });
        server.start();
        try {
            assertThatThrownBy(() -> client(server).verifySource(
                    "source-1",
                    objectMapper.readTree("{}")
            )).isInstanceOfSatisfying(AiServiceException.class, exception ->
                    assertThat(exception.code())
                            .isEqualTo("UNSUPPORTED_CONTRACT_VERSION")
            );
        } finally {
            server.stop(0);
        }
    }

    @Test
    void streamsMonotonicProgressAndReturnsFinalResult() throws Exception {
        String body = """
                {"contractVersion":"jobis.ai.v3alpha1","type":"PROGRESS","sequence":1,
                 "progress":{"contractVersion":"jobis.ai.v3alpha1"}}
                {"contractVersion":"jobis.ai.v3alpha1","type":"RESULT","sequence":2,
                 "result":{"contractVersion":"jobis.ai.v3alpha1","status":"COMPLETED"}}
                """;
        byte[] response = body.lines()
                .map(String::trim)
                .reduce((left, right) -> left + right)
                .orElseThrow()
                .replace("}{", "}\n{")
                .getBytes(StandardCharsets.UTF_8);
        HttpServer server = streamServer(response, 200);
        try {
            List<JsonNode> events = new ArrayList<>();
            JsonNode result = client(server).streamCareerPipeline(
                    objectMapper.readTree("{}"),
                    events::add
            );

            assertThat(events).hasSize(2);
            assertThat(events).extracting(event -> event.path("sequence").intValue())
                    .containsExactly(1, 2);
            assertThat(result.path("status").stringValue()).isEqualTo("COMPLETED");
        } finally {
            server.stop(0);
        }
    }

    @Test
    void rejectsOutOfOrderPipelineEvents() throws Exception {
        byte[] response = ("""
                {"contractVersion":"jobis.ai.v3alpha1","type":"PROGRESS","sequence":2,
                 "progress":{"contractVersion":"jobis.ai.v3alpha1"}}
                {"contractVersion":"jobis.ai.v3alpha1","type":"RESULT","sequence":1,
                 "result":{"contractVersion":"jobis.ai.v3alpha1","status":"COMPLETED"}}
                """).lines()
                .map(String::trim)
                .reduce((left, right) -> left + right)
                .orElseThrow()
                .replace("}{", "}\n{")
                .getBytes(StandardCharsets.UTF_8);
        HttpServer server = streamServer(response, 200);
        try {
            assertThatThrownBy(() -> client(server).streamCareerPipeline(
                    objectMapper.readTree("{}"),
                    ignored -> { }
            )).isInstanceOfSatisfying(AiServiceException.class, exception ->
                    assertThat(exception.code()).isEqualTo("INVALID_AI_RESPONSE")
            );
        } finally {
            server.stop(0);
        }
    }

    @Test
    void preservesV3ErrorCodeFromErrorEnvelope() throws Exception {
        byte[] response = """
                {"contractVersion":"jobis.ai.v3alpha1","error":{
                  "code":"SOURCE_FETCH_FAILED",
                  "message":"Could not fetch posting",
                  "retryable":true
                }}
                """.getBytes(StandardCharsets.UTF_8);
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/v1/sources/acquire", exchange -> {
            exchange.getRequestBody().readAllBytes();
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(503, response.length);
            exchange.getResponseBody().write(response);
            exchange.close();
        });
        server.start();
        try {
            assertThatThrownBy(() -> client(server).acquireSource(
                    objectMapper.readTree("{}")
            )).isInstanceOfSatisfying(AiServiceException.class, exception -> {
                assertThat(exception.code()).isEqualTo("SOURCE_FETCH_FAILED");
                assertThat(exception.getMessage()).isEqualTo("Could not fetch posting");
            });
        } finally {
            server.stop(0);
        }
    }

    private HttpServer streamServer(byte[] response, int status) throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/v1/analysis-pipeline/stream", exchange -> {
            exchange.getRequestBody().readAllBytes();
            exchange.getResponseHeaders().set("Content-Type", "application/x-ndjson");
            exchange.sendResponseHeaders(status, response.length);
            exchange.getResponseBody().write(response);
            exchange.close();
        });
        server.start();
        return server;
    }

    private AiAnalysisClient client(HttpServer server) {
        return new AiAnalysisClient(
                new JobissProperties(
                        new JobissProperties.Auth(
                                "test-jwt-secret",
                                3600,
                                7200,
                                7200,
                                false
                        ),
                        new JobissProperties.Ai(
                                "http://127.0.0.1:" + server.getAddress().getPort(),
                                "test-v3-secret-123",
                                true,
                                1000,
                                60,
                                1
                        )
                ),
                objectMapper
        );
    }
}
