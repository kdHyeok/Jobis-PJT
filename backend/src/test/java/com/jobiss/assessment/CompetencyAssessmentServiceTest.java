package com.jobiss.assessment;

import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class CompetencyAssessmentServiceTest {

    @Test
    void startsWithFirstMissingCoreDimension() {
        assertThat(CompetencyAssessmentService.firstQuestionKind(Map.of()))
                .isEqualTo("CONCEPT");
        assertThat(CompetencyAssessmentService.firstQuestionKind(Map.of(
                "CONCEPT", 90,
                "SCENARIO", 80
        ))).isEqualTo("CODE");
    }

    @Test
    void retriesWeakestDimensionUntilAveragePasses() {
        assertThat(CompetencyAssessmentService.nextQuestionKind(Map.of(
                "CONCEPT", 80,
                "CODE", 60,
                "SCENARIO", 70
        ))).isEqualTo("CODE");
        assertThat(CompetencyAssessmentService.nextQuestionKind(Map.of(
                "CONCEPT", 90,
                "CODE", 75,
                "SCENARIO", 80
        ))).isNull();
    }

    @Test
    void scoreBelowIndividualMinimumIsNeverRetainedAsComplete() {
        assertThat(CompetencyAssessmentService.nextQuestionKind(Map.of(
                "CONCEPT", 90,
                "CODE", 59,
                "SCENARIO", 80
        ))).isEqualTo("CODE");
    }
}
