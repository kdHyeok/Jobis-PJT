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

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.time.Duration;
import java.nio.charset.StandardCharsets;
import java.util.function.Consumer;

@Component
public class AiAnalysisClient {

    private final RestClient restClient;
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
    }

    public AiContracts.AnalysisResponse analyze(AiContracts.AnalysisRequest request) {
        return post("/v1/analyses", request, AiContracts.AnalysisResponse.class);
    }

    public AiContracts.AnalysisResponse analyze(
            AiContracts.AnalysisRequest request,
            Consumer<AiContracts.AnalysisStreamEvent> progressConsumer
    ) {
        try {
            return postAnalysisStream(request, progressConsumer);
        } catch (StreamNotSupportedException exception) {
            return analyze(request);
        }
    }

    public AiContracts.ChatResponse chat(AiContracts.ChatRequest request) {
        return post("/v1/chat", request, AiContracts.ChatResponse.class);
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

    public AiContracts.CompetencyAssessmentResponse assessCompetency(
            AiContracts.CompetencyAssessmentRequest request
    ) {
        return post(
                "/v1/competency-assessments",
                request,
                AiContracts.CompetencyAssessmentResponse.class
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

    private AiContracts.AnalysisResponse postAnalysisStream(
            AiContracts.AnalysisRequest body,
            Consumer<AiContracts.AnalysisStreamEvent> progressConsumer
    ) {
        return restClient.post()
                .uri("/v1/analyses/stream")
                .contentType(MediaType.APPLICATION_JSON)
                .accept(MediaType.parseMediaType("application/x-ndjson"))
                .header("X-JOBISS-AI-SECRET", properties.ai().sharedSecret())
                .body(body)
                .exchange((request, response) -> {
                    if (response.getStatusCode().value() == 404
                            || response.getStatusCode().value() == 405) {
                        throw new StreamNotSupportedException();
                    }
                    if (response.getStatusCode().isError()) {
                        handleError(
                                response.getStatusCode(),
                                response.getBody().readAllBytes()
                        );
                    }

                    AiContracts.AnalysisResponse result = null;
                    try (var reader = new BufferedReader(new InputStreamReader(
                            response.getBody(),
                            StandardCharsets.UTF_8
                    ))) {
                        String line;
                        while ((line = reader.readLine()) != null) {
                            if (line.isBlank()) {
                                continue;
                            }
                            AiContracts.AnalysisStreamEvent event;
                            try {
                                event = objectMapper.readValue(
                                        line,
                                        AiContracts.AnalysisStreamEvent.class
                                );
                            } catch (RuntimeException exception) {
                                throw new AiServiceException(
                                        "INVALID_AI_RESPONSE",
                                        "AI 진행 이벤트를 해석하지 못했습니다.",
                                        exception
                                );
                            }
                            progressConsumer.accept(event);
                            if ("ERROR".equals(event.type())) {
                                throw new AiServiceException(
                                        event.errorCode() == null
                                                ? "AI_SERVICE_ERROR"
                                                : event.errorCode(),
                                        event.errorMessage() == null
                                                ? "AI 분석 실행이 중단되었습니다."
                                                : event.errorMessage()
                                );
                            }
                            if ("RESULT".equals(event.type()) && event.result() != null) {
                                result = event.result();
                            }
                        }
                    }
                    if (result == null) {
                        throw new AiServiceException(
                                "EMPTY_AI_RESPONSE",
                                "AI 분석 스트림이 최종 결과 없이 종료되었습니다."
                        );
                    }
                    return result;
                });
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

    private static final class StreamNotSupportedException extends RuntimeException {
    }
}
