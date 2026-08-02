package com.jobiss.auth;

import com.jobiss.common.ApiException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.time.Instant;
import java.util.concurrent.ConcurrentHashMap;

@Component
public class RegistrationRateLimitService {

    private static final int MAX_REGISTRATIONS = 5;
    private static final Duration WINDOW = Duration.ofHours(1);

    private final ConcurrentHashMap<String, AttemptWindow> attempts = new ConcurrentHashMap<>();

    public void consume(String clientAddress) {
        AttemptWindow updated = attempts.compute(clientAddress, (ignored, current) -> {
            Instant now = Instant.now();
            if (current == null || current.expiresAt().isBefore(now)) {
                return new AttemptWindow(1, now.plus(WINDOW));
            }
            return new AttemptWindow(current.count() + 1, current.expiresAt());
        });
        if (attempts.size() > 10_000) {
            attempts.entrySet().removeIf(entry -> entry.getValue().expiresAt().isBefore(Instant.now()));
        }
        if (updated.count() > MAX_REGISTRATIONS) {
            throw new ApiException(
                    HttpStatus.TOO_MANY_REQUESTS,
                    "REGISTRATION_RATE_LIMITED",
                    "계정 생성 요청이 너무 많습니다. 잠시 후 다시 시도해 주세요."
            );
        }
    }

    private record AttemptWindow(int count, Instant expiresAt) {
    }
}
