package com.jobiss.auth;

import com.jobiss.config.JobissProperties;
import com.jobiss.security.CookieAuthenticationFilter;
import com.jobiss.security.JwtService;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Email;
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

    public AuthController(
            AuthService authService,
            JwtService jwtService,
            JobissProperties properties,
            LoginAttemptService loginAttempts,
            RegistrationRateLimitService registrationRateLimit
    ) {
        this.authService = authService;
        this.jwtService = jwtService;
        this.properties = properties;
        this.loginAttempts = loginAttempts;
        this.registrationRateLimit = registrationRateLimit;
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
                request.displayName()
        );
        setAccessCookie(response, user.id());
        return new AuthResponse(user);
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
            setAccessCookie(response, user.id());
            return new AuthResponse(user);
        } catch (RuntimeException exception) {
            loginAttempts.failed(attemptKey);
            throw exception;
        }
    }

    @PostMapping("/logout")
    void logout(HttpServletResponse response) {
        ResponseCookie cookie = ResponseCookie
                .from(CookieAuthenticationFilter.ACCESS_COOKIE, "")
                .httpOnly(true)
                .secure(properties.auth().cookieSecure())
                .sameSite("Lax")
                .path("/")
                .maxAge(Duration.ZERO)
                .build();
        response.addHeader(HttpHeaders.SET_COOKIE, cookie.toString());
    }

    @GetMapping("/me")
    AuthResponse me(@AuthenticationPrincipal UUID userId) {
        return new AuthResponse(authService.me(userId));
    }

    private void setAccessCookie(HttpServletResponse response, UUID userId) {
        String token = jwtService.createAccessToken(userId);
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

    public record RegisterRequest(
            @Email @NotBlank String email,
            @Size(min = 12, max = 100) String password,
            @NotBlank @Size(max = 80) String displayName
    ) {
    }

    public record LoginRequest(
            @Email @NotBlank String email,
            @NotBlank @Size(max = 100) String password
    ) {
    }

    public record AuthResponse(AuthService.UserView user) {
    }
}
