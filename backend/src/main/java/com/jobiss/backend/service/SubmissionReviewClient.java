package com.jobiss.backend.service;

import com.jobiss.backend.exception.ApiException;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;
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
 * 산출물 제출 → AI(웹 브릿지 POST /submission-review) 요건별 피드백.
 *
 * 웹은 판정하지 않는다 — 제출 링크·메모와 그 분석의 공고 요건 목록을 넘기고 결과를 그대로 저장한다.
 * 고정 피드백 JSON(mock/cloudwave-feedback.json)을 읽던 자리를 대신한다.
 */
@Component
public class SubmissionReviewClient {

    private final ObjectMapper om;
    private final String agentHttpUrl;
    // HTTP/1.1 고정 — EvidenceImportService 와 같은 이유(업그레이드 헤더 오인 방지).
    private final HttpClient httpClient = HttpClient.newBuilder()
            .version(HttpClient.Version.HTTP_1_1)
            .connectTimeout(Duration.ofSeconds(5))
            .build();

    public SubmissionReviewClient(ObjectMapper om,
                                  @Value("${jobiss.agent.http-url}") String agentHttpUrl) {
        this.om = om;
        this.agentHttpUrl = agentHttpUrl;
    }

    /** 제출물 리뷰 JSON 문자열({summary, checks}) — 그대로 feedback_reports.report 에 저장된다. */
    public String review(String githubUrl, String deployUrl, String note, List<String> requirements) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("githubUrl", githubUrl == null ? "" : githubUrl);
        body.put("deployUrl", deployUrl == null ? "" : deployUrl);
        body.put("note", note == null ? "" : note);
        body.put("requirements", requirements == null ? List.of() : requirements);

        try {
            HttpRequest request = HttpRequest.newBuilder()
                    .uri(URI.create(agentHttpUrl + "/submission-review"))
                    .timeout(Duration.ofSeconds(120))
                    .header("Content-Type", "application/json; charset=utf-8")
                    .POST(HttpRequest.BodyPublishers.ofString(om.writeValueAsString(body), StandardCharsets.UTF_8))
                    .build();

            HttpResponse<String> response = httpClient.send(request,
                    HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() / 100 != 2) {
                throw new ApiException(HttpStatus.BAD_GATEWAY, "AI_REVIEW_FAILED",
                        "제출물 검토 실패(" + response.statusCode() + ")");
            }
            return response.body();
        } catch (ApiException e) {
            throw e;
        } catch (Exception e) {
            throw new ApiException(HttpStatus.BAD_GATEWAY, "AI_UNREACHABLE",
                    "AI 서버에 연결하지 못했어요. (웹 브릿지가 켜져 있나요?)");
        }
    }

    /**
     * 저장된 분석 결과에서 대조할 공고 요건 문구를 뽑는다.
     * 결과 JSON 의 gaps[].requirement 가 요건 목록이다(충족·미충족 모두 담겨 있다).
     */
    public List<String> requirementsOf(String resultJson) {
        List<String> out = new ArrayList<>();
        if (resultJson == null || resultJson.isBlank()) {
            return out;
        }
        try {
            JsonNode gaps = om.readTree(resultJson).path("gaps");
            for (JsonNode gap : gaps) {
                String text = gap.path("requirement").asString("").trim();
                if (!text.isEmpty()) {
                    out.add(text);
                }
            }
        } catch (Exception ignore) {
            // 결과 파싱 실패해도 제출은 받는다 — 요건 없이 링크만으로 검토한다.
        }
        return out;
    }
}
