package com.jobiss.backend.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.LocalDateTime;

/**
 * 대화 스레드. 목록(사이드바)의 단위이자 분석이 태어나는 자리.
 * conversationId(UUID) = API 경로 식별자(백엔드 발급) — analysisId 와 같은 방식.
 */
@Entity
@Table(name = "conversations")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Conversation {

    /** 제목이 길면 목록에서 잘려 보이므로 저장 단계에서 줄인다. */
    public static final int TITLE_MAX = 60;

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "conversation_id", nullable = false, unique = true, length = 36, updatable = false)
    private String conversationId;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "user_id", nullable = false)
    private User user;

    @Column(nullable = false, length = 200)
    private String title;

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;

    @UpdateTimestamp
    @Column(name = "updated_at")
    private LocalDateTime updatedAt;

    @Builder
    private Conversation(String conversationId, User user, String title) {
        this.conversationId = conversationId;
        this.user = user;
        this.title = clip(title);
    }

    /** 첫 발화가 들어오면 제목을 그 문장으로 바꾼다(ChatGPT 와 같은 방식). */
    public void rename(String title) {
        if (title != null && !title.isBlank()) {
            this.title = clip(title);
        }
    }

    /**
     * 활동이 있었음을 표시 — 목록이 "최근 활동" 순으로 정렬되게 한다.
     * 메시지는 자식 테이블이라 이 엔티티가 더티가 되지 않으면 @UpdateTimestamp 가 안 돈다.
     */
    public void touch() {
        this.updatedAt = LocalDateTime.now();
    }

    private static String clip(String s) {
        String t = s == null ? "" : s.replaceAll("\\s+", " ").trim();
        if (t.isEmpty()) return "새 대화";
        return t.length() > TITLE_MAX ? t.substring(0, TITLE_MAX) + "…" : t;
    }
}
