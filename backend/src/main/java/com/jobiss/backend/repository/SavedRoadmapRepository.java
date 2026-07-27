package com.jobiss.backend.repository;

import com.jobiss.backend.domain.SavedRoadmap;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface SavedRoadmapRepository extends JpaRepository<SavedRoadmap, Long> {

    /** 로드맵 저장소 목록(내 것, 최신순) — 다음 arc. */
    List<SavedRoadmap> findByUserIdOrderByCreatedAtDesc(Long userId);

    /** 같은 (분석·경로) 로드맵이 이미 있으면 교체하기 위해 조회. */
    Optional<SavedRoadmap> findByUserIdAndAnalysisIdAndRouteId(Long userId, String analysisId, String routeId);
}
