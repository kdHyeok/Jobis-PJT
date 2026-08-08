package com.jobiss.conversation;

import com.jobiss.analysis.AiServiceException;
import org.junit.jupiter.api.Test;
import org.springframework.web.client.ResourceAccessException;

import java.net.ConnectException;

import static org.assertj.core.api.Assertions.assertThat;

class ChatReplyWorkerTest {

    @Test
    void retriesOnlyTransportFailures() {
        assertThat(ChatReplyWorker.isTransportFailure(
                new ResourceAccessException("connection refused", new ConnectException())
        )).isTrue();
        assertThat(ChatReplyWorker.isTransportFailure(
                new AiServiceException("INVALID_AI_RESPONSE", "schema mismatch")
        )).isFalse();
        assertThat(ChatReplyWorker.isTransportFailure(
                new IllegalStateException("missing message")
        )).isFalse();
    }
}
