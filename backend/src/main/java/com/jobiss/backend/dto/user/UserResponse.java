package com.jobiss.backend.dto.user;

import com.jobiss.backend.domain.User;

/** 사용자 정보 응답(비밀번호 등 민감정보 제외). */
public record UserResponse(
        Long id,
        String name,
        String email
) {
    public static UserResponse from(User u) {
        return new UserResponse(u.getId(), u.getName(), u.getEmail());
    }
}
