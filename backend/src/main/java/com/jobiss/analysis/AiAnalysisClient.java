package com.jobiss.analysis;

import com.jobiss.config.JobissProperties;
import org.springframework.http.MediaType;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.nio.charset.StandardCharsets;
import java.util.function.Consumer;
import java.util.stream.Stream;

@Component
public class AiAnalysisClient {

    // 스트림 미지원 AI 서버(팀 ai-server 등, 404/405) 신호 — 호출부가 단건 /v1/chat 으로 폴백한다.
    public static final String STREAM_UNSUPPORTED = "AI_STREAM_UNSUPPORTED";

    private final RestClient restClient;
    private final HttpClient streamingClient;
    private final JobissProperties properties;
    private final ObjectMapper objectMapper;

    public AiAnalysisClient(JobissProperties properties, ObjectMapper objectMapper) {
        this.properties = properties;
        this.objectMapper = objectMapper;
        var requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(Duration.ofSeconds(5));
        requestFactory.setReadTimeout(Duration.ofSeconds(
                Math.max(30, properties.ai().requestTimeoutSeconds())
        ));
        this.restClient = RestClient.builder()
                .baseUrl(properties.ai().baseUrl())
                .requestFactory(requestFactory)
                .build();
        // NDJSON 스트리밍(chatStream)은 본문을 줄 단위로 읽어야 해서 RestClient 대신
        // java.net.http 를 쓴다 — RestClient 는 응답 전체를 받은 뒤에야 본문을 준다.
        this.streamingClient = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(5))
                .build();
    }

    public AiContracts.AnalysisResponse analyze(AiContracts.AnalysisRequest request) {
        return post("/v1/analyses", request, AiContracts.AnalysisResponse.class);
    }

    public AiContracts.ChatResponse chat(AiContracts.ChatRequest request) {
        return post("/v1/chat", request, AiContracts.ChatResponse.class);
    }

    /**
     * 대화 한 턴을 NDJSON 스트림(/v1/chat/stream)으로 처리한다 — 진행 단계가 올 때마다
     * onProgress 를 부르고, 마지막 result 줄의 ChatResponse 를 돌려준다.
     * 스트림 미지원 서버(404/405)면 {@link #STREAM_UNSUPPORTED} 코드로 실패한다 —
     * 호출부(ChatReplyWorker)가 단건 chat() 으로 폴백한다.
     */
    public AiContracts.ChatResponse chatStream(
            AiContracts.ChatRequest request,
            Consumer<AiContracts.ProgressStep> onProgress
    ) {
        HttpRequest httpRequest;
        try {
            httpRequest = HttpRequest.newBuilder()
                    .uri(URI.create(properties.ai().baseUrl() + "/v1/chat/stream"))
                    .timeout(Duration.ofSeconds(Math.max(30, properties.ai().requestTimeoutSeconds())))
                    .header("Content-Type", "application/json")
                    .header("X-JOBISS-AI-SECRET", properties.ai().sharedSecret())
                    .POST(HttpRequest.BodyPublishers.ofString(
                            objectMapper.writeValueAsString(request), StandardCharsets.UTF_8))
                    .build();
        } catch (RuntimeException exception) {
            throw new AiServiceException("AI_SERVICE_ERROR", "AI 스트림 요청을 만들지 못했습니다.", exception);
        }

        HttpResponse<Stream<String>> response;
        try {
            response = streamingClient.send(httpRequest, HttpResponse.BodyHandlers.ofLines());
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new AiServiceException("AI_SERVICE_ERROR", "AI 스트리밍이 중단되었습니다.", exception);
        } catch (IOException exception) {
            throw new AiServiceException("AI_SERVICE_ERROR", "AI 스트리밍 연결에 실패했습니다.", exception);
        }
        if (response.statusCode() == 404 || response.statusCode() == 405) {
            throw new AiServiceException(STREAM_UNSUPPORTED, "AI 서버가 스트리밍을 지원하지 않습니다.");
        }
        if (response.statusCode() >= 400) {
            throw new AiServiceException("AI_SERVICE_ERROR",
                    "AI 스트리밍 요청이 실패했습니다. HTTP " + response.statusCode());
        }

        AiContracts.ChatResponse result = null;
        try (Stream<String> lines = response.body()) {
            for (String line : (Iterable<String>) lines::iterator) {
                if (line == null || line.isBlank()) {
                    continue;
                }
                JsonNode node = objectMapper.readTree(line);
                switch (node.path("type").stringValue("")) {
                    case "progress" -> {
                        try {
                            onProgress.accept(new AiContracts.ProgressStep(
                                    node.path("step").stringValue(""),
                                    node.path("label").stringValue(""),
                                    node.path("detail").stringValue(""),
                                    node.path("elapsedMs").isNumber()
                                            ? node.path("elapsedMs").intValue() : null
                            ));
                        } catch (RuntimeException ignored) {
                            // 진행 표시는 관찰이다 — 콜백 실패가 본 응답을 막지 않는다.
                        }
                    }
                    case "result" -> result = objectMapper.treeToValue(
                            node.path("response"), AiContracts.ChatResponse.class);
                    case "error" -> throw new AiServiceException(
                            node.path("code").stringValue("AI_SERVICE_ERROR"),
                            node.path("message").stringValue("AI 스트리밍 처리에 실패했습니다."));
                    default -> { }
                }
            }
        } catch (AiServiceException exception) {
            throw exception;
        } catch (java.io.UncheckedIOException exception) {
            // 서버 재시작·네트워크 절단으로 스트림이 중간에 끊긴 경우 — 파싱 결함이 아니라
            // 재시도 대상이다(실측 2026-07-31: AI 재배포 중이던 요청이 "해석 실패"로 보였다).
            throw new AiServiceException("AI_SERVICE_ERROR",
                    "AI 스트리밍이 중간에 끊겼습니다. 다시 시도해 주세요.", exception);
        } catch (RuntimeException exception) {
            throw new AiServiceException("INVALID_AI_RESPONSE",
                    "AI 스트림 응답을 해석하지 못했습니다: " + exception.getMessage(), exception);
        }
        if (result == null) {
            throw new AiServiceException("EMPTY_AI_RESPONSE", "AI 스트림이 결과 없이 종료되었습니다.");
        }
        return result;
    }

    public AiContracts.EvidenceVerificationResponse verifyEvidence(
            AiContracts.EvidenceVerificationRequest request
    ) {
        return post(
                "/v1/evidence-verifications",
                request,
                AiContracts.EvidenceVerificationResponse.class
        );
    }

    public AiContracts.CareerExtractionResponse extractCareer(
            AiContracts.CareerExtractionRequest request
    ) {
        return post(
                "/v1/career-extractions",
                request,
                AiContracts.CareerExtractionResponse.class
        );
    }

    private <T> T post(String uri, Object body, Class<T> responseType) {
        ResponseEntity<byte[]> response = restClient.post()
                .uri(uri)
                .contentType(MediaType.APPLICATION_JSON)
                .accept(MediaType.APPLICATION_JSON)
                .header("X-JOBISS-AI-SECRET", properties.ai().sharedSecret())
                .body(body)
                .retrieve()
                .onStatus(HttpStatusCode::isError, (request, errorResponse) ->
                        handleError(
                                errorResponse.getStatusCode(),
                                errorResponse.getBody().readAllBytes()
                        )
                )
                .toEntity(byte[].class);
        return parseResponse(
                response.getBody(),
                response.getHeaders().getContentType(),
                responseType
        );
    }

    <T> T parseResponse(byte[] body, MediaType contentType, Class<T> responseType) {
        if (body == null || body.length == 0) {
            throw new AiServiceException(
                    "EMPTY_AI_RESPONSE",
                    "AI 서버가 빈 응답을 반환했습니다."
            );
        }
        try {
            // 로컬 AI 서버나 중간 프록시가 JSON 본문을 octet-stream으로
            // 표시하는 경우에도 실제 본문 계약을 직접 검증한다.
            return objectMapper.readValue(body, responseType);
        } catch (RuntimeException exception) {
            String mediaType = contentType == null ? "unknown" : contentType.toString();
            throw new AiServiceException(
                    "INVALID_AI_RESPONSE",
                    "AI 서버 응답을 분석 JSON으로 해석하지 못했습니다. 응답 형식: "
                            + mediaType,
                    exception
            );
        }
    }

    private void handleError(HttpStatusCode status, byte[] body) throws IOException {
        String code = "AI_SERVICE_ERROR";
        String message = status.is5xxServerError()
                ? "AI 서비스가 일시적으로 응답하지 않습니다."
                : "AI 서비스 요청을 처리하지 못했습니다.";
        try {
            JsonNode root = objectMapper.readTree(new String(body, StandardCharsets.UTF_8));
            JsonNode detail = root.path("detail");
            if (detail.isObject()) {
                if (!detail.path("code").isMissingNode()) {
                    String upstreamCode = detail.path("code").stringValue("");
                    if (!upstreamCode.isBlank()) {
                        code = upstreamCode;
                    }
                }
                if (!detail.path("message").isMissingNode()) {
                    String upstreamMessage = detail.path("message").stringValue("");
                    if (!upstreamMessage.isBlank()) {
                        message = upstreamMessage;
                    }
                }
            }
        } catch (RuntimeException ignored) {
            // A non-JSON upstream response is reduced to the stable public message above.
        }
        throw new AiServiceException(code, message);
    }
}
