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
import jakarta.persistence.JoinTable;
import jakarta.persistence.ManyToMany;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.LocalDateTime;
import java.util.HashSet;
import java.util.Set;

/**
 * 분석 실행(Run). 상태 머신(RunStatus)을 따라 진행된다.
 * analysisId(UUID) = API 경로 & AI 계약 공용 식별자(백엔드 발급).
 * evidences = 이번 분석에 선택한 자료(run_evidences 조인 테이블).
 */
@Entity
@Table(name = "analysis_runs")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class AnalysisRun {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "analysis_id", nullable = false, unique = true, length = 36, updatable = false)
    private String analysisId;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "user_id", nullable = false)
    private User user;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "job_posting_id", nullable = false)
    private JobPosting jobPosting;

    /** 대체 공고 재분석이면 원래 분석의 analysisId(UUID). 독립 분석이면 null. */
    @Column(name = "parent_analysis_id", length = 36, updatable = false)
    private String parentAnalysisId;

    /** 경로 비교에서 사용자가 고른 주 경로 id(결과 JSON routes[].id). 미선택이면 null. */
    @Column(name = "selected_route", length = 40)
    private String selectedRoute;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private RunStatus status;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 10)
    private AnalysisEngine engine;

    @ManyToMany(fetch = FetchType.LAZY)
    @JoinTable(
            name = "run_evidences",
            joinColumns = @JoinColumn(name = "run_id"),
            inverseJoinColumns = @JoinColumn(name = "evidence_id")
    )
    private Set<Evidence> evidences = new HashSet<>();

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;

    @UpdateTimestamp
    @Column(name = "updated_at")
    private LocalDateTime updatedAt;

    @Builder
    private AnalysisRun(String analysisId, User user, JobPosting jobPosting, RunStatus status,
                        AnalysisEngine engine, Set<Evidence> evidences, String parentAnalysisId) {
        this.analysisId = analysisId;
        this.user = user;
        this.jobPosting = jobPosting;
        this.status = status;
        this.engine = engine;
        this.parentAnalysisId = parentAnalysisId;
        if (evidences != null) {
            this.evidences = evidences;
        }
    }

    /** 상태 전이는 setter가 아니라 의미 있는 메서드로. */
    public void changeStatus(RunStatus next) {
        this.status = next;
    }

    /** 경로 비교에서 주 경로 선택(재선택 가능). */
    public void selectRoute(String routeId) {
        this.selectedRoute = routeId;
    }
}
