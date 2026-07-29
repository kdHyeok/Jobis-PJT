package com.jobiss.backend.repository;

import com.jobiss.backend.domain.RoadmapStageDetail;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface RoadmapStageDetailRepository extends JpaRepository<RoadmapStageDetail, Long> {

    /** 단계 상세 캐시 조회. (saved_roadmap_id, stage_no) 당 1행. */
    Optional<RoadmapStageDetail> findBySavedRoadmapIdAndStageNo(Long savedRoadmapId, int stageNo);
}
