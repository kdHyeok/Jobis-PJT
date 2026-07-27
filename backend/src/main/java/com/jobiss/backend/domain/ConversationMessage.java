package com.jobiss.backend.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;

/** 대화 한 턴의 발화. agents 는 그 답을 만든 에이전트들(오케스트레이터 가시화). */
@Entity
@Table(name = "conversation_messages")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class ConversationMessage {

    public enum Role { USER, ASSISTANT }

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "conversation_id", nullable = false)
    private Long conversationId;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 16)
    private Role role;

    @Column(columnDefinition = "TEXT", nullable = false)
    private String content;

    @Column(length = 200)
    private String agents;

    @CreationTimestamp
    @Column(name = "created_at", nullable = false, updatable = false)
    private LocalDateTime createdAt;

    @Builder
    private ConversationMessage(Long conversationId, Role role, String content, String agents) {
        this.conversationId = conversationId;
        this.role = role;
        this.content = content;
        this.agents = agents;
    }
}
