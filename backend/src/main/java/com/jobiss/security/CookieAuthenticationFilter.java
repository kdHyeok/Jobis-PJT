package com.jobiss.security;

import io.jsonwebtoken.JwtException;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.AuthorityUtils;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.Arrays;
import java.util.UUID;

@Component
public class CookieAuthenticationFilter extends OncePerRequestFilter {

    public static final String ACCESS_COOKIE = "jobiss_access";
    public static final String REFRESH_COOKIE = "jobiss_refresh";

    private final JwtService jwtService;
    private final AuthTokenVersionService tokenVersions;
    private final com.jobiss.config.JobissProperties properties;

    public CookieAuthenticationFilter(
            JwtService jwtService,
            AuthTokenVersionService tokenVersions,
            com.jobiss.config.JobissProperties properties
    ) {
        this.jwtService = jwtService;
        this.tokenVersions = tokenVersions;
        this.properties = properties;
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain
    ) throws ServletException, IOException {
        String token = findCookie(request, properties.auth().cookieName());
        if (token != null && SecurityContextHolder.getContext().getAuthentication() == null) {
            try {
                JwtService.TokenPrincipal principal = jwtService.parsePrincipal(token);
                if (!tokenVersions.isCurrent(principal.userId(), principal.authVersion())) {
                    throw new JwtException("Access token was invalidated");
                }
                var authentication = UsernamePasswordAuthenticationToken.authenticated(
                        principal.userId(),
                        null,
                        AuthorityUtils.createAuthorityList("ROLE_USER")
                );
                SecurityContextHolder.getContext().setAuthentication(authentication);
            } catch (JwtException | IllegalArgumentException ignored) {
                // Invalid cookies are treated as unauthenticated and never become an RLS identity.
            }
        }
        filterChain.doFilter(request, response);
    }

    public static String findCookie(HttpServletRequest request, String name) {
        if (request.getCookies() == null) {
            return null;
        }
        return Arrays.stream(request.getCookies())
                .filter(cookie -> name.equals(cookie.getName()))
                .map(Cookie::getValue)
                .findFirst()
                .orElse(null);
    }
}
