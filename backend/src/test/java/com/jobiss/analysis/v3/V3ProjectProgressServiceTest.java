package com.jobiss.analysis.v3;

import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import static org.mockito.Mockito.mock;

import static org.assertj.core.api.Assertions.assertThat;

class V3ProjectProgressServiceTest {

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final V3ProjectProgressService service = new V3ProjectProgressService(
            objectMapper,
            mock(V3ProjectTaskProgressService.class)
    );

    @Test
    void removesBackendCareerNodeIdsFromAiContractSnapshotWithoutLosingProgress() {
        JsonNode original = objectMapper.readTree("""
                {
                  "roadmapVersion": 3,
                  "nodes": [
                    {
                      "nodeId": "project-estgames",
                      "nodeKind": "TARGET_PROJECT",
                      "targetRef": "project:11111111-1111-1111-1111-111111111111",
                      "progressState": "EVIDENCED",
                      "careerNodeId": "22222222-2222-2222-2222-222222222222"
                    }
                  ],
                  "relations": []
                }
                """);

        JsonNode contractSnapshot = service.withoutInternalLinkage(original);

        assertThat(contractSnapshot.path("nodes").get(0).has("careerNodeId")).isFalse();
        assertThat(contractSnapshot.path("nodes").get(0).path("progressState").stringValue())
                .isEqualTo("EVIDENCED");
        assertThat(contractSnapshot.path("nodes").get(0).path("targetRef").stringValue())
                .isEqualTo("project:11111111-1111-1111-1111-111111111111");
        assertThat(original.path("nodes").get(0).has("careerNodeId")).isTrue();
    }
}
