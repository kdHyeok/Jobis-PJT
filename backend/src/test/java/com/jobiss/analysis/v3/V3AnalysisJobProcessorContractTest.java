package com.jobiss.analysis.v3;

import com.jobiss.analysis.AiServiceException;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class V3AnalysisJobProcessorContractTest {

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    void rejectsCapabilityOnlyShellAsCompletedRoadmap() {
        JsonNode proposal = objectMapper.readTree("""
                {"operations":[{
                  "operationId":"op-java",
                  "action":"CREATE_NODE",
                  "nodeKind":"CAPABILITY"
                }]}
                """);

        assertThatThrownBy(() ->
                V3AnalysisJobProcessor.requireActionableRoadmapProposal(
                        proposal,
                        objectMapper.readTree("{\"nodes\":[]}")
                )
        ).isInstanceOfSatisfying(AiServiceException.class, exception -> {
            assertThat(exception.code()).isEqualTo("INVALID_AI_RESPONSE");
            assertThat(exception.getMessage()).contains("목표 프로젝트");
        });
    }

    @Test
    void acceptsDraftWithProjectTasksAndOpportunity() {
        JsonNode proposal = objectMapper.readTree("""
                {"operations":[
                  {
                    "operationId":"op-project",
                    "action":"CREATE_TARGET_PROJECT",
                    "nodeKind":"TARGET_PROJECT",
                    "projectSpec":{"tasks":[{"taskKey":"task.one"}]}
                  },
                  {
                    "operationId":"op-opportunity",
                    "action":"ADD_OPPORTUNITY",
                    "nodeKind":"OPPORTUNITY",
                    "opportunitySpec":{"opportunityId":"opportunity-one"}
                  }
                ]}
                """);

        assertThatCode(() ->
                V3AnalysisJobProcessor.requireActionableRoadmapProposal(
                        proposal,
                        objectMapper.readTree("{\"nodes\":[]}")
                )
        ).doesNotThrowAnyException();
    }

    @Test
    void projectsUnifiedRoleAndExperienceIntoLegacyRecommendationContract() {
        JsonNode role = objectMapper.readTree("""
                {"canonicalRoleId":"role.data_science","specialization":"DATA_SCIENCE"}
                """);
        JsonNode experience = objectMapper.readTree("""
                {"kind":"NEW_GRADUATE_OR_EXPERIENCED","experiencedMinMonths":24}
                """);

        assertThat(V3AnalysisJobProcessor.legacyTrack(role)).isEqualTo("DATA");
        assertThat(V3AnalysisJobProcessor.legacyExperienceType(
                experience.path("kind").stringValue("")
        )).isEqualTo("PREFERRED");
        assertThat(V3AnalysisJobProcessor.minimumExperienceMonths(experience)).isEqualTo(24);
    }

    @Test
    void doesNotInventExperienceMonthsWhenUnifiedPostingHasNoNumber() {
        JsonNode experience = objectMapper.readTree("""
                {"kind":"NEW_GRADUATE_OR_EXPERIENCED","experiencedMinMonths":null}
                """);

        assertThat(V3AnalysisJobProcessor.minimumExperienceMonths(experience)).isZero();
    }
}
