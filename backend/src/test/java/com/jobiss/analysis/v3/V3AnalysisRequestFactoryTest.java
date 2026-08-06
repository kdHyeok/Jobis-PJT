package com.jobiss.analysis.v3;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

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
}
