package com.jobiss.security;

import com.jobiss.config.JobissProperties;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.springframework.stereotype.Component;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Date;
import java.util.UUID;

@Component
public class JwtService {

    private final JobissProperties properties;
    private final SecretKey key;

    public JwtService(JobissProperties properties) {
        this.properties = properties;
        byte[] secret = properties.auth().jwtSecret().getBytes(StandardCharsets.UTF_8);
        if (secret.length < 32) {
            throw new IllegalStateException("JWT_SECRET must contain at least 32 bytes");
        }
        this.key = Keys.hmacShaKeyFor(secret);
    }

    public String createAccessToken(UUID userId, long authVersion) {
        Instant now = Instant.now();
        return Jwts.builder()
                .subject(userId.toString())
                .claim("ver", authVersion)
                .issuedAt(Date.from(now))
                .expiration(Date.from(now.plusSeconds(properties.auth().accessTokenSeconds())))
                .signWith(key)
                .compact();
    }

    public TokenPrincipal parsePrincipal(String token) {
        Claims claims = Jwts.parser()
                .verifyWith(key)
                .build()
                .parseSignedClaims(token)
                .getPayload();
        Number version = claims.get("ver", Number.class);
        if (version == null) {
            throw new IllegalArgumentException("Token auth version is missing");
        }
        return new TokenPrincipal(
                UUID.fromString(claims.getSubject()),
                version.longValue()
        );
    }

    public record TokenPrincipal(UUID userId, long authVersion) {
    }
}
