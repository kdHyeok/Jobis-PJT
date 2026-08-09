package com.jobiss.analysis.v3;

import com.jobiss.db.RlsTransactionExecutor;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

class V3ProjectTaskProgressServiceTest {

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final V3ProjectTaskProgressService service = new V3ProjectTaskProgressService(
            mock(RlsTransactionExecutor.class),
            objectMapper
    );

    @Test
    void runtimeProgressDoesNotChangeTheProjectTaskDefinitionRevision() {
        JsonNode definition = objectMapper.readTree("""
                {
                  "taskKey": "task.api",
                  "necessity": "REQUIRED",
                  "title": "API 구현",
                  "objective": "요청을 처리한다.",
                  "acceptanceCriteria": ["정상 응답", "오류 응답"],
                  "capabilityKeys": ["spring.mvc-rest-controller"],
                  "requirementIds": ["requirement.api"],
                  "dependsOnTaskKeys": []
                }
                """);
        JsonNode projected = definition.deepCopy();
        ((tools.jackson.databind.node.ObjectNode) projected).put("progressState", "CLAIMED");
        ((tools.jackson.databind.node.ObjectNode) projected).put("evidenceCount", 3);

        assertThat(service.definitionRevision(projected))
                .isEqualTo(service.definitionRevision(definition));
    }

    @Test
    void actualTaskDefinitionChangesStillChangeTheRevision() {
        JsonNode original = objectMapper.readTree("""
                {"taskKey":"task.api","title":"API 구현","objective":"요청을 처리한다."}
                """);
        JsonNode changed = objectMapper.readTree("""
                {"taskKey":"task.api","title":"API 구현","objective":"요청과 오류를 처리한다."}
                """);

        assertThat(service.definitionRevision(changed))
                .isNotEqualTo(service.definitionRevision(original));
    }
}
