package com.jobiss.backend.config;

import com.jobiss.backend.security.JwtAuthenticationFilter;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

/**
 * 보안 설정. 세션 없이(STATELESS) JWT로만 인증.
 * 공개: /health, /api/auth/**, GET /api/job-postings/samples. 나머지는 토큰 필요.
 */
@Configuration
public class SecurityConfig {

    private final JwtAuthenticationFilter jwtAuthenticationFilter;

    public SecurityConfig(JwtAuthenticationFilter jwtAuthenticationFilter) {
        this.jwtAuthenticationFilter = jwtAuthenticationFilter;
    }

    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http
                .csrf(csrf -> csrf.disable())
                .sessionManagement(sm -> sm.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(auth -> auth
                        // 정적 프론트(목업) — 로그인 전에도 페이지 자체는 열 수 있어야 함
                        .requestMatchers("/", "/*.html", "/*.css", "/*.js", "/favicon.ico", "/error").permitAll()
                        .requestMatchers("/chat-app/**", "/ws/**").permitAll()   // 채팅 목업 + STOMP 핸드셰이크
                        .requestMatchers("/img/**", "/vid/**").permitAll()       // 배경 이미지/영상 등 정적 미디어
                        .requestMatchers("/health", "/api/auth/register", "/api/auth/login").permitAll()
                        .requestMatchers(HttpMethod.GET, "/api/job-postings/samples").permitAll()
                        .requestMatchers("/api/dev/**").permitAll()   // DEV ONLY — 가짜 AI 트리거, 배포 전 제거
                        .anyRequest().authenticated()
                )
                // 인증 실패(토큰 없음·만료·무효)는 401 — 프론트가 401에서만 로그인으로 자동 이동한다.
                // (기본값은 403이라, 토큰 만료가 "Forbidden" 이라는 혼란스러운 에러로만 떴다.)
                // 권한 거부(남의 리소스 접근)는 서비스의 ApiException(FORBIDDEN)이 그대로 403으로 낸다 — 여기 영향 없음.
                .exceptionHandling(ex -> ex.authenticationEntryPoint((request, response, authEx) -> {
                    response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
                    response.setContentType("application/json;charset=UTF-8");
                    response.getWriter().write("{\"error\":{\"code\":\"UNAUTHORIZED\",\"message\":\"로그인이 필요합니다.\"}}");
                }))
                .addFilterBefore(jwtAuthenticationFilter, UsernamePasswordAuthenticationFilter.class);
        return http.build();
    }

    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }
}
