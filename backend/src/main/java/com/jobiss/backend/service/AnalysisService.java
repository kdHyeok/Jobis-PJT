package com.jobiss.backend.service;

import com.jobiss.backend.domain.AnalysisResult;
import com.jobiss.backend.domain.AnalysisRun;
import com.jobiss.backend.domain.JobPosting;
import com.jobiss.backend.domain.RunStatus;
import com.jobiss.backend.dto.analysis.AnalysisStatusResponse;
import com.jobiss.backend.dto.analysis.AnalysisSummaryResponse;
import com.jobiss.backend.dto.analysis.JobPostingBrief;
import com.jobiss.backend.dto.analysis.ResultResponse;
import com.jobiss.backend.exception.ApiException;
import com.jobiss.backend.repository.AnalysisResultRepository;
import com.jobiss.backend.repository.AnalysisRunRepository;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

/**
 * 분석 조회·상태 관리. 분석 자체는 에이전트(AgentRunService → 웹 브릿지)가 수행한다.
 * 목업 엔진(고정 질문·고정 결과)으로 분석을 만들던 경로는 제거했다 — 결과는 실제 판정만 적재된다.
 */
@Service
public class AnalysisService {

    private final AnalysisRunRepository runRepository;
    private final AnalysisResultRepository resultRepository;

    public AnalysisService(AnalysisRunRepository runRepository, AnalysisResultRepository resultRepository) {
        this.runRepository = runRepository;
        this.resultRepository = resultRepository;
    }

    @Transactional(readOnly = true)
    public AnalysisStatusResponse getStatus(Long userId, String analysisId) {
        AnalysisRun run = getOwnedRun(userId, analysisId);
        String parentId = run.getParentAnalysisId();
        String parentLabel = (parentId == null) ? null : runRepository.findByAnalysisId(parentId)
                .map(p -> {
                    JobPosting j = p.getJobPosting();
                    String c = j.getCompany() == null ? "" : j.getCompany();
                    String r = j.getRole() == null ? "" : j.getRole();
                    String label = (c + (r.isBlank() ? "" : " · " + r)).trim();
                    return label.isBlank() ? null : label;
                }).orElse(null);
        return new AnalysisStatusResponse(analysisId, run.getStatus().name(),
                JobPostingBrief.from(run.getJobPosting()), null, parentId, parentLabel, run.getSelectedRoute());
    }

    /** 경로 비교에서 주 경로 선택 저장(스펙 §11.3). 재선택 가능. */
    @Transactional
    public void selectRoute(Long userId, String analysisId, String routeId) {
        AnalysisRun run = getOwnedRun(userId, analysisId);
        String rid = (routeId != null && routeId.length() > 40) ? routeId.substring(0, 40) : routeId;
        run.selectRoute(rid);
    }

    @Transactional(readOnly = true)
    public ResultResponse getResult(Long userId, String analysisId) {
        AnalysisRun run = getOwnedRun(userId, analysisId);
        if (run.getStatus() != RunStatus.COMPLETED) {
            throw new ApiException(HttpStatus.CONFLICT, "RESULT_NOT_READY", "결과가 아직 준비되지 않았습니다.");
        }
        AnalysisResult result = resultRepository.findByRunId(run.getId())
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "RESULT_NOT_FOUND", "결과를 찾을 수 없습니다."));
        return new ResultResponse(JobPostingBrief.from(run.getJobPosting()), result.getResult());
    }

    /** 사이드바 "최근 분석": 내 분석 목록(최신순). */
    @Transactional(readOnly = true)
    public List<AnalysisSummaryResponse> listForUser(Long userId) {
        return runRepository.findByUserIdOrderByCreatedAtDesc(userId).stream()
                .map(AnalysisSummaryResponse::from)
                .toList();
    }

    /** analysisId 로 Run 조회 + 소유자 확인(남의 분석 접근 차단). */
    private AnalysisRun getOwnedRun(Long userId, String analysisId) {
        AnalysisRun run = runRepository.findByAnalysisId(analysisId)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "RUN_NOT_FOUND", "분석을 찾을 수 없습니다."));
        if (!run.getUser().getId().equals(userId)) {
            throw new ApiException(HttpStatus.FORBIDDEN, "FORBIDDEN", "접근 권한이 없습니다.");
        }
        return run;
    }
}
