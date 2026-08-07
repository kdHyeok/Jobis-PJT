package com.jobiss.analysis.v3;

import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.stream.StreamSupport;

import static org.assertj.core.api.Assertions.assertThat;

class D048ProjectCenteredJourneyTest {

    private final ObjectMapper objectMapper = new ObjectMapper();
    private final V3RoadmapCompiler compiler = new V3RoadmapCompiler(objectMapper);

    @Test
    void entryAndExperiencedTargetsBecomeOneCareerGraph() throws Exception {
        JsonNode fixture = objectMapper.readTree(Files.readString(Path.of(
                "..", "contract-fixtures", "scenarios",
                "d048-estgames-naver-career-journey.json"
        ).normalize()));

        JsonNode entry = compiler.compile(read("""
                {"roadmapVersion":0,"nodes":[],"relations":[]}
                """), read("""
                {
                  "proposalId":"d048-entry","status":"DRAFT","basedOnRoadmapVersion":0,
                  "operations":[
                    {"operationId":"java","action":"CREATE_NODE","nodeKind":"CAPABILITY",
                     "canonicalKey":"java.classes-objects","title":"Java 객체 모델링",
                     "sectionKey":"section.web_backend","initialProgressState":"NOT_STARTED",
                     "scopeDefinition":"객체로 상태와 책임을 모델링한다.","reason":"required"},
                    {"operationId":"entry-project","action":"CREATE_TARGET_PROJECT","nodeKind":"TARGET_PROJECT",
                     "targetRef":"project:estgames-backend-entry","title":"게임 퍼블리싱·과금 플랫폼 백엔드 프로젝트",
                     "sectionKey":"section.web_backend","initialProgressState":"NOT_STARTED","reason":"project",
                     "projectSpec":{"objective":"게임 결제 흐름을 구현한다.",
                       "deliverables":["실행 서비스","검증 보고서"],"verificationCriteria":["테스트 통과","실행 재현"],
                       "requiredCapabilityKeys":["java.classes-objects"],"preferredCapabilityKeys":[],
                       "requiredProvisionalCandidateIds":[],"preferredProvisionalCandidateIds":[],
                       "domainContext":"게임 퍼블리싱","tasks":[{
                         "taskKey":"task.entry-core","necessity":"REQUIRED","title":"구매 흐름 구현",
                         "objective":"구매 상태를 구현한다.","acceptanceCriteria":["구매 성공","실패 검증"],
                         "capabilityKeys":["java.classes-objects"],"requirementIds":["req-java"],
                         "dependsOnTaskKeys":[]
                       }]}},
                    {"operationId":"entry-opportunity","action":"ADD_OPPORTUNITY","nodeKind":"OPPORTUNITY",
                     "targetRef":"estgames-backend-entry","title":"이스트게임즈 백엔드 신입",
                     "sectionKey":"section.web_backend","initialProgressState":"NOT_STARTED","reason":"target",
                     "opportunitySpec":{"opportunityId":"estgames-backend-entry","companyName":"이스트게임즈",
                       "positionTitle":"웹 백엔드","roleFamily":"SOFTWARE_ENGINEERING","roleSpecialization":"WEB_BACKEND",
                       "sourceExperienceKind":"NEW_GRADUATE","selectedExperienceTrack":"NEW_GRADUATE",
                       "minimumExperienceMonths":0}}
                  ],
                  "relations":[
                    {"relationId":"java-project","fromOperationId":"java","toOperationId":"entry-project",
                     "relationType":"UNLOCKS_PROJECT","conditions":[],"reason":"required"},
                    {"relationId":"project-entry","fromOperationId":"entry-project","toOperationId":"entry-opportunity",
                     "relationType":"UNLOCKS_OPPORTUNITY","conditions":[],"reason":"ready"}
                  ]
                }
                """));

        JsonNode experiencedProposal = read("""
                {
                  "proposalId":"d048-experienced","status":"DRAFT","basedOnRoadmapVersion":1,
                  "operations":[
                    {"operationId":"java-reuse","action":"REUSE_NODE","nodeKind":"CAPABILITY",
                     "canonicalKey":"java.classes-objects","existingNodeId":"node-6dc0c19908e1c040",
                     "title":"Java 객체 모델링","sectionKey":"section.web_backend",
                     "initialProgressState":"NOT_STARTED","scopeDefinition":"객체로 상태와 책임을 모델링한다.",
                     "reason":"reuse"},
                    {"operationId":"naver-project","action":"CREATE_TARGET_PROJECT","nodeKind":"TARGET_PROJECT",
                     "targetRef":"project:naver-webtoon-backend-experienced","title":"글로벌 유료 콘텐츠 백엔드 플랫폼 프로젝트",
                     "sectionKey":"section.web_backend","initialProgressState":"NOT_STARTED","reason":"project",
                     "projectSpec":{"objective":"글로벌 유료 콘텐츠 흐름을 구현한다.",
                       "deliverables":["실행 서비스","성능 보고서"],"verificationCriteria":["테스트 통과","부하 측정"],
                       "requiredCapabilityKeys":["java.classes-objects"],"preferredCapabilityKeys":[],
                       "requiredProvisionalCandidateIds":[],"preferredProvisionalCandidateIds":[],
                       "domainContext":"유료 콘텐츠","tasks":[]}},
                    {"operationId":"experience-gate","action":"CREATE_GATE","nodeKind":"CAREER_GATE",
                     "targetRef":"gate:naver","title":"관련 실무 경력 2~4년","sectionKey":"section.web_backend",
                     "initialProgressState":"NOT_STARTED","reason":"experience",
                     "gateSpec":{"gateType":"EXPERIENCE","requiredMonths":24,"maximumMonths":48,
                       "assessmentStatus":"NOT_MET","evidenceIds":[]}},
                    {"operationId":"naver-opportunity","action":"ADD_OPPORTUNITY","nodeKind":"OPPORTUNITY",
                     "targetRef":"naver-webtoon-backend-experienced","title":"네이버웹툰 백엔드",
                     "sectionKey":"section.web_backend","initialProgressState":"NOT_STARTED","reason":"target",
                     "opportunitySpec":{"opportunityId":"naver-webtoon-backend-experienced","companyName":"네이버웹툰",
                       "positionTitle":"백엔드 서버 개발","roleFamily":"SOFTWARE_ENGINEERING","roleSpecialization":"WEB_BACKEND",
                       "sourceExperienceKind":"RANGE","selectedExperienceTrack":"EXPERIENCED",
                       "minimumExperienceMonths":24,"maximumExperienceMonths":48}}
                  ],
                  "relations":[
                    {"relationId":"java-naver-project","fromOperationId":"java-reuse","toOperationId":"naver-project",
                     "relationType":"UNLOCKS_PROJECT","conditions":[],"reason":"reuse"},
                    {"relationId":"naver-project-opportunity","fromOperationId":"naver-project","toOperationId":"naver-opportunity",
                     "relationType":"UNLOCKS_OPPORTUNITY","conditions":[],"reason":"project"},
                    {"relationId":"gate-naver","fromOperationId":"experience-gate","toOperationId":"naver-opportunity",
                     "relationType":"REQUIRES_GATE","conditions":[],"reason":"experience"}
                  ]
                }
                """);
        String javaNodeId = StreamSupport.stream(entry.path("snapshot").path("nodes").spliterator(), false)
                .filter(node -> "java.classes-objects".equals(node.path("canonicalKey").asText()))
                .findFirst()
                .orElseThrow()
                .path("nodeId")
                .asText();
        ((ObjectNode) experiencedProposal.path("operations").get(0)).put("existingNodeId", javaNodeId);
        JsonNode combined = compiler.compile(entry.path("snapshot"), experiencedProposal);

        JsonNode snapshot = combined.path("snapshot");
        assertThat(count(snapshot, "TARGET_PROJECT")).isEqualTo(2);
        assertThat(count(snapshot, "OPPORTUNITY")).isEqualTo(2);
        assertThat(count(snapshot, "EMPLOYMENT_EVENT")).isEqualTo(1);
        assertThat(count(snapshot, "EXPERIENCE_INTERVAL")).isEqualTo(1);
        assertThat(count(snapshot, "CAPABILITY")).isEqualTo(1);
        assertThat(snapshot.path("relations"))
                .anyMatch(item -> "POTENTIAL_CAREER_ENTRY".equals(item.path("relationType").asText()))
                .anyMatch(item -> "STARTS_EXPERIENCE".equals(item.path("relationType").asText()))
                .anyMatch(item -> "SATISFIES_EXPERIENCE_GATE".equals(item.path("relationType").asText()));
        assertThat(fixture.path("expectedJourneyProjection").path("projectTasksRenderedOnOverview").asBoolean())
                .isFalse();
    }

    private long count(JsonNode snapshot, String kind) {
        return StreamSupport.stream(snapshot.path("nodes").spliterator(), false)
                .filter(node -> kind.equals(node.path("nodeKind").asText()))
                .count();
    }

    private JsonNode read(String value) {
        return objectMapper.readTree(value);
    }
}
