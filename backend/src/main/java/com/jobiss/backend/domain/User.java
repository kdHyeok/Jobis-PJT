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

    @Column(name = "job_title", length = 100)
    private String jobTitle;

    @Column(length = 50)
    private String status;

    @Column(nullable = false)
    private int completeness;

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;

    @UpdateTimestamp
    @Column(name = "updated_at")
    private LocalDateTime updatedAt;

    @Builder
    private User(String email, String passwordHash, String name, String jobTitle, String status, int completeness) {
        this.email = email;
        this.passwordHash = passwordHash;
        this.name = name;
        this.jobTitle = jobTitle;
        this.status = status;
        this.completeness = completeness;
    }
}
