package com.jobiss.backend.service;

import com.jobiss.backend.domain.AnalysisRun;
import com.jobiss.backend.exception.ApiException;
import com.jobiss.backend.repository.AnalysisRunRepository;
import jakarta.persistence.EntityManager;
import jakarta.persistence.PersistenceContext;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 분석 삭제(캐스케이드). 자식 재분석(parentAnalysisId 체인)까지 연쇄 삭제하고,
 * 자기 데이터(답변·질문·피드백·제출·결과·run_evidences)와 사용자 입력 공고를 지운다.
 * 저장 로드맵은 deleteRoadmaps 플래그로: true면 로드맵+스텝진행까지, false면 남겨 고아로 둔다
 * (남긴 로드맵은 로드맵 페이지·재진단·물어보기는 정상, 프론트에서 "분석 열기"만 비활성).
 * cascade에 의존하지 않고 자식→부모 순 네이티브 삭제(FK 안전, DevResetService와 동일 방식).
 */
@Service
public class AnalysisDeletionService {

    @PersistenceContext
    private EntityManager em;
    private final AnalysisRunRepository runRepository;

    public AnalysisDeletionService(AnalysisRunRepository runRepository) {
        this.runRepository = runRepository;
    }

    /** 삭제 미리보기: 함께 지워질 자식 분석 수 + 저장 로드맵 수(확인창 표시용). */
    @Transactional(readOnly = true)
    public Map<String, Object> preview(Long userId, String analysisId) {
        requireOwnedRoot(userId, analysisId);
        List<AnalysisRun> runs = collect(userId, analysisId);
        List<String> aids = runs.stream().map(AnalysisRun::getAnalysisId).toList();
        long roadmaps = ((Number) em.createNativeQuery(
                "select count(*) from saved_roadmaps where user_id = :uid and analysis_id in (:aids)")
                .setParameter("uid", userId).setParameter("aids", aids).getSingleResult()).longValue();
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("descendantCount", runs.size() - 1);   // 자기 자신 제외 = 함께 삭제될 자식 재분석 수
        out.put("roadmapCount", roadmaps);
        return out;
    }

    /** 분석 + 자식 재분석 연쇄 삭제. deleteRoadmaps=true면 저장 로드맵/스텝진행까지 함께. */
    @Transactional
    public Map<String, Object> delete(Long userId, String analysisId, boolean deleteRoadmaps) {
        requireOwnedRoot(userId, analysisId);
        List<AnalysisRun> runs = collect(userId, analysisId);
        List<Long> runIds = runs.stream().map(AnalysisRun::getId).toList();
        List<String> aids = runs.stream().map(AnalysisRun::getAnalysisId).toList();
        List<Long> jobIds = runs.stream().map(r -> r.getJobPosting().getId()).distinct().toList();

        execIds("delete from analysis_answers where run_id in (:ids)", runIds);
        execIds("delete from analysis_questions where run_id in (:ids)", runIds);
        execIds("delete from feedback_reports where submission_id in (select id from submissions where run_id in (:ids))", runIds);
        execIds("delete from submissions where run_id in (:ids)", runIds);
        execIds("delete from analysis_results where run_id in (:ids)", runIds);
        execIds("delete from run_evidences where run_id in (:ids)", runIds);

        int roadmaps = 0;
        if (deleteRoadmaps) {
            em.createNativeQuery("delete from roadmap_step_progress where user_id = :uid and analysis_id in (:aids)")
                    .setParameter("uid", userId).setParameter("aids", aids).executeUpdate();
            roadmaps = em.createNativeQuery("delete from saved_roadmaps where user_id = :uid and analysis_id in (:aids)")
                    .setParameter("uid", userId).setParameter("aids", aids).executeUpdate();
        }
        int runsDeleted = execIds("delete from analysis_runs where id in (:ids)", runIds);
        // 사용자 입력 공고 중 더 이상 어떤 run도 참조하지 않는 것만 정리(공유 샘플 user_id NULL은 제외)
        int jobs = em.createNativeQuery(
                "delete from job_postings where id in (:jids) and user_id = :uid " +
                "and id not in (select job_posting_id from analysis_runs)")
                .setParameter("jids", jobIds).setParameter("uid", userId).executeUpdate();
        em.clear();   // 네이티브 삭제로 사라진 엔티티가 영속성 컨텍스트에 남지 않게

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("deletedAnalyses", runsDeleted);
        out.put("deletedRoadmaps", roadmaps);
        out.put("deletedJobPostings", jobs);
        out.put("roadmapsKept", !deleteRoadmaps);
        return out;
    }

    private void requireOwnedRoot(Long userId, String analysisId) {
        AnalysisRun root = runRepository.findByAnalysisId(analysisId)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "RUN_NOT_FOUND", "분석을 찾을 수 없습니다."));
        if (!root.getUser().getId().equals(userId)) {
            throw new ApiException(HttpStatus.FORBIDDEN, "FORBIDDEN", "이 분석에 대한 권한이 없습니다.");
        }
    }

    /** root + 모든 자식(대체 재분석) 수집(BFS). 소유권 확인된 것만. */
    private List<AnalysisRun> collect(Long userId, String rootAnalysisId) {
        List<AnalysisRun> out = new ArrayList<>();
        Set<String> visited = new HashSet<>();
        Deque<String> queue = new ArrayDeque<>();
        queue.add(rootAnalysisId);
        while (!queue.isEmpty()) {
            String aid = queue.poll();
            if (!visited.add(aid)) continue;
            AnalysisRun run = runRepository.findByAnalysisId(aid).orElse(null);
            if (run == null || !run.getUser().getId().equals(userId)) continue;
            out.add(run);
            runRepository.findByUserIdAndParentAnalysisId(userId, aid)
                    .forEach(c -> queue.add(c.getAnalysisId()));
        }
        return out;
    }

    private int execIds(String sql, List<Long> ids) {
        return em.createNativeQuery(sql).setParameter("ids", ids).executeUpdate();
    }
}
