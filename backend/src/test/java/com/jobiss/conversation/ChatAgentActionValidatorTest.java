package com.jobiss.conversation;

import com.jobiss.common.ApiException;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class ChatAgentActionValidatorTest {

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    void acceptsOnlyTheStoredPostingAnalysisProposal() {
        JsonNode action = objectMapper.readTree("""
                {
                  "actionId": "analyze-posting-abcd1234",
                  "actionType": "ANALYZE_POSTING",
                  "requiresConsent": true,
                  "payload": {
                    "sourceType": "TEXT",
                    "sourceUrl": null,
                    "rawText": "Java와 Spring Boot 백엔드 개발자를 모집합니다.",
                    "reviewText": "# 채용 공고 핵심 정보\\n## 필수 요건\\n- Java와 Spring Boot 경험"
                  }
                }
                """);

        ChatAgentActionValidator.PostingAnalysisAction result =
                ChatAgentActionValidator.requirePostingAnalysis(
                        action,
                        "analyze-posting-abcd1234"
                );

        assertThat(result.sourceType()).isEqualTo("TEXT");
        assertThat(result.sourceUrl()).isNull();
        assertThat(result.rawText()).contains("Spring Boot");
        assertThat(result.reviewText()).contains("필수 요건");
    }

    @Test
    void rejectsAChangedActionId() {
        JsonNode action = validAction();

        assertThatThrownBy(() ->
                ChatAgentActionValidator.requirePostingAnalysis(action, "different-action")
        ).isInstanceOfSatisfying(ApiException.class, exception ->
                assertThat(exception.code()).isEqualTo("INVALID_AGENT_ACTION")
        );
    }

    @Test
    void rejectsAnUnconfirmedOrMalformedProposal() {
        JsonNode action = validAction();
        ((tools.jackson.databind.node.ObjectNode) action).put("requiresConsent", false);

        assertThatThrownBy(() ->
                ChatAgentActionValidator.requirePostingAnalysis(
                        action,
                        "analyze-posting-abcd1234"
                )
        ).isInstanceOfSatisfying(ApiException.class, exception -> {
            assertThat(exception.code()).isEqualTo("INVALID_AGENT_ACTION");
            assertThat(exception.getMessage()).contains("사용자 확인");
        });
    }

    @Test
    void acceptsAnExplicitlyRequestedAutomaticAnalysis() {
        JsonNode action = objectMapper.readTree("""
                {
                  "actionId": "analyze-posting-explicit123",
                  "actionType": "ANALYZE_POSTING",
                  "requiresConsent": false,
                  "payload": {
                    "sourceType": "TEXT",
                    "sourceUrl": null,
                    "rawText": "Java와 Spring Boot 백엔드 개발자를 모집합니다.",
                    "reviewText": "# 채용 공고 핵심 정보\\n## 필수 요건\\n- Java와 Spring Boot 경험",
                    "userInitiated": true
                  }
                }
                """);

        ChatAgentActionValidator.ValidatedAction result =
                ChatAgentActionValidator.require(
                        action,
                        "analyze-posting-explicit123"
                );

        assertThat(result.actionType()).isEqualTo("ANALYZE_POSTING");
        assertThat(result.postingAnalysis().rawText()).contains("Spring Boot");
    }

    private JsonNode validAction() {
        return objectMapper.readTree("""
                {
                  "actionId": "analyze-posting-abcd1234",
                  "actionType": "ANALYZE_POSTING",
                  "requiresConsent": true,
                  "payload": {
                    "sourceType": "TEXT",
                    "sourceUrl": null,
                    "rawText": "Java와 Spring Boot 백엔드 개발자를 모집합니다.",
                    "reviewText": "# 채용 공고 핵심 정보\\n## 필수 요건\\n- Java와 Spring Boot 경험"
                  }
                }
                """);
    }
}
