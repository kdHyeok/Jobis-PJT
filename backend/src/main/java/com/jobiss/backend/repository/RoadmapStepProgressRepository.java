package com.jobiss.backend.repository;

import com.jobiss.backend.domain.RoadmapStepProgress;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface RoadmapStepProgressRepository extends JpaRepository<RoadmapStepProgress, Long> {

    /** 한 로드맵(분석·경로)의 모든 스텝 진행 상태. */
    List<RoadmapStepProgress> findByUserIdAndAnalysisIdAndRouteId(Long userId, String analysisId, String routeId);

    /** 특정 스텝의 진행 상태(제출 시 교체 대상). */
    Optional<RoadmapStepProgress> findByUserIdAndAnalysisIdAndRouteIdAndStepNo(
            Long userId, String analysisId, String routeId, int stepNo);
}
