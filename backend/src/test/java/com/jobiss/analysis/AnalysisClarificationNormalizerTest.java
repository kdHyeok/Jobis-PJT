package com.jobiss.analysis;

import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class AnalysisClarificationNormalizerTest {

    @Test
    void semanticallyEquivalentEntryAnswersShareOneFingerprint() {
        AiContracts.AnalysisAnswer junior = new AiContracts.AnalysisAnswer(
                "career_stage",
                "어느 경력 단계인가요?",
                "junior",
                "신입",
                "CHOICE",
                "PROVIDED",
                List.of(),
                "NONE"
        );
        AiContracts.AnalysisAnswer entry = new AiContracts.AnalysisAnswer(
                "experience_level",
                "어느 경력 단계인가요?",
                "entry",
                "신입",
                "CHOICE",
                "PROVIDED",
                List.of(),
                "NONE"
        );

        assertThat(AnalysisClarificationNormalizer.fingerprint(List.of(junior)))
                .isEqualTo(AnalysisClarificationNormalizer.fingerprint(List.of(entry)));
    }

    @Test
    void normalizesKnownQuestionKeysAndOptionValues() {
        AiContracts.AnalysisQuestion normalized =
                AnalysisClarificationNormalizer.normalize(
                        new AiContracts.AnalysisQuestion(
                                "primary_role",
                                "어느 직무인가요?",
                                "복합 공고입니다.",
                                "CHOICE",
                                List.of(
                                        new AiContracts.AnalysisQuestionOption(
                                                "server_developer",
                                                "백엔드",
                                                "서버 직무"
                                        ),
                                        new AiContracts.AnalysisQuestionOption(
                                                "web_frontend",
                                                "프론트엔드",
                                                "웹 화면 직무"
                                        )
                                ),
                                List.of(),
                                "NONE"
                        )
                );

        assertThat(normalized.key()).isEqualTo("target_track");
        assertThat(normalized.options())
                .extracting(AiContracts.AnalysisQuestionOption::value)
                .containsExactly("backend", "frontend");
    }

    @Test
    void preservesFreeTextAnswersWithoutSluggingThem() {
        AiContracts.AnalysisAnswer answer = new AiContracts.AnalysisAnswer(
                "project_evidence",
                "프로젝트 경험을 알려주세요.",
                "Spring Boot로 주문 API를 만들고 Git으로 협업했습니다.",
                "Spring Boot로 주문 API를 만들고 Git으로 협업했습니다.",
                "TEXT",
                "PROVIDED",
                List.of("req-project"),
                "REQUIREMENTS"
        );

        AiContracts.AnalysisAnswer normalized =
                AnalysisClarificationNormalizer.normalize(answer);

        assertThat(normalized.answerValue())
                .isEqualTo("Spring Boot로 주문 API를 만들고 Git으로 협업했습니다.");
        assertThat(normalized.inputType()).isEqualTo("TEXT");
        assertThat(normalized.answerStatus()).isEqualTo("PROVIDED");
        assertThat(normalized.relatedRequirementIds()).containsExactly("req-project");
    }

    @Test
    void recognizesExplicitAndNaturalLanguageAbsence() {
        AiContracts.AnalysisAnswer typedAbsence = new AiContracts.AnalysisAnswer(
                "project_evidence",
                "프로젝트 경험을 알려주세요.",
                "따로 없습니다.",
                "따로 없습니다.",
                "TEXT",
                "PROVIDED",
                List.of("req-project"),
                "REQUIREMENTS"
        );

        AiContracts.AnalysisAnswer normalized =
                AnalysisClarificationNormalizer.normalize(typedAbsence);

        assertThat(normalized.answerStatus()).isEqualTo("CONFIRMED_ABSENT");
        assertThat(AnalysisClarificationNormalizer.answerStatus(
                "CONFIRMED_ABSENT",
                "GENERAL_EXPERIENCE",
                "없습니다."
        )).isEqualTo("CONFIRMED_ABSENT");
    }

    @Test
    void doesNotTreatQualifiedExperienceStatementAsAbsence() {
        assertThat(AnalysisClarificationNormalizer.isConfirmedAbsence(
                "실무 경험은 없지만 개인 프로젝트는 있습니다."
        )).isFalse();
    }
}
