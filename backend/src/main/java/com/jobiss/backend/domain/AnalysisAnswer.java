package com.jobiss.backend.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.OneToOne;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;

/**
 * 사용자가 특정 질문에 준 답변. 질문 1개당 답변 1개(unique).
 */
@Entity
@Table(name = "analysis_answers")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class AnalysisAnswer {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "run_id", nullable = false)
    private AnalysisRun run;

    @OneToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "question_id", nullable = false, unique = true)
    private AnalysisQuestion question;

    @Column(name = "answer_text", columnDefinition = "TEXT")
    private String answerText;

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;

    @Builder
    private AnalysisAnswer(AnalysisRun run, AnalysisQuestion question, String answerText) {
        this.run = run;
        this.question = question;
        this.answerText = answerText;
    }
}
