package com.jobiss.backend.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;

/**
 * 저장된 로드맵. 경로별(분석 + route)로 가짜 AI가 생성한 로드맵 JSON을 보관한다.
 * goalLabel = 목표 맥락(디딤돌이면 목표 회사·직무, 독립 목표면 null) — "디에스앤텍(목표)"과
 * "디에스앤텍(쉴드원 디딤돌)"을 구분하는 층.
 */
@Entity
@Table(name = "saved_roadmaps")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class SavedRoadmap {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(name = "analysis_id", length = 36, nullable = false)
    private String analysisId;

    @Column(name = "route_id", length = 40, nullable = false)
    private String routeId;

    @Column(name = "goal_label", length = 200)
    private String goalLabel;

    @Column(name = "roadmap_json", columnDefinition = "TEXT", nullable = false)
    private String roadmapJson;

    @Column(nullable = false)
    private boolean representative;

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;

    @Builder
    private SavedRoadmap(Long userId, String analysisId, String routeId, String goalLabel, String roadmapJson) {
        this.userId = userId;
        this.analysisId = analysisId;
        this.routeId = routeId;
        this.goalLabel = goalLabel;
        this.roadmapJson = roadmapJson;
        this.representative = false;
    }

    /** 같은 (분석·경로)를 다시 생성하면 내용 갱신(중복 저장 대신 교체). */
    public void updateRoadmap(String goalLabel, String roadmapJson) {
        this.goalLabel = goalLabel;
        this.roadmapJson = roadmapJson;
    }

    /** 대표 로드맵 지정(다음 arc). */
    public void setRepresentative(boolean representative) {
        this.representative = representative;
    }
}
