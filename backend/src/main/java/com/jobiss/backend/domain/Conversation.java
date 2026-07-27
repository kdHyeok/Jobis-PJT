package com.jobiss.backend.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.LocalDateTime;

/**
 * 일반 대화 한 건. 사이드바 목록의 한 줄이 이것이다.
 * AI 세션 키는 "conv-{id}" 로 만든다 — 대화마다 맥락이 격리된다.
 */
@Entity
@Table(name = "conversations")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Conversation {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(nullable = false, length = 120)
    private String title;

    @CreationTimestamp
    @Column(name = "created_at", nullable = false, updatable = false)
    private LocalDateTime createdAt;

    @UpdateTimestamp
    @Column(name = "updated_at", nullable = false)
    private LocalDateTime updatedAt;

    @Builder
    private Conversation(Long userId, String title) {
        this.userId = userId;
        this.title = title;
    }

    /** 첫 발화가 짧아 제목이 부실했을 때 다시 다듬을 수 있게 둔다. */
    public void rename(String title) {
        if (title != null && !title.isBlank()) {
            this.title = title;
        }
    }

    /** 세션 키 — AI 쪽 대화 맥락은 이 값으로 격리된다. */
    public String sessionId() {
        return "conv-" + id;
    }
}
