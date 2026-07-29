package com.jobiss.backend.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;

/**
 * 단계형 로드맵의 "단계 상세" 캐시. 개요(saved_roadmaps.roadmap_json)는 로드맵 생성 시 한 번에 나오지만,
 * 각 단계의 레슨·예제·결과물·시험 상세는 그 단계를 열 때 가짜 AI가 생성한다(느림). 한 번 만든 건 여기 캐시해
 * 다시 열 때 즉시 보여준다. (saved_roadmap_id, stage_no) 당 1행.
 */
@Entity
@Table(name = "roadmap_stage_details",
        uniqueConstraints = @UniqueConstraint(name = "uk_stage_detail", columnNames = {"saved_roadmap_id", "stage_no"}))
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class RoadmapStageDetail {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "saved_roadmap_id", nullable = false)
    private Long savedRoadmapId;

    @Column(name = "stage_no", nullable = false)
    private int stageNo;

    @Column(name = "detail_json", columnDefinition = "TEXT", nullable = false)
    private String detailJson;

    @CreationTimestamp
    @Column(name = "generated_at", updatable = false)
    private LocalDateTime generatedAt;

    @Builder
    private RoadmapStageDetail(Long savedRoadmapId, int stageNo, String detailJson) {
        this.savedRoadmapId = savedRoadmapId;
        this.stageNo = stageNo;
        this.detailJson = detailJson;
    }

    /** 재생성 시 교체(캐시 무효화 대용). */
    public void updateDetail(String detailJson) {
        this.detailJson = detailJson;
    }
}
