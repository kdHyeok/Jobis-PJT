package com.jobiss.backend.repository;

import com.jobiss.backend.domain.Submission;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface SubmissionRepository extends JpaRepository<Submission, Long> {

    List<Submission> findByRunIdOrderByCreatedAtDesc(Long runId);
}
