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
                "신입"
        );
        AiContracts.AnalysisAnswer entry = new AiContracts.AnalysisAnswer(
                "experience_level",
                "어느 경력 단계인가요?",
                "entry",
                "신입"
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
                                )
                        )
                );

        assertThat(normalized.key()).isEqualTo("target_track");
        assertThat(normalized.options())
                .extracting(AiContracts.AnalysisQuestionOption::value)
                .containsExactly("backend", "frontend");
    }
}
