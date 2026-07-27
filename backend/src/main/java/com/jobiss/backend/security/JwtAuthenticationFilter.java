package com.jobiss.backend.security;

import com.jobiss.backend.repository.UserRepository;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.lang.NonNull;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.AuthorityUtils;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

/**
 * 요청마다 Authorization: Bearer &lt;token&gt; 을 읽어 검증하고,
 * 유효하면 SecurityContext 에 인증 정보를 심는다(principal = userId).
 *
 * 서명이 맞아도 **그 사용자가 실제로 있는지** 확인한다. 없는 사용자의 토큰을 통과시키면
 * 인증은 성공한 채로 뒤 단계에서 "사용자를 찾을 수 없습니다"(404)가 나서, 사용자는 왜 안 되는지
 * 알 수 없고 재로그인으로 유도되지도 않는다(계정 삭제·DB 초기화 후 실제로 발생).
 * 인증을 심지 않으면 Spring Security 가 401/403 을 내고, 프론트(auth.js)가 로그인 화면으로 보낸다.
 */
@Component
public class JwtAuthenticationFilter extends OncePerRequestFilter {

    private static final Logger log = LoggerFactory.getLogger(JwtAuthenticationFilter.class);

    private final JwtTokenProvider tokenProvider;
    private final UserRepository userRepository;

    public JwtAuthenticationFilter(JwtTokenProvider tokenProvider, UserRepository userRepository) {
        this.tokenProvider = tokenProvider;
        this.userRepository = userRepository;
    }

    @Override
    protected void doFilterInternal(@NonNull HttpServletRequest request,
                                    @NonNull HttpServletResponse response,
                                    @NonNull FilterChain filterChain) throws ServletException, IOException {
        String header = request.getHeader("Authorization");
        if (header != null && header.startsWith("Bearer ")) {
            String token = header.substring(7);
            Long userId = tokenProvider.parseUserId(token);
            if (userId != null && SecurityContextHolder.getContext().getAuthentication() == null) {
                if (userRepository.existsById(userId)) {
                    UsernamePasswordAuthenticationToken authentication =
                            UsernamePasswordAuthenticationToken.authenticated(userId, null, AuthorityUtils.NO_AUTHORITIES);
                    SecurityContextHolder.getContext().setAuthentication(authentication);
                } else {
                    // 토큰은 유효하지만 계정이 사라졌다 — 인증하지 않고 넘긴다(재로그인 유도).
                    log.info("[인증] 없는 사용자의 토큰 거부: userId={}", userId);
                }
            }
        }
        filterChain.doFilter(request, response);
    }
}
