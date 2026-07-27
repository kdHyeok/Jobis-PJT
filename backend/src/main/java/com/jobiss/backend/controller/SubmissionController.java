package com.jobiss.backend.controller;

import com.jobiss.backend.dto.submission.FeedbackResponse;
import com.jobiss.backend.dto.submission.SubmissionCreateRequest;
import com.jobiss.backend.dto.submission.SubmissionResponse;
import com.jobiss.backend.service.SubmissionService;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class SubmissionController {

    private final SubmissionService submissionService;

    public SubmissionController(SubmissionService submissionService) {
        this.submissionService = submissionService;
    }

    /** 산출물 제출. */
    @PostMapping("/api/analyses/{analysisId}/submissions")
    public ResponseEntity<SubmissionResponse> submit(@AuthenticationPrincipal Long userId,
                                                     @PathVariable String analysisId,
                                                     @Valid @RequestBody SubmissionCreateRequest request) {
        return ResponseEntity.status(HttpStatus.ACCEPTED).body(submissionService.submit(userId, analysisId, request));
    }

    /** 피드백 리포트 조회. */
    @GetMapping("/api/submissions/{submissionId}/feedback")
    public FeedbackResponse feedback(@AuthenticationPrincipal Long userId, @PathVariable Long submissionId) {
        return submissionService.getFeedback(userId, submissionId);
    }
}
