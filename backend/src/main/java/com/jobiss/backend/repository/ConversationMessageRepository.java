package com.jobiss.backend.repository;

import com.jobiss.backend.domain.ConversationMessage;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;

public interface ConversationMessageRepository extends JpaRepository<ConversationMessage, Long> {

    List<ConversationMessage> findByConversationIdOrderBySeqAsc(Long conversationId);

    /** 다음 seq = max+1. 개수로 세면 중간 삭제 후 충돌하므로 최대값을 쓴다. */
    @Query("select coalesce(max(m.seq), 0) from ConversationMessage m where m.conversation.id = :conversationId")
    int maxSeq(@Param("conversationId") Long conversationId);

    void deleteByConversationId(Long conversationId);
}
