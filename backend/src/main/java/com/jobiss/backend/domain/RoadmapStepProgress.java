package com.jobiss.backend.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.LocalDateTime;

/**
 * 로드맵 스텝별 진행/재진단 결과. (user + analysis + route + stepNo) 하나당 한 행(제출하면 교체).
 * 산출물 링크를 제출하면 가짜 AI가 재진단해 status/verdict 를 갱신한다.
 */
@Entity
@Table(name = "roadmap_step_progress")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class RoadmapStepProgress {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(name = "analysis_id", length = 36, nullable = false)
    private String analysisId;

    @Column(name = "route_id", length = 40, nullable = false)
    private String routeId;

    @Column(name = "step_no", nullable = false)
    private int stepNo;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private RoadmapStepStatus status;

    @Column(name = "submitted_url", length = 500)
    private String submittedUrl;

    @Column(name = "verdict_json", columnDefinition = "TEXT")
    private String verdictJson;

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;

    @UpdateTimestamp
    @Column(name = "updated_at")
    private LocalDateTime updatedAt;

    @Builder
    private RoadmapStepProgress(Long userId, String analysisId, String routeId, int stepNo,
                                RoadmapStepStatus status, String submittedUrl, String verdictJson) {
        this.userId = userId;
        this.analysisId = analysisId;
        this.routeId = routeId;
        this.stepNo = stepNo;
        this.status = status;
        this.submittedUrl = submittedUrl;
        this.verdictJson = verdictJson;
    }

    /** 같은 스텝을 다시 제출하면 최신 결과로 교체. */
    public void update(RoadmapStepStatus status, String submittedUrl, String verdictJson) {
        this.status = status;
        this.submittedUrl = submittedUrl;
        this.verdictJson = verdictJson;
    }
}
