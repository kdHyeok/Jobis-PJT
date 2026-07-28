package com.jobiss.backend.service;

import com.jobiss.backend.domain.AnalysisRun;
import com.jobiss.backend.domain.FeedbackReport;
import com.jobiss.backend.domain.Submission;
import com.jobiss.backend.domain.SubmissionStatus;
import com.jobiss.backend.dto.submission.FeedbackResponse;
import com.jobiss.backend.dto.submission.SubmissionCreateRequest;
import com.jobiss.backend.dto.submission.SubmissionResponse;
import com.jobiss.backend.exception.ApiException;
import com.jobiss.backend.repository.AnalysisRunRepository;
import com.jobiss.backend.repository.FeedbackReportRepository;
import com.jobiss.backend.repository.SubmissionRepository;
import com.jobiss.backend.repository.AnalysisResultRepository;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 산출물 제출 → AI 검토 → 피드백 저장.
 * 고정 피드백 JSON(mock)을 돌려주던 경로는 제거했다 — 제출 링크·메모를 그 분석의 공고 요건과
 * 실제로 대조해 결과를 적재한다(SubmissionReviewClient).
 */
@Service
public class SubmissionService {

    private final AnalysisRunRepository runRepository;
    private final SubmissionRepository submissionRepository;
    private final FeedbackReportRepository feedbackReportRepository;
    private final AnalysisResultRepository resultRepository;
    private final SubmissionReviewClient reviewClient;

    public SubmissionService(AnalysisRunRepository runRepository, SubmissionRepository submissionRepository,
                             FeedbackReportRepository feedbackReportRepository,
                             AnalysisResultRepository resultRepository,
                             SubmissionReviewClient reviewClient) {
        this.runRepository = runRepository;
        this.submissionRepository = submissionRepository;
        this.feedbackReportRepository = feedbackReportRepository;
        this.resultRepository = resultRepository;
        this.reviewClient = reviewClient;
    }

    /** 산출물 제출 → AI 가 공고 요건과 대조 → 피드백 저장 → REVIEWED. */
    @Transactional
    public SubmissionResponse submit(Long userId, String analysisId, SubmissionCreateRequest req) {
        AnalysisRun run = runRepository.findByAnalysisId(analysisId)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "RUN_NOT_FOUND", "분석을 찾을 수 없습니다."));
        if (!run.getUser().getId().equals(userId)) {
            throw new ApiException(HttpStatus.FORBIDDEN, "FORBIDDEN", "접근 권한이 없습니다.");
        }

        Submission submission = Submission.builder()
                .run(run)
                .githubUrl(req.githubUrl())
                .deployUrl(req.deployUrl())
                .note(req.note())
                .status(SubmissionStatus.VALIDATING)
                .build();
        submissionRepository.save(submission);

        // 이 분석의 공고 요건을 꺼내 제출물과 대조한다. 결과 JSON 을 그대로 저장한다.
        List<String> requirements = resultRepository.findByRunId(run.getId())
                .map(r -> reviewClient.requirementsOf(r.getResult()))
                .orElse(List.of());
        String reportJson = reviewClient.review(req.githubUrl(), req.deployUrl(), req.note(), requirements);

        feedbackReportRepository.save(FeedbackReport.builder()
                .submission(submission)
                .report(reportJson)
                .reviewedAt(LocalDateTime.now())
                .build());
        submission.changeStatus(SubmissionStatus.REVIEWED);

        return new SubmissionResponse(submission.getId(), submission.getStatus().name());
    }

    @Transactional(readOnly = true)
    public FeedbackResponse getFeedback(Long userId, Long submissionId) {
        Submission submission = submissionRepository.findById(submissionId)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "SUBMISSION_NOT_FOUND", "제출물을 찾을 수 없습니다."));
        if (!submission.getRun().getUser().getId().equals(userId)) {
            throw new ApiException(HttpStatus.FORBIDDEN, "FORBIDDEN", "접근 권한이 없습니다.");
        }
        FeedbackReport report = feedbackReportRepository.findBySubmissionId(submissionId)
                .orElseThrow(() -> new ApiException(HttpStatus.CONFLICT, "FEEDBACK_NOT_READY", "피드백이 아직 준비되지 않았습니다."));
        return new FeedbackResponse(submissionId, submission.getStatus().name(), report.getReviewedAt(), report.getReport());
    }
}
