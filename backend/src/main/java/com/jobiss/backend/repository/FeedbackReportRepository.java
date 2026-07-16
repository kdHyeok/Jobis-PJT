package com.jobiss.backend.repository;

import com.jobiss.backend.domain.FeedbackReport;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface FeedbackReportRepository extends JpaRepository<FeedbackReport, Long> {

    Optional<FeedbackReport> findBySubmissionId(Long submissionId);
}
