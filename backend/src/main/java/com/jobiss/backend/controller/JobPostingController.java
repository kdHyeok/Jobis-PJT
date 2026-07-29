package com.jobiss.backend.controller;

import com.jobiss.backend.dto.job.JobSampleResponse;
import com.jobiss.backend.service.JobPostingService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/job-postings")
public class JobPostingController {

    private final JobPostingService jobPostingService;

    public JobPostingController(JobPostingService jobPostingService) {
        this.jobPostingService = jobPostingService;
    }

    /** 샘플 공고 목록(인증 불필요). */
    @GetMapping("/samples")
    public List<JobSampleResponse> samples() {
        return jobPostingService.getSamples();
    }
}
