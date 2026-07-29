package com.jobiss.backend.repository;

import com.jobiss.backend.domain.Conversation;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface ConversationRepository extends JpaRepository<Conversation, Long> {

    Optional<Conversation> findByConversationId(String conversationId);

    /** 사이드바 목록 — 최근 활동 순. */
    List<Conversation> findByUserIdOrderByUpdatedAtDesc(Long userId);

    long countByUserId(Long userId);
}
