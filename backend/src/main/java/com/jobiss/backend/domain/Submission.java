package com.jobiss.backend.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
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
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;

/**
 * 산출물 제출(GitHub/배포 URL 등). 하나의 Run에 여러 번 제출 가능.
 */
@Entity
@Table(name = "submissions")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Submission {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "run_id", nullable = false)
    private AnalysisRun run;

    @Column(name = "github_url", length = 500)
    private String githubUrl;

    @Column(name = "deploy_url", length = 500)
    private String deployUrl;

    @Column(columnDefinition = "TEXT")
    private String note;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private SubmissionStatus status;

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;

    @Builder
    private Submission(AnalysisRun run, String githubUrl, String deployUrl, String note, SubmissionStatus status) {
        this.run = run;
        this.githubUrl = githubUrl;
        this.deployUrl = deployUrl;
        this.note = note;
        this.status = status;
    }

    public void changeStatus(SubmissionStatus next) {
        this.status = next;
    }
}
