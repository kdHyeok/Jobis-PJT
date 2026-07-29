package com.jobiss.backend.service;

import com.jobiss.backend.domain.Evidence;
import com.jobiss.backend.domain.User;
import com.jobiss.backend.dto.evidence.EvidenceCreateRequest;
import com.jobiss.backend.dto.evidence.EvidenceResponse;
import com.jobiss.backend.repository.EvidenceRepository;
import com.jobiss.backend.repository.UserRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

@Service
public class EvidenceService {

    private final EvidenceRepository evidenceRepository;
    private final UserRepository userRepository;

    public EvidenceService(EvidenceRepository evidenceRepository, UserRepository userRepository) {
        this.evidenceRepository = evidenceRepository;
        this.userRepository = userRepository;
    }

    /** 로그인한 사용자의 자료만 조회(계정별 격리). */
    @Transactional(readOnly = true)
    public List<EvidenceResponse> list(Long userId) {
        return evidenceRepository.findByUserId(userId).stream()
                .map(EvidenceResponse::from)
                .toList();
    }

    @Transactional
    public EvidenceResponse create(Long userId, EvidenceCreateRequest req) {
        User userRef = userRepository.getReferenceById(userId);   // FK만 필요하므로 프록시로 충분
        Evidence evidence = Evidence.builder()
                .user(userRef)
                .kind(req.kind())
                .label(req.label())
                .description(req.description())
                .build();
        evidenceRepository.save(evidence);
        return EvidenceResponse.from(evidence);
    }
}
