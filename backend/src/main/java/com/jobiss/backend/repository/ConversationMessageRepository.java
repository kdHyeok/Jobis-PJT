package com.jobiss.backend.repository;

import com.jobiss.backend.domain.ConversationMessage;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface ConversationMessageRepository extends JpaRepository<ConversationMessage, Long> {

    List<ConversationMessage> findByConversationIdOrderByIdAsc(Long conversationId);

    long countByConversationId(Long conversationId);
}
