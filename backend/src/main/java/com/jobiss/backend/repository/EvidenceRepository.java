package com.jobiss.backend.repository;

import com.jobiss.backend.domain.Evidence;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface EvidenceRepository extends JpaRepository<Evidence, Long> {

    /** 특정 사용자의 자료만 조회(계정별 격리). user.id 로 자동 매핑됨. */
    List<Evidence> findByUserId(Long userId);
}
