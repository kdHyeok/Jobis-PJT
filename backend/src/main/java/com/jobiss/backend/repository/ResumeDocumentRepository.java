package com.jobiss.backend.repository;

import com.jobiss.backend.domain.ResumeDocument;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface ResumeDocumentRepository extends JpaRepository<ResumeDocument, Long> {

    /** 내 이력서 원문 목록(최신순). */
    List<ResumeDocument> findByUserIdOrderByUpdatedAtDesc(Long userId);

    long countByUserId(Long userId);
}
