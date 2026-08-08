package com.jobiss.conversation;

import com.jobiss.common.ApiException;
import org.springframework.http.HttpStatus;
import tools.jackson.databind.JsonNode;

import java.net.URI;
import java.util.Set;
import java.util.regex.Pattern;

final class ChatAgentActionValidator {

    private static final Pattern ACTION_ID = Pattern.compile(
            "^[a-z0-9][a-z0-9._-]{1,79}$"
    );

    private ChatAgentActionValidator() {
    }

    private static final Set<String> SUPPORTED_TYPES = Set.of(
            "NAVIGATE",
            "ANALYZE_POSTING",
            "COMPARE",
            "SAVE_DRAFT",
            "START_INTERVIEW",
            "FIND_ALTERNATIVES"
    );

    static ValidatedAction require(JsonNode action, String expectedActionId) {
        if (action == null
                || !expectedActionId.equals(action.path("actionId").stringValue(""))
                || !ACTION_ID.matcher(expectedActionId).matches()) {
            throw invalid("실행할 AI 제안을 찾을 수 없습니다.");
        }
        String actionType = action.path("actionType").stringValue("");
        if (!SUPPORTED_TYPES.contains(actionType)) {
            throw invalid("지원하지 않는 AI 제안입니다.");
        }
        JsonNode payload = action.path("payload");
        boolean requiresConsent = action.path("requiresConsent").booleanValue();
        JsonNode userInitiatedNode = payload.path("userInitiated");
        boolean userInitiated = userInitiatedNode.isBoolean()
                && userInitiatedNode.booleanValue();
        if (!requiresConsent
                && !userInitiated
                && !Set.of("NAVIGATE", "COMPARE", "FIND_ALTERNATIVES").contains(actionType)) {
            throw invalid("사용자 확인 없이 실행하려면 사용자가 직접 요청한 작업이어야 합니다.");
        }

        PostingAnalysisAction postingAnalysis = null;
        if ("ANALYZE_POSTING".equals(actionType)) {
            postingAnalysis = requirePostingAnalysisPayload(payload);
        } else if ("SAVE_DRAFT".equals(actionType)
                && !"COVER_LETTER_DRAFT".equals(payload.path("productType").stringValue(""))) {
            throw invalid("저장할 자소서 초안이 올바르지 않습니다.");
        } else if ("START_INTERVIEW".equals(actionType)
                && !"INTERVIEW_SET".equals(payload.path("productType").stringValue(""))) {
            throw invalid("시작할 면접 질문 세트가 올바르지 않습니다.");
        }
        return new ValidatedAction(actionType, payload, postingAnalysis);
    }

    static PostingAnalysisAction requirePostingAnalysis(
            JsonNode action,
            String expectedActionId
    ) {
        ValidatedAction validated = require(action, expectedActionId);
        if (!"ANALYZE_POSTING".equals(validated.actionType())) {
            throw invalid("공고 분석 제안이 아닙니다.");
        }
        return validated.postingAnalysis();
    }

    private static PostingAnalysisAction requirePostingAnalysisPayload(JsonNode payload) {
        String sourceType = payload.path("sourceType").stringValue("").trim();
        String rawText = payload.path("rawText").stringValue("").trim();
        String reviewText = payload.path("reviewText").stringValue("").trim();
        String sourceUrl = payload.path("sourceUrl").isNull()
                ? null
                : payload.path("sourceUrl").stringValue("").trim();
        if (!("TEXT".equals(sourceType) || "URL".equals(sourceType))) {
            throw invalid("공고 출처 형식이 올바르지 않습니다.");
        }
        if (rawText.length() < 20 || rawText.length() > 100_000) {
            throw invalid("공고 본문은 20자 이상 100,000자 이하이어야 합니다.");
        }
        if (reviewText.length() < 20 || reviewText.length() > 20_000) {
            throw invalid("정리한 공고 내용은 20자 이상 20,000자 이하이어야 합니다.");
        }
        if (sourceUrl != null && sourceUrl.length() > 2_000) {
            throw invalid("공고 URL이 너무 깁니다.");
        }
        if ("URL".equals(sourceType)) {
            validateHttpUrl(sourceUrl);
        } else {
            sourceUrl = null;
        }
        return new PostingAnalysisAction(sourceType, sourceUrl, rawText, reviewText);
    }

    private static void validateHttpUrl(String sourceUrl) {
        try {
            URI uri = URI.create(sourceUrl == null ? "" : sourceUrl);
            if (!("http".equalsIgnoreCase(uri.getScheme())
                    || "https".equalsIgnoreCase(uri.getScheme()))) {
                throw invalid("공고 URL은 HTTP 또는 HTTPS 주소여야 합니다.");
            }
        } catch (IllegalArgumentException exception) {
            throw invalid("공고 URL 형식이 올바르지 않습니다.");
        }
    }

    private static ApiException invalid(String message) {
        return new ApiException(
                HttpStatus.BAD_REQUEST,
                "INVALID_AGENT_ACTION",
                message
        );
    }

    record PostingAnalysisAction(
            String sourceType,
            String sourceUrl,
            String rawText,
            String reviewText
    ) {
    }

    record ValidatedAction(
            String actionType,
            JsonNode payload,
            PostingAnalysisAction postingAnalysis
    ) {
    }
}
