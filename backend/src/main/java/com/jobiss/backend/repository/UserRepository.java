package com.jobiss.backend.repository;

import com.jobiss.backend.domain.User;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

/**
 * users 테이블 접근. JpaRepository 상속만으로 save/findById/findAll/delete 자동 제공.
 * 아래 두 메서드는 메서드 이름만으로 쿼리가 자동 생성된다(인증에서 사용).
 */
public interface UserRepository extends JpaRepository<User, Long> {

    Optional<User> findByEmail(String email);

    boolean existsByEmail(String email);
}
