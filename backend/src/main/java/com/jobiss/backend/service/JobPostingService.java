package com.jobiss.backend.service;

import com.jobiss.backend.domain.JobSourceType;
import com.jobiss.backend.dto.job.JobSampleResponse;
import com.jobiss.backend.repository.JobPostingRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

@Service
public class JobPostingService {

    private final JobPostingRepository jobPostingRepository;

    public JobPostingService(JobPostingRepository jobPostingRepository) {
        this.jobPostingRepository = jobPostingRepository;
    }

    @Transactional(readOnly = true)
    public List<JobSampleResponse> getSamples() {
        return jobPostingRepository.findBySourceType(JobSourceType.SAMPLE).stream()
                .map(JobSampleResponse::from)
                .toList();
    }
}
