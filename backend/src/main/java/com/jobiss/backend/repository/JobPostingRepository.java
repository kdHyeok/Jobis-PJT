package com.jobiss.backend.repository;

import com.jobiss.backend.domain.JobPosting;
import com.jobiss.backend.domain.JobSourceType;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface JobPostingRepository extends JpaRepository<JobPosting, Long> {

    Optional<JobPosting> findByCode(String code);

    List<JobPosting> findBySourceType(JobSourceType sourceType);
}
