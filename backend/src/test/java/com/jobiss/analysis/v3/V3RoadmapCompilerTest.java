package com.jobiss.analysis.v3;

import com.jobiss.common.ApiException;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class V3RoadmapCompilerTest {

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final V3RoadmapCompiler compiler = new V3RoadmapCompiler(objectMapper);

    @Test
    void preservesProgressAndCreatesExplicitEmploymentAndExperiencePath() {
        JsonNode preview = compiler.compile(read("""
                {
                  "roadmapVersion":3,
                  "nodes":[
                    {"nodeId":"node-java","nodeKind":"CAPABILITY","title":"Java",
                     "canonicalKey":"lang.java","sectionKey":"section.web_backend",
                     "progressState":"VERIFIED","scopeDefinition":"Java language scope","level":2,"displayRank":0},
                    {"nodeId":"node-entry","nodeKind":"OPPORTUNITY","title":"Entry Backend",
                     "targetRef":"opportunity-entry","sectionKey":"section.web_backend",
                     "progressState":"NOT_STARTED","displayRank":1,
                     "opportunitySpec":{"opportunityId":"opportunity-entry","companyName":"Entry",
                     "positionTitle":"Backend","roleFamily":"SOFTWARE_ENGINEERING",
                     "roleSpecialization":"WEB_BACKEND","sourceExperienceKind":"NEW_GRADUATE",
                     "selectedExperienceTrack":"NEW_GRADUATE","minimumExperienceMonths":0}}
                  ],
                  "relations":[]
                }
                """), read("""
                {
                  "proposalId":"proposal-experienced","status":"DRAFT","basedOnRoadmapVersion":3,
                  "operations":[
                    {"operationId":"op-java","action":"REUSE_NODE","nodeKind":"CAPABILITY",
                     "canonicalKey":"lang.java","technologyKey":"lang.java","graphNodeVersion":2,
                     "verificationMethods":["IMPLEMENT","EXPLAIN"],
                     "existingNodeId":"node-java","title":"Java",
                     "sectionKey":"section.web_backend","scopeDefinition":"Java language scope","level":2,
                     "initialProgressState":"NOT_STARTED","reason":"reuse"},
                    {"operationId":"op-gate","action":"CREATE_GATE","nodeKind":"CAREER_GATE",
                     "targetRef":"gate:experienced","title":"관련 경력 2년","sectionKey":"section.web_backend",
                     "initialProgressState":"NOT_STARTED","reason":"experience",
                     "gateSpec":{"gateType":"EXPERIENCE","requiredMonths":24,"maximumMonths":48,"assessmentStatus":"NOT_MET","evidenceIds":[]}},
                    {"operationId":"op-company","action":"ADD_OPPORTUNITY","nodeKind":"OPPORTUNITY",
                     "targetRef":"opportunity-experienced","title":"Experienced Backend",
                     "sectionKey":"section.web_backend","initialProgressState":"NOT_STARTED","reason":"target",
                     "opportunitySpec":{"opportunityId":"opportunity-experienced","companyName":"Experienced",
                     "positionTitle":"Backend","roleFamily":"SOFTWARE_ENGINEERING",
                     "roleSpecialization":"WEB_BACKEND","sourceExperienceKind":"EXPERIENCE_REQUIRED",
                     "selectedExperienceTrack":"EXPERIENCED","minimumExperienceMonths":24,
                     "maximumExperienceMonths":48}}
                  ],
                  "relations":[
                    {"relationId":"rel-java-company","fromOperationId":"op-java","toOperationId":"op-company",
                     "relationType":"UNLOCKS_OPPORTUNITY","conditions":[],"reason":"skill"},
                    {"relationId":"rel-gate-company","fromOperationId":"op-gate","toOperationId":"op-company",
                     "relationType":"REQUIRES_GATE","conditions":[],"reason":"experience"}
                  ]
                }
                """));

        assertThat(preview.path("proposedRoadmapVersion").longValue()).isEqualTo(4);
        assertThat(preview.path("snapshot").path("nodes"))
                .anyMatch(node -> "node-java".equals(node.path("nodeId").stringValue())
                        && "VERIFIED".equals(node.path("progressState").stringValue())
                        && "lang.java".equals(node.path("technologyKey").stringValue())
                        && node.path("graphNodeVersion").intValue() == 2
                        && node.path("verificationMethods").size() == 2);
        JsonNode gate = findNode(preview, "CAREER_GATE");
        JsonNode employment = findNode(preview, "EMPLOYMENT_EVENT");
        JsonNode interval = findNode(preview, "EXPERIENCE_INTERVAL");
        JsonNode experienced = findTarget(preview, "opportunity-experienced");
        assertThat(preview.path("snapshot").path("relations"))
                .anyMatch(relation -> "node-entry".equals(relation.path("fromNodeId").stringValue())
                        && employment.path("nodeId").stringValue().equals(relation.path("toNodeId").stringValue())
                        && "POTENTIAL_CAREER_ENTRY".equals(relation.path("relationType").stringValue()))
                .anyMatch(relation -> employment.path("nodeId").stringValue().equals(relation.path("fromNodeId").stringValue())
                        && interval.path("nodeId").stringValue().equals(relation.path("toNodeId").stringValue())
                        && "STARTS_EXPERIENCE".equals(relation.path("relationType").stringValue()))
                .anyMatch(relation -> interval.path("nodeId").stringValue().equals(relation.path("fromNodeId").stringValue())
                        && gate.path("nodeId").stringValue().equals(relation.path("toNodeId").stringValue())
                        && "SATISFIES_EXPERIENCE_GATE".equals(relation.path("relationType").stringValue()))
                .noneMatch(relation -> "node-entry".equals(relation.path("fromNodeId").stringValue())
                        && gate.path("nodeId").stringValue().equals(relation.path("toNodeId").stringValue()));
        assertThat(interval.path("experienceIntervalSpec").path("minimumMonths").intValue())
                .isEqualTo(24);
        assertThat(interval.path("experienceIntervalSpec").path("maximumMonths").intValue())
                .isEqualTo(48);
        assertThat(employment.path("displayRank").intValue())
                .isLessThan(interval.path("displayRank").intValue());
        assertThat(interval.path("displayRank").intValue())
                .isLessThan(gate.path("displayRank").intValue());
        assertThat(gate.path("displayRank").intValue())
                .isLessThan(experienced.path("displayRank").intValue());
    }

    @Test
    void rejectsStaleProposal() {
        assertThatThrownBy(() -> compiler.compile(
                read("{\"roadmapVersion\":3,\"nodes\":[],\"relations\":[]}"),
                read("{\"proposalId\":\"p\",\"status\":\"DRAFT\",\"basedOnRoadmapVersion\":2,\"operations\":[],\"relations\":[]}")
        )).isInstanceOf(ApiException.class)
                .extracting(error -> ((ApiException) error).code())
                .isEqualTo("V3_ROADMAP_STALE_PROPOSAL");
    }

    @Test
    void targetRemovalKeepsVerifiedCapabilityAndReportsRemovedNodes() {
        JsonNode preview = compiler.compile(read("""
                {
                  "roadmapVersion":4,
                  "nodes":[
                    {"nodeId":"node-java","nodeKind":"CAPABILITY","title":"Java",
                     "canonicalKey":"lang.java","sectionKey":"section.web_backend",
                     "progressState":"VERIFIED","scopeDefinition":"Java language scope","displayRank":0},
                    {"nodeId":"node-project","nodeKind":"TARGET_PROJECT","title":"Entry project",
                     "targetRef":"project:opportunity:posting-1","sectionKey":"section.web_backend",
                     "progressState":"NOT_STARTED","displayRank":1,"projectSpec":{"objective":"Build",
                     "deliverables":["a","b"],"verificationCriteria":["a","b"],
                     "requiredCapabilityKeys":["lang.java"],"preferredCapabilityKeys":[],
                     "requiredProvisionalCandidateIds":[],"preferredProvisionalCandidateIds":[],
                     "domainContext":"backend"}},
                    {"nodeId":"node-entry","nodeKind":"OPPORTUNITY","title":"Entry Backend",
                     "targetRef":"opportunity:posting-1","sectionKey":"section.web_backend",
                     "progressState":"NOT_STARTED","displayRank":2,
                     "opportunitySpec":{"opportunityId":"opportunity:posting-1","companyName":"Entry",
                     "positionTitle":"Backend","roleFamily":"SOFTWARE_ENGINEERING",
                     "roleSpecialization":"WEB_BACKEND","sourceExperienceKind":"NEW_GRADUATE",
                     "selectedExperienceTrack":"NEW_GRADUATE","minimumExperienceMonths":0}}
                  ],
                  "relations":[
                    {"relationId":"edge-java-project","fromNodeId":"node-java","toNodeId":"node-project",
                     "relationType":"UNLOCKS_PROJECT","conditions":[],"reason":"required"},
                    {"relationId":"edge-project-entry","fromNodeId":"node-project","toNodeId":"node-entry",
                     "relationType":"UNLOCKS_OPPORTUNITY","conditions":[],"reason":"target"}
                  ]
                }
                """), read("""
                {"proposalId":"remove-entry","status":"DRAFT","basedOnRoadmapVersion":4,
                 "removeTargetRefs":["opportunity:posting-1"],"operations":[],"relations":[]}
                """));

        assertThat(preview.path("snapshot").path("nodes"))
                .anyMatch(node -> "node-java".equals(node.path("nodeId").stringValue()))
                .noneMatch(node -> "node-project".equals(node.path("nodeId").stringValue()))
                .noneMatch(node -> "node-entry".equals(node.path("nodeId").stringValue()));
        assertThat(preview.path("removedNodeIds"))
                .anyMatch(node -> "node-project".equals(node.stringValue()))
                .anyMatch(node -> "node-entry".equals(node.stringValue()));
        assertThat(preview.path("removedRelationIds")).hasSize(2);
    }

    private JsonNode findNode(JsonNode preview, String kind) {
        for (JsonNode node : preview.path("snapshot").path("nodes")) {
            if (kind.equals(node.path("nodeKind").stringValue())) {
                return node;
            }
        }
        throw new AssertionError("node not found: " + kind);
    }

    private JsonNode findTarget(JsonNode preview, String targetRef) {
        for (JsonNode node : preview.path("snapshot").path("nodes")) {
            if (targetRef.equals(node.path("targetRef").stringValue(""))) {
                return node;
            }
        }
        throw new AssertionError("target not found: " + targetRef);
    }

    private JsonNode read(String json) {
        return objectMapper.readTree(json);
    }
}
