package com.jobiss.backend.service.agent;

import com.jobiss.backend.domain.AnalysisResult;
import com.jobiss.backend.domain.AnalysisRun;
import com.jobiss.backend.domain.RunStatus;
import com.jobiss.backend.repository.AnalysisResultRepository;
import com.jobiss.backend.repository.AnalysisRunRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 가짜 AI 세션이 비동기(WebSocket 콜백 스레드)에서 DB에 쓸 때 쓰는 트랜잭션 경계.
 * DONE/ERROR 신호가 올 때 호출된다.
 */
@Service
public class AgentResultService {

    private final AnalysisRunRepository runRepository;
    private final AnalysisResultRepository resultRepository;

    public AgentResultService(AnalysisRunRepository runRepository, AnalysisResultRepository resultRepository) {
        this.runRepository = runRepository;
        this.resultRepository = resultRepository;
    }

    /** DONE: §B 결과 저장 + COMPLETED. */
    @Transactional
    public void complete(String analysisId, String resultJson) {
        AnalysisRun run = runRepository.findByAnalysisId(analysisId).orElse(null);
        if (run == null) return;
        if (resultRepository.findByRunId(run.getId()).isEmpty()) {
            resultRepository.save(AnalysisResult.builder().run(run).result(resultJson).build());
        }
        run.changeStatus(RunStatus.COMPLETED);
    }

    /** ERROR/연결실패: FAILED. */
    @Transactional
    public void fail(String analysisId, String reason) {
        runRepository.findByAnalysisId(analysisId).ifPresent(run -> run.changeStatus(RunStatus.FAILED));
    }

    /** JOB_CONTEXT: AI가 파악한 공고 구조(회사·직무·경력·요구스택)를 JobPosting에 반영(재접속 헤더·세션목록용). */
    @Transactional
    public void saveJobContext(String analysisId, String company, String role, String career, String stackJson) {
        runRepository.findByAnalysisId(analysisId).ifPresent(run -> {
            var job = run.getJobPosting();
            // 공유 샘플 공고(user==null)는 덮어쓰지 않는다 — 시드 데이터 보호. 사용자 입력 공고만 반영.
            if (job.getUser() == null) return;
            job.applyAiContext(cap(company, 100), cap(role, 150), cap(career, 50),
                    stackJson == null ? "[]" : stackJson);
        });
    }

    private static String cap(String s, int n) {
        if (s == null) return null;
        return s.length() > n ? s.substring(0, n) : s;
    }
}
