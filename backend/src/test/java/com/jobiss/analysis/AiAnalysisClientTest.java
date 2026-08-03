package com.jobiss.analysis;

import com.sun.net.httpserver.HttpServer;
import com.jobiss.config.JobissProperties;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import tools.jackson.databind.ObjectMapper;

import java.nio.charset.StandardCharsets;
import java.net.InetSocketAddress;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class AiAnalysisClientTest {

    private final AiAnalysisClient client = client("http://localhost:8000");

    @Test
    void streamsAgentProgressBeforeReturningAnalysisResult() throws Exception {
        UUID runId = UUID.randomUUID();
        String rawResponseBody = """
                {"type":"RUN_STARTED","runId":"%s","sequence":1,
                 "occurredAt":"2026-07-31T10:00:00Z",
                 "stages":[{"id":"posting_analysis","label":"공고 분석",
                 "role":"공고 분석 에이전트","message":"요구사항을 정리합니다.",
                 "color":"#ce82ff"}],"stage":null,"result":null,
                 "errorCode":null,"errorMessage":null}
                {"type":"STAGE_UPDATED","runId":"%s","sequence":2,
                 "occurredAt":"2026-07-31T10:00:01Z","stages":[],
                 "stage":{"id":"posting_analysis","status":"RUNNING",
                 "message":"필수 조건을 확인하고 있어요."},"result":null,
                 "errorCode":null,"errorMessage":null}
                {"type":"RESULT","runId":"%s","sequence":3,
                 "occurredAt":"2026-07-31T10:00:02Z","stages":[],"stage":null,
                 "result":{"status":"COMPLETED","question":null,
                 "job":{"companyName":"Example","roleTitle":"Backend Engineer",
                 "employmentType":null,"experienceText":"신입",
                 "primaryTrack":"BACKEND",
                 "experienceRequirement":{"type":"NONE","minimumMonths":0,
                 "maximumMonths":null,"sourceText":"신입"},
                 "parsedData":{}},
                 "evaluation":{"verdict":"STRENGTHEN_THEN_APPLY",
                 "summary":"보강 후 지원할 수 있습니다.","reasons":["Java 검증 필요"]},
                 "competencyProposal":{"competencies":[{"ref":"java",
                 "canonicalKey":"skill.java","title":"Java","domain":"BACKEND",
                 "kind":"TECHNOLOGY","scopeDefinition":"Java 언어 기본기를 적용한다.",
                 "stage":"LANGUAGE","requiredLevel":2,"roadmapEligible":true,
                 "verificationMethod":"코드와 설명으로 검증"}],
                 "requirements":[{"competencyRef":"java","relation":"REQUIRED",
                 "sourceText":"Java 경험","confidence":0.9}],
                 "targetProject":{"title":"백엔드 과제","objective":"Java 검증",
                 "domainContext":"서비스 백엔드",
                 "requiredCompetencyRefs":["java"],"optionalCompetencyRefs":[],
                 "deliverables":["실행 코드"],"acceptanceCriteria":["API 동작"]}}},
                 "errorCode":null,"errorMessage":null}
                """.formatted(runId, runId, runId);
        String responseBody = java.util.Arrays
                .stream(rawResponseBody.strip().split(
                        "\\R\\s*(?=\\{\"type\")"
                ))
                .map(part -> part.replaceAll("\\R\\s*", " "))
                .collect(java.util.stream.Collectors.joining("\n"));
        byte[] responseBytes = responseBody.getBytes(StandardCharsets.UTF_8);
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/v1/analyses/stream", exchange -> {
            exchange.getRequestBody().readAllBytes();
            exchange.getResponseHeaders().set(
                    "Content-Type",
                    "application/x-ndjson"
            );
            exchange.sendResponseHeaders(200, responseBytes.length);
            exchange.getResponseBody().write(responseBytes);
            exchange.close();
        });
        server.start();
        try {
            AiAnalysisClient httpClient = client(
                    "http://127.0.0.1:" + server.getAddress().getPort()
            );
            List<AiContracts.AnalysisStreamEvent> events = new ArrayList<>();
            AiContracts.AnalysisResponse response = httpClient.analyze(
                    analysisRequest(runId),
                    events::add
            );

            assertThat(events).hasSize(3);
            assertThat(events.get(0).stages().get(0).id())
                    .isEqualTo("posting_analysis");
            assertThat(events.get(1).stage().status()).isEqualTo("RUNNING");
            assertThat(response.status()).isEqualTo("COMPLETED");
            assertThat(response.competencyProposal().competencies())
                    .extracting(AiContracts.AnalyzedCompetency::canonicalKey)
                    .containsExactly("skill.java");
        } finally {
            server.stop(0);
        }
    }

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
                                200,
                                2
                        )
                ),
                new ObjectMapper()
        );
    }

    private static AiContracts.AnalysisRequest analysisRequest(UUID runId) {
        return new AiContracts.AnalysisRequest(
                runId,
                new AiContracts.Posting(
                        UUID.randomUUID(),
                        "TEXT",
                        null,
                        "Java 백엔드 개발자를 채용합니다."
                ),
                new AiContracts.CareerSnapshot(
                        UUID.randomUUID(),
                        1,
                        List.of(),
                        List.of(),
                        new AiContracts.CareerGoalContext(
                                null,
                                null,
                                null,
                                "게임 플랫폼 백엔드 개발자"
                        )
                ),
                0,
                List.of(),
                null
        );
    }
}
