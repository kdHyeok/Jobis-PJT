package com.jobiss.auth;

import com.jobiss.common.ApiException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.time.Instant;
import java.util.concurrent.ConcurrentHashMap;

@Component
public class PasswordResetRateLimitService {

    private static final int MAX_REQUESTS = 5;
    private static final Duration WINDOW = Duration.ofHours(1);
    private final ConcurrentHashMap<String, AttemptWindow> attempts = new ConcurrentHashMap<>();

    public void consume(String key) {
        AttemptWindow updated = attempts.compute(key, (ignored, current) -> {
            Instant now = Instant.now();
            if (current == null || current.expiresAt().isBefore(now)) {
                return new AttemptWindow(1, now.plus(WINDOW));
            }
            return new AttemptWindow(current.count() + 1, current.expiresAt());
        });
        if (attempts.size() > 20_000) {
            attempts.entrySet().removeIf(entry -> entry.getValue().expiresAt().isBefore(Instant.now()));
        }
        if (updated.count() > MAX_REQUESTS) {
            throw new ApiException(
                    HttpStatus.TOO_MANY_REQUESTS,
                    "PASSWORD_RESET_RATE_LIMITED",
                    "비밀번호 재설정 요청이 너무 많습니다. 잠시 후 다시 시도해 주세요."
            );
        }
    }

    private record AttemptWindow(int count, Instant expiresAt) {
    }
}
