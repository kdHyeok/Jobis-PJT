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
 * 채용공고. 샘플(code 있음·user 없음) 또는 사용자 입력(user 있음).
 * stack/parsed 는 MySQL JSON 컬럼(원문 JSON 문자열로 보관).
 */
@Entity
@Table(name = "job_postings")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class JobPosting {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(length = 50)
    private String code;                 // 샘플 슬러그 (예: 'cloudwave'), 사용자 입력이면 null

    @ManyToOne(fetch = FetchType.LAZY)   // 사용자 입력 공고면 소유자, 샘플이면 null
    @JoinColumn(name = "user_id")
    private User user;

    @Enumerated(EnumType.STRING)
    @Column(name = "source_type", nullable = false, length = 20)
    private JobSourceType sourceType;

    @Column(length = 100)
    private String company;

    @Column(length = 150)
    private String role;

    @Column(length = 50)
    private String career;

    @Column(length = 30)
    private String due;

    @Column(length = 500)
    private String url;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(columnDefinition = "json")
    private String stack;                // ["Java","Spring",...] 형태의 JSON 문자열

    @Column(name = "raw_text", columnDefinition = "TEXT")
    private String rawText;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(columnDefinition = "json")
    private String parsed;

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;

    @Builder
    private JobPosting(String code, User user, JobSourceType sourceType, String company, String role,
                       String career, String due, String url, String stack, String rawText, String parsed) {
        this.code = code;
        this.user = user;
        this.sourceType = sourceType;
        this.company = company;
        this.role = role;
        this.career = career;
        this.due = due;
        this.url = url;
        this.stack = stack;
        this.rawText = rawText;
        this.parsed = parsed;
    }

    /**
     * AI 에이전트가 분석 중 파악한 공고 구조(JOB_CONTEXT)를 반영.
     * 웹은 원문만 저장했었고, 회사·직무·요구스택은 AI가 알려준 값으로 채운다.
     */
    public void applyAiContext(String company, String role, String career, String stackJson) {
        this.company = company;
        this.role = role;
        this.career = career;
        this.stack = stackJson;
    }
}
