package com.jobiss.conversation;

import static org.assertj.core.api.Assertions.assertThat;

import com.jobiss.analysis.AiServiceException;
import java.io.IOException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.web.client.ResourceAccessException;

class ChatReplyWorkerTest {

    @Test
    @DisplayName("AI 서버에 닿지 못한 실패는 되돌린다")
    void transportFailuresAreRetryable() {
        // 실측 08-04 09:20 에 실제로 온 두 가지 — AI 서버 재시작 전후.
        assertThat(ChatReplyWorker.isTransportFailure(new ResourceAccessException(
                "I/O error on POST request for \"http://localhost:8000/v1/chat/stream\": "
                        + "Connection reset",
                new IOException("Connection reset")
        ))).isTrue();
        assertThat(ChatReplyWorker.isTransportFailure(new ResourceAccessException(
                "I/O error on POST request for \"http://localhost:8000/v1/chat/stream\": "
                        + "Connection refused: getsockopt"
        ))).isTrue();
    }

    @Test
    @DisplayName("AI 가 스스로 낸 오류는 되돌리지 않는다 — 다시 걸어도 같은 답이다")
    void aiErrorsAreNotRetried() {
        assertThat(ChatReplyWorker.isTransportFailure(
                new AiServiceException("AI_PROVIDER_UNAVAILABLE", "엔진이 실패했습니다.")
        )).isFalse();
        assertThat(ChatReplyWorker.isTransportFailure(
                new IllegalStateException("AI response did not include a message")
        )).isFalse();
    }

    @Test
    @DisplayName("AI 오류를 전송 실패로 감싸도 되돌리지 않는다")
    void wrappedAiErrorWins() {
        assertThat(ChatReplyWorker.isTransportFailure(new IllegalStateException(
                "wrapped",
                new AiServiceException("INVALID_AI_RESPONSE", "해석 실패", new IOException())
        ))).isFalse();
    }
}
