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
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.Resource;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;

@Service
public class SubmissionService {

    private final AnalysisRunRepository runRepository;
    private final SubmissionRepository submissionRepository;
    private final FeedbackReportRepository feedbackReportRepository;
    private final String mockFeedbackJson;

    public SubmissionService(AnalysisRunRepository runRepository, SubmissionRepository submissionRepository,
                             FeedbackReportRepository feedbackReportRepository,
                             @Value("classpath:mock/cloudwave-feedback.json") Resource feedbackResource) {
        this.runRepository = runRepository;
        this.submissionRepository = submissionRepository;
        this.feedbackReportRepository = feedbackReportRepository;
        try (InputStream in = feedbackResource.getInputStream()) {
            this.mockFeedbackJson = new String(in.readAllBytes(), StandardCharsets.UTF_8);
        } catch (IOException e) {
            throw new IllegalStateException("mock 피드백 JSON을 읽을 수 없습니다.", e);
        }
    }

    /** 산출물 제출 → (Mock) 즉시 피드백 생성 → REVIEWED. */
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

        // Mock: 즉시 피드백 리포트 생성
        feedbackReportRepository.save(FeedbackReport.builder()
                .submission(submission)
                .report(mockFeedbackJson)
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
