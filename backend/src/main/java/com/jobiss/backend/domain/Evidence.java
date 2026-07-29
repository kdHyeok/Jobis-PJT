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
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.time.LocalDateTime;

/**
 * 내 커리어 저장소 자료 한 건. 반드시 소유자(user)가 있다.
 * payload 는 파싱 결과를 담는 JSON 컬럼(초기엔 null).
 */
@Entity
@Table(name = "evidences")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Evidence {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "user_id", nullable = false)
    private User user;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private EvidenceKind kind;

    @Column(nullable = false)
    private String label;

    @Column(columnDefinition = "TEXT")
    private String description;

    // status 제거: "부족/충족"은 evidence 속성이 아니라 분석 결과에 산다.

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(columnDefinition = "json")
    private String payload;

    /** 이 조각이 나온 이력서 원문(V6). null이면 직접 추가한 조각.
     *  느슨한 참조(FK 없음) — 원문을 지워도 조각은 커리어 증거로 남아야 한다. */
    @Column(name = "resume_document_id")
    private Long resumeDocumentId;

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;

    @Builder
    private Evidence(User user, EvidenceKind kind, String label, String description,
                     String payload, Long resumeDocumentId) {
        this.user = user;
        this.kind = kind;
        this.label = label;
        this.description = description;
        this.payload = payload;
        this.resumeDocumentId = resumeDocumentId;
    }
}
