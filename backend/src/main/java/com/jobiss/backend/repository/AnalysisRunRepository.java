package com.jobiss.backend.repository;

import com.jobiss.backend.domain.AnalysisRun;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;
import java.util.Optional;

public interface AnalysisRunRepository extends JpaRepository<AnalysisRun, Long> {

    /** API 경로의 UUID(analysisId)로 Run 조회. */
    Optional<AnalysisRun> findByAnalysisId(String analysisId);

    /** 사이드바 세션 목록: 내 분석을 최신순으로. */
    List<AnalysisRun> findByUserIdOrderByCreatedAtDesc(Long userId);

    /** 대체 재분석 자식 조회(삭제 시 연쇄용). */
    List<AnalysisRun> findByUserIdAndParentAnalysisId(Long userId, String parentAnalysisId);

    /** 대화 목록에 "이 대화의 분석" 상태를 같이 얹기 위한 조회(목록 N+1 방지). */
    @Query("select r from AnalysisRun r where r.conversation.id in :conversationIds order by r.createdAt desc")
    List<AnalysisRun> findByConversationIds(@Param("conversationIds") List<Long> conversationIds);

    /** analysisId의 소유자 userId만 조회(STOMP 소유권 검증용, 엔티티 로딩 없이). */
    @Query("select r.user.id from AnalysisRun r where r.analysisId = :analysisId")
    Optional<Long> findOwnerIdByAnalysisId(@Param("analysisId") String analysisId);
}
