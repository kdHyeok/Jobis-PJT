package com.jobiss.backend.repository;

import com.jobiss.backend.domain.AnalysisAnswer;
import org.springframework.data.jpa.repository.JpaRepository;

public interface AnalysisAnswerRepository extends JpaRepository<AnalysisAnswer, Long> {

    boolean existsByQuestionId(Long questionId);
}
