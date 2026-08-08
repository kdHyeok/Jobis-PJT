package com.jobiss.analysis.v3;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class V3AtomicAssessmentServiceTest {

    @Test
    void requiresTwoOrThreeQuestionsBasedOnGraphMethods() {
        assertThat(V3AtomicAssessmentService.requiredQuestionCount(1)).isEqualTo(2);
        assertThat(V3AtomicAssessmentService.requiredQuestionCount(2)).isEqualTo(2);
        assertThat(V3AtomicAssessmentService.requiredQuestionCount(3)).isEqualTo(3);
        assertThat(V3AtomicAssessmentService.requiredQuestionCount(6)).isEqualTo(3);
    }

    @Test
    void requiresBothPerQuestionPassesAndSessionAverage() {
        assertThat(V3AtomicAssessmentService.sessionPasses(75, true)).isTrue();
        assertThat(V3AtomicAssessmentService.sessionPasses(74, true)).isFalse();
        assertThat(V3AtomicAssessmentService.sessionPasses(95, false)).isFalse();
    }
}
