package com.jobiss.auth;

import com.jobiss.config.JobissProperties;
import com.jobiss.security.CookieAuthenticationFilter;
import com.jobiss.security.JwtService;
import com.jobiss.security.AuthTokenVersionService;
import com.jobiss.security.RefreshTokenService;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.AssertTrue;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseCookie;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.web.csrf.CsrfToken;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.Duration;
import java.util.Map;
import java.util.UUID;

@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private final AuthService authService;
    private final JwtService jwtService;
    private final JobissProperties properties;
    private final LoginAttemptService loginAttempts;
    private final RegistrationRateLimitService registrationRateLimit;
    private final PasswordResetRateLimitService passwordResetRateLimit;
    private final PasswordResetService passwordResetService;
    private final AuthTokenVersionService tokenVersions;
    private final RefreshTokenService refreshTokens;

    public AuthController(
            AuthService authService,
            JwtService jwtService,
            JobissProperties properties,
            LoginAttemptService loginAttempts,
            RegistrationRateLimitService registrationRateLimit,
            PasswordResetRateLimitService passwordResetRateLimit,
            PasswordResetService passwordResetService,
            AuthTokenVersionService tokenVersions,
            RefreshTokenService refreshTokens
    ) {
        this.authService = authService;
        this.jwtService = jwtService;
        this.properties = properties;
        this.loginAttempts = loginAttempts;
        this.registrationRateLimit = registrationRateLimit;
        this.passwordResetRateLimit = passwordResetRateLimit;
        this.passwordResetService = passwordResetService;
        this.tokenVersions = tokenVersions;
        this.refreshTokens = refreshTokens;
    }

    @GetMapping("/csrf")
    Map<String, String> csrf(CsrfToken token) {
        return Map.of("headerName", token.getHeaderName(), "token", token.getToken());
    }

    @PostMapping("/register")
    AuthResponse register(
            @Valid @RequestBody RegisterRequest request,
            HttpServletRequest servletRequest,
            HttpServletResponse response
    ) {
        registrationRateLimit.consume(servletRequest.getRemoteAddr());
        AuthService.UserView user = authService.register(
                request.email(),
                request.password(),
                request.displayName(),
                request.policyVersion()
        );
        setSessionCookies(response, user.id(), false);
        return new AuthResponse(user);
    }

    @PostMapping("/password-reset/request")
    Map<String, String> requestPasswordReset(
            @Valid @RequestBody PasswordResetRequest request,
            HttpServletRequest servletRequest
    ) {
        passwordResetRateLimit.consume(
                servletRequest.getRemoteAddr() + "|" + request.email().trim().toLowerCase()
        );
        passwordResetService.request(request.email());
        return Map.of(
                "message",
                "가입된 이메일이라면 비밀번호 재설정 안내를 보냈습니다."
        );
    }

    @PostMapping("/password-reset/confirm")
    void confirmPasswordReset(@Valid @RequestBody PasswordResetConfirmRequest request) {
        passwordResetService.reset(request.token(), request.newPassword());
    }

    @PostMapping("/login")
    AuthResponse login(
            @Valid @RequestBody LoginRequest request,
            HttpServletRequest servletRequest,
            HttpServletResponse response
    ) {
        String attemptKey = servletRequest.getRemoteAddr()
                + "|" + request.email().trim().toLowerCase();
        loginAttempts.check(attemptKey);
        try {
            AuthService.UserView user = authService.login(request.email(), request.password());
            loginAttempts.succeeded(attemptKey);
            setSessionCookies(response, user.id(), request.rememberMe());
            return new AuthResponse(user);
        } catch (RuntimeException exception) {
            loginAttempts.failed(attemptKey);
            throw exception;
        }
    }

    @PostMapping("/logout")
    void logout(
            @AuthenticationPrincipal UUID userId,
            HttpServletRequest request,
            HttpServletResponse response
    ) {
        String refreshToken = CookieAuthenticationFilter.findCookie(
                request,
                CookieAuthenticationFilter.REFRESH_COOKIE
        );
        if (userId != null) {
            refreshTokens.revokeAll(userId);
            tokenVersions.invalidateAll(userId);
        } else {
            refreshTokens.revokeFamily(refreshToken);
        }
        clearSessionCookies(response);
    }

    @PostMapping("/refresh")
    AuthResponse refresh(HttpServletRequest request, HttpServletResponse response) {
        String rawToken = CookieAuthenticationFilter.findCookie(
                request,
                CookieAuthenticationFilter.REFRESH_COOKIE
        );
        RefreshTokenService.IssuedRefreshToken rotated = refreshTokens.rotate(rawToken);
        setAccessCookie(response, rotated.userId());
        setRefreshCookie(response, rotated);
        return new AuthResponse(authService.me(rotated.userId()));
    }

    @GetMapping("/me")
    AuthResponse me(@AuthenticationPrincipal UUID userId) {
        return new AuthResponse(authService.me(userId));
    }

    private void setSessionCookies(HttpServletResponse response, UUID userId, boolean rememberMe) {
        setAccessCookie(response, userId);
        setRefreshCookie(response, refreshTokens.issue(userId, rememberMe));
    }

    private void setAccessCookie(HttpServletResponse response, UUID userId) {
        String token = jwtService.createAccessToken(userId, tokenVersions.current(userId));
        ResponseCookie cookie = ResponseCookie
                .from(CookieAuthenticationFilter.ACCESS_COOKIE, token)
                .httpOnly(true)
                .secure(properties.auth().cookieSecure())
                .sameSite("Lax")
                .path("/")
                .maxAge(Duration.ofSeconds(properties.auth().accessTokenSeconds()))
                .build();
        response.addHeader(HttpHeaders.SET_COOKIE, cookie.toString());
    }

    private void setRefreshCookie(
            HttpServletResponse response,
            RefreshTokenService.IssuedRefreshToken token
    ) {
        long maxAge = Math.max(0, Duration.between(
                java.time.OffsetDateTime.now(),
                token.expiresAt()
        ).toSeconds());
        ResponseCookie cookie = ResponseCookie
                .from(CookieAuthenticationFilter.REFRESH_COOKIE, token.rawToken())
                .httpOnly(true)
                .secure(properties.auth().cookieSecure())
                .sameSite("Lax")
                .path("/api/auth")
                .maxAge(Duration.ofSeconds(maxAge))
                .build();
        response.addHeader(HttpHeaders.SET_COOKIE, cookie.toString());
    }

    private void clearSessionCookies(HttpServletResponse response) {
        response.addHeader(HttpHeaders.SET_COOKIE, expiredCookie(
                CookieAuthenticationFilter.ACCESS_COOKIE,
                "/"
        ).toString());
        response.addHeader(HttpHeaders.SET_COOKIE, expiredCookie(
                CookieAuthenticationFilter.REFRESH_COOKIE,
                "/api/auth"
        ).toString());
    }

    private ResponseCookie expiredCookie(String name, String path) {
        return ResponseCookie.from(name, "")
                .httpOnly(true)
                .secure(properties.auth().cookieSecure())
                .sameSite("Lax")
                .path(path)
                .maxAge(Duration.ZERO)
                .build();
    }

    public record RegisterRequest(
            @Email @NotBlank String email,
            @Size(min = 12, max = 100) String password,
            @NotBlank @Size(max = 80) String displayName,
            @AssertTrue(message = "이용약관에 동의해 주세요.") boolean termsAccepted,
            @AssertTrue(message = "개인정보 처리 안내에 동의해 주세요.") boolean privacyAccepted,
            @Pattern(regexp = "2026-08-04", message = "최신 정책을 확인해 주세요.")
            String policyVersion
    ) {
    }

    public record LoginRequest(
            @Email @NotBlank String email,
            @NotBlank @Size(max = 100) String password,
            boolean rememberMe
    ) {
    }

    public record PasswordResetRequest(
            @Email @NotBlank @Size(max = 320) String email
    ) {
    }

    public record PasswordResetConfirmRequest(
            @NotBlank @Size(min = 32, max = 200) String token,
            @NotBlank @Size(min = 12, max = 100) String newPassword
    ) {
    }

    public record AuthResponse(AuthService.UserView user) {
    }
}
