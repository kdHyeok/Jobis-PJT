package com.jobiss.auth;

import com.jobiss.common.ApiException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.time.Instant;
import java.util.concurrent.ConcurrentHashMap;

@Component
public class LoginAttemptService {

    private static final int MAX_ATTEMPTS = 5;
    private static final Duration WINDOW = Duration.ofMinutes(15);

    private final ConcurrentHashMap<String, AttemptWindow> attempts = new ConcurrentHashMap<>();

    public void check(String key) {
        AttemptWindow current = attempts.get(key);
        if (current == null || current.expiresAt().isBefore(Instant.now())) {
            return;
        }
        if (current.count() >= MAX_ATTEMPTS) {
            throw new ApiException(
                    HttpStatus.TOO_MANY_REQUESTS,
                    "LOGIN_RATE_LIMITED",
                    "로그인 시도가 너무 많습니다. 잠시 후 다시 시도해 주세요."
            );
        }
    }

    public void failed(String key) {
        attempts.compute(key, (ignored, current) -> {
            Instant now = Instant.now();
            if (current == null || current.expiresAt().isBefore(now)) {
                return new AttemptWindow(1, now.plus(WINDOW));
            }
            return new AttemptWindow(current.count() + 1, current.expiresAt());
        });
        if (attempts.size() > 10_000) {
            attempts.entrySet().removeIf(entry -> entry.getValue().expiresAt().isBefore(Instant.now()));
        }
    }

    public void succeeded(String key) {
        attempts.remove(key);
    }

    private record AttemptWindow(int count, Instant expiresAt) {
    }
}
