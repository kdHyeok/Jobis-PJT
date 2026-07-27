package com.jobiss.backend.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

/**
 * 분석이 생성한 추가 질문 한 개. 하나의 Run에 여러 개(seq 순서).
 */
@Entity
@Table(name = "analysis_questions")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class AnalysisQuestion {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "run_id", nullable = false)
    private AnalysisRun run;

    @Column(nullable = false)
    private int seq;

    @Column(nullable = false, length = 50)
    private String field;

    @Column(nullable = false, columnDefinition = "TEXT")
    private String title;

    @Column(columnDefinition = "TEXT")
    private String why;

    @Column(name = "default_answer", columnDefinition = "TEXT")
    private String defaultAnswer;

    @Column(length = 255)
    private String effect;

    @Builder
    private AnalysisQuestion(AnalysisRun run, int seq, String field, String title,
                            String why, String defaultAnswer, String effect) {
        this.run = run;
        this.seq = seq;
        this.field = field;
        this.title = title;
        this.why = why;
        this.defaultAnswer = defaultAnswer;
        this.effect = effect;
    }
}
