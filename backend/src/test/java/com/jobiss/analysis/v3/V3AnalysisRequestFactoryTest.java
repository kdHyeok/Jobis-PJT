package com.jobiss.analysis.v3;

import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class V3AnalysisRequestFactoryTest {

    @Test
    void mapsEvidenceQuestionChoicesToRequirementSelfReports() {
        assertThat(V3AnalysisRequestFactory.requirementClaimState(
                "claim-present",
                "PROVIDED"
        )).isEqualTo("CLAIMED");
        assertThat(V3AnalysisRequestFactory.requirementClaimState(
                "claim-absent",
                "PROVIDED"
        )).isEqualTo("NOT_CLAIMED");
        assertThat(V3AnalysisRequestFactory.requirementClaimState(
                "claim-unknown",
                "PROVIDED"
        )).isEqualTo("UNKNOWN");
    }

    @Test
    void confirmedAbsenceWinsOverChoiceText() {
        assertThat(V3AnalysisRequestFactory.requirementClaimState(
                "claim-present",
                "CONFIRMED_ABSENT"
        )).isEqualTo("NOT_CLAIMED");
    }

    @Test
    void chatAndPostingsPageRequireTheSameExplicitReviewConfirmation() {
        assertThat(V3AnalysisRequestFactory.requiresPostingConfirmation("CHAT", null))
                .isTrue();
        assertThat(V3AnalysisRequestFactory.requiresPostingConfirmation("POSTINGS_PAGE", null))
                .isTrue();
        assertThat(V3AnalysisRequestFactory.requiresPostingConfirmation(
                "CHAT",
                "posting-review-confirmed"
        )).isFalse();
        assertThat(V3AnalysisRequestFactory.requiresPostingConfirmation(
                "POSTINGS_PAGE",
                "posting-review-confirmed"
        )).isFalse();
        assertThatThrownBy(() ->
                V3AnalysisRequestFactory.requiresPostingConfirmation("UNKNOWN", null)
        ).isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void skipsEvidenceQuestionsOnlyAfterTheThirdQuestion() {
        assertThat(V3AnalysisRequestFactory.skipRemainingEvidenceQuestions(2)).isFalse();
        assertThat(V3AnalysisRequestFactory.skipRemainingEvidenceQuestions(3)).isTrue();
    }

    @Test
    void confirmedSkillFragmentBecomesExactBroadCompetencyEvidenceOnly() {
        ObjectMapper objectMapper = new ObjectMapper();
        ArrayNode competencies = objectMapper.createArrayNode();
        ObjectNode sql = objectMapper.createObjectNode();
        sql.put("competencyId", "skill.sql");
        sql.put("displayName", "SQL");
        sql.put("scopeDefinition", "SQL broad competency");
        sql.put("claimState", "NOT_CLAIMED");
        sql.put("evidenceState", "NO_EVIDENCE");
        sql.put("verificationState", "NOT_VERIFIED");
        sql.put("verifiedLevel", 0);
        sql.putArray("evidenceRefs");
        sql.put("confidence", 0.5);
        competencies.add(sql);
        ArrayNode evidenceItems = objectMapper.createArrayNode();
        ArrayNode formalFacts = objectMapper.createArrayNode();
        UUID fragmentId = UUID.randomUUID();

        V3AnalysisRequestFactory.applyConfirmedCareerFragments(
                objectMapper,
                competencies,
                evidenceItems,
                formalFacts,
                List.of(new V3AnalysisRequestFactory.CareerFragmentEvidence(
                        fragmentId,
                        "SKILL",
                        "SQL",
                        "CRUD queries used in a project",
                        "skill.sql"
                ))
        );

        assertThat(competencies).hasSize(1);
        assertThat(sql.path("claimState").stringValue()).isEqualTo("CLAIMED");
        assertThat(sql.path("evidenceState").stringValue()).isEqualTo("EVIDENCED");
        assertThat(sql.path("verificationState").stringValue())
                .isEqualTo("NOT_VERIFIED");
        assertThat(sql.path("evidenceRefs").get(0).stringValue())
                .isEqualTo(fragmentId.toString());
        assertThat(evidenceItems).hasSize(1);
        assertThat(formalFacts).isEmpty();
        assertThat(competencies)
                .noneMatch(item -> "sql.crud".equals(
                        item.path("competencyId").stringValue("")
                ));
    }

    @Test
    void confirmedStructuredFragmentsBecomeFormalFactsWithEvidenceRefs() {
        ObjectMapper objectMapper = new ObjectMapper();
        ArrayNode competencies = objectMapper.createArrayNode();
        ArrayNode evidenceItems = objectMapper.createArrayNode();
        ArrayNode formalFacts = objectMapper.createArrayNode();
        UUID projectId = UUID.randomUUID();
        UUID experienceId = UUID.randomUUID();
        UUID educationId = UUID.randomUUID();
        UUID credentialId = UUID.randomUUID();
        UUID linkId = UUID.randomUUID();

        V3AnalysisRequestFactory.applyConfirmedCareerFragments(
                objectMapper,
                competencies,
                evidenceItems,
                formalFacts,
                List.of(
                        fragment(projectId, "PROJECT", "Project"),
                        fragment(experienceId, "EXPERIENCE", "Backend engineer"),
                        fragment(educationId, "EDUCATION", "Computer science"),
                        fragment(credentialId, "CREDENTIAL", "Certificate"),
                        fragment(linkId, "LINK", "Reference link")
                )
        );

        assertThat(evidenceItems).hasSize(5);
        assertThat(formalFacts).hasSize(4);
        assertThat(formalFacts)
                .extracting(item -> item.path("kind").stringValue())
                .containsExactly(
                        "PORTFOLIO",
                        "ROLE_EXPERIENCE",
                        "EDUCATION",
                        "CERTIFICATE"
                );
        assertThat(formalFacts.get(0).path("evidenceRefs").get(0).stringValue())
                .isEqualTo(projectId.toString());
        assertThat(formalFacts.get(0).path("verificationState").stringValue())
                .isEqualTo("NOT_VERIFIED");
        assertThat(formalFacts.get(2).path("label").stringValue())
                .isEqualTo("Computer science · Computer science description");
        assertThat(formalFacts.get(3).path("label").stringValue())
                .isEqualTo("Certificate");
    }

    private static V3AnalysisRequestFactory.CareerFragmentEvidence fragment(
            UUID id,
            String kind,
            String title
    ) {
        return new V3AnalysisRequestFactory.CareerFragmentEvidence(
                id,
                kind,
                title,
                title + " description",
                null
        );
    }
}
