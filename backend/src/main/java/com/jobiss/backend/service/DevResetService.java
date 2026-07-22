package com.jobiss.backend.service;

import jakarta.persistence.EntityManager;
import jakarta.persistence.PersistenceContext;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 개발/시연용: 계정은 **유지**하고, 그 계정의 저장소 자료 + 분석 내역만 비운다. **DEV ONLY · 배포 전 제거.**
 * 다시 로그인하면 "빈 상태"부터 시연을 반복할 수 있다.
 * cascade에 의존하지 않고 자식 → 부모 순으로 명시 삭제(FK 안전, 스키마 드리프트에도 견고).
 * 삭제 대상: (답변·질문·피드백·제출물·결과·run_evidences) → 분석런 → 자료 → 사용자 입력 공고. **users 행은 남긴다.**
 * 공유 샘플 공고(user_id NULL)는 건드리지 않는다.
 */
@Service
public class DevResetService {

    @PersistenceContext
    private EntityManager em;

    @Transactional
    public Map<String, Object> resetByEmail(String email) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("email", email);

        List<?> ids = em.createNativeQuery("select id from users where email = :e")
                .setParameter("e", email)
                .getResultList();
        if (ids.isEmpty()) {
            out.put("deleted", false);
            out.put("reason", "해당 이메일 사용자가 없습니다");
            return out;
        }
        long uid = ((Number) ids.get(0)).longValue();
        String userRuns = "(select id from analysis_runs where user_id = " + uid + ")";

        // 자식부터 명시적으로 (cascade 의존 X)
        exec("delete from analysis_answers where run_id in " + userRuns);
        exec("delete from analysis_questions where run_id in " + userRuns);
        exec("delete from feedback_reports where submission_id in (select id from submissions where run_id in " + userRuns + ")");
        exec("delete from submissions where run_id in " + userRuns);
        exec("delete from analysis_results where run_id in " + userRuns);
        exec("delete from run_evidences where run_id in " + userRuns);
        exec("delete from roadmap_step_progress where user_id = " + uid);           // 스텝 진행(V5)도 함께(고아 방지)
        int roadmaps = exec("delete from saved_roadmaps where user_id = " + uid);   // 저장 로드맵도 함께(고아 방지)
        int runs = exec("delete from analysis_runs where user_id = " + uid);
        int evidences = exec("delete from evidences where user_id = " + uid);
        int jobs = exec("delete from job_postings where user_id = " + uid);
        // users 행은 유지 → 같은 계정으로 다시 로그인하면 빈 상태

        out.put("deleted", true);
        out.put("keptAccount", true);
        out.put("evidences", evidences);
        out.put("runs", runs);
        out.put("savedRoadmaps", roadmaps);
        out.put("jobPostings", jobs);
        return out;
    }

    private int exec(String sql) {
        return em.createNativeQuery(sql).executeUpdate();
    }
}
