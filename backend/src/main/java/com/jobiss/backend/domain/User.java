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
 * 사용자(계정). users 테이블 1행 = User 객체 1개.
 * 캡슐화를 위해 @Setter를 두지 않고, 생성은 @Builder로만 한다.
 */
@Entity
@Table(name = "users")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)   // JPA가 요구하는 기본 생성자, 외부 사용은 막음
public class User {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)  // MySQL AUTO_INCREMENT
    private Long id;

    @Column(nullable = false, unique = true)
    private String email;

    @Column(name = "password_hash", nullable = false)
    private String passwordHash;

    @Column(nullable = false, length = 100)
    private String name;

    /** 계정 상태: ACTIVE | WITHDRAWN | SUSPENDED */
    @Column(nullable = false, length = 20)
    private String status;

    /** 탈퇴 시각(soft delete). null이면 활성. */
    @Column(name = "withdrawn_at")
    private LocalDateTime withdrawnAt;

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;

    @UpdateTimestamp
    @Column(name = "updated_at")
    private LocalDateTime updatedAt;

    @Builder
    private User(String email, String passwordHash, String name, String status) {
        this.email = email;
        this.passwordHash = passwordHash;
        this.name = name;
        this.status = (status == null || status.isBlank()) ? "ACTIVE" : status;
    }

    /** 탈퇴(soft delete) — 로그인 차단 + 탈퇴 시각 기록. 개인정보 파기는 별도 배치. */
    public void withdraw() {
        this.status = "WITHDRAWN";
        this.withdrawnAt = LocalDateTime.now();
    }
}
