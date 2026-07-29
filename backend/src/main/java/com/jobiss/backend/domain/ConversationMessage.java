package com.jobiss.backend.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
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

import java.time.LocalDateTime;

/**
 * 대화 안의 한 줄.
 * <p>
 * role=ANALYSIS 인 줄은 말풍선이 아니라 "분석 카드"다 — 진행 내역을 여기에 복사해 두지 않고
 * analysisId 로 참조만 한다. 분석의 진짜 상태는 analysis_runs 가 갖고 있으므로,
 * 대화를 다시 열 때 그쪽에서 복원하는 편이 항상 최신이다.
 */
@Entity
@Table(name = "conversation_messages")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class ConversationMessage {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "conversation_id", nullable = false)
    private Conversation conversation;

    /** 대화 내 순서(1부터). 정렬 키. */
    @Column(nullable = false)
    private Integer seq;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private MessageRole role;

    @Column(columnDefinition = "TEXT")
    private String content;

    /** role=ANALYSIS 일 때 참조하는 분석. */
    @Column(name = "analysis_id", length = 36)
    private String analysisId;

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;

    @Builder
    private ConversationMessage(Conversation conversation, Integer seq, MessageRole role,
                                String content, String analysisId) {
        this.conversation = conversation;
        this.seq = seq;
        this.role = role;
        this.content = content;
        this.analysisId = analysisId;
    }
}
