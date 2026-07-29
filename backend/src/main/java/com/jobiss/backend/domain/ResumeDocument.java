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
 * 이력서 원문. 파편화하면 조각(Evidence)이 생기지만, 원문 자체도 남겨 다시 쓸 수 있게 한다.
 * - 재사용: 다음 분석에서 붙여넣기 없이 불러오기
 * - 근거 추적: 조각이 어느 원문에서 나왔는지(evidences.resume_document_id)
 * - 갱신 이력: 이력서를 고쳐 다시 저장
 * user 는 연관 대신 id 로만 들고 있다(목록 조회가 잦아 LAZY 로딩 비용을 피함).
 */
@Entity
@Table(name = "resume_documents")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class ResumeDocument {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(nullable = false, length = 150)
    private String title;

    @Column(name = "source_type", nullable = false, length = 20)
    private String sourceType;   // TEXT | FILE | GITHUB

    /** GITHUB 원주소 등 (nullable). */
    @Column(name = "source_url")
    private String sourceUrl;

    /** 원본 파일 위치(오브젝트 스토리지). AI가 파일 직접 읽는 경우 (nullable). */
    @Column(name = "file_key")
    private String fileKey;

    /** 원문 텍스트. AI가 파일 직접 읽으면 없을 수 있음 (nullable). */
    @Column(columnDefinition = "TEXT")
    private String content;

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;

    @UpdateTimestamp
    @Column(name = "updated_at")
    private LocalDateTime updatedAt;

    @Builder
    private ResumeDocument(Long userId, String title, String sourceType, String sourceUrl, String fileKey, String content) {
        this.userId = userId;
        this.title = title;
        this.sourceType = sourceType;
        this.sourceUrl = sourceUrl;
        this.fileKey = fileKey;
        this.content = content;
    }

    /** 원문 갱신(같은 문서를 고쳐 저장). */
    public void update(String title, String content) {
        if (title != null && !title.isBlank()) this.title = title;
        if (content != null && !content.isBlank()) this.content = content;
    }
}
