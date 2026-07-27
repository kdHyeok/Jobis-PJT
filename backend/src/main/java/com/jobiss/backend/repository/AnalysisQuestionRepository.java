package com.jobiss.backend.repository;

import com.jobiss.backend.domain.AnalysisQuestion;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface AnalysisQuestionRepository extends JpaRepository<AnalysisQuestion, Long> {

    /** 특정 Run의 질문을 seq 순으로. */
    List<AnalysisQuestion> findByRunIdOrderBySeqAsc(Long runId);
}
