package com.jobiss.backend.dto.auth;

import com.jobiss.backend.dto.user.UserResponse;

/** 로그인/회원가입 응답: 토큰 + 사용자 정보. */
public record AuthResponse(String token, UserResponse user) {
}
