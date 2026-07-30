package com.jobiss.backend.service;

import com.jobiss.backend.domain.Conversation;
import com.jobiss.backend.domain.User;
import com.jobiss.backend.repository.AnalysisRunRepository;
import com.jobiss.backend.repository.ConversationMessageRepository;
import com.jobiss.backend.repository.ConversationRepository;
import com.jobiss.backend.repository.UserRepository;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ConversationServiceTest {

    @Test
    void usesThePublicConversationIdAsTheAiSessionId() {
        ConversationRepository conversationRepository = mock(ConversationRepository.class);
        ConversationMessageRepository messageRepository = mock(ConversationMessageRepository.class);
        AnalysisRunRepository runRepository = mock(AnalysisRunRepository.class);
        UserRepository userRepository = mock(UserRepository.class);
        ConversationAiClient ai = mock(ConversationAiClient.class);

        User user = User.builder()
                .email("user@example.com")
                .passwordHash("hash")
                .name("사용자")
                .build();
        ReflectionTestUtils.setField(user, "id", 42L);

        Conversation conversation = Conversation.builder()
                .conversationId("conversation-uuid")
                .user(user)
                .title("새 대화")
                .build();
        ReflectionTestUtils.setField(conversation, "id", 7L);

        when(conversationRepository.findByConversationId("conversation-uuid"))
                .thenReturn(Optional.of(conversation));
        when(messageRepository.findByConversationIdOrderBySeqAsc(7L)).thenReturn(List.of());
        when(messageRepository.maxSeq(7L)).thenReturn(0);
        when(ai.chat("conversation-uuid", "안녕하세요")).thenReturn(Map.of("reply", "반가워요"));

        ConversationService service = new ConversationService(
                conversationRepository, messageRepository, runRepository, userRepository, ai);

        service.send(42L, "conversation-uuid", "안녕하세요");

        verify(ai).chat("conversation-uuid", "안녕하세요");
    }
}
