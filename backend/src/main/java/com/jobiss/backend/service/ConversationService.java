package com.jobiss.backend.service;

import com.jobiss.backend.domain.Conversation;
import com.jobiss.backend.domain.ConversationMessage;
import com.jobiss.backend.dto.chat.ConversationMessageResponse;
import com.jobiss.backend.dto.chat.ConversationResponse;
import com.jobiss.backend.exception.ApiException;
import com.jobiss.backend.repository.ConversationMessageRepository;
import com.jobiss.backend.repository.ConversationRepository;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

/**
 * 대화 목록·이력 적재. 사이드바의 대화창과 새로고침 후 이어보기가 여기서 나온다.
 *
 * AI 쪽 대화 맥락(세션)은 브릿지 메모리에 있고 서버 재시작하면 사라진다. 그래서 사용자에게 보이는
 * 이력은 DB 에 남긴다 — 둘의 역할이 다르다(맥락 vs 기록).
 */
@Service
public class ConversationService {

    /** 사이드바에 들어갈 제목 길이. 첫 발화를 이 길이로 잘라 쓴다. */
    private static final int TITLE_MAX = 40;

    private final ConversationRepository conversationRepository;
    private final ConversationMessageRepository messageRepository;

    public ConversationService(ConversationRepository conversationRepository,
                              ConversationMessageRepository messageRepository) {
        this.conversationRepository = conversationRepository;
        this.messageRepository = messageRepository;
    }

    @Transactional(readOnly = true)
    public List<ConversationResponse> list(Long userId) {
        return conversationRepository.findByUserIdOrderByUpdatedAtDesc(userId).stream()
                .map(ConversationResponse::from)
                .toList();
    }

    @Transactional(readOnly = true)
    public List<ConversationMessageResponse> messages(Long userId, Long conversationId) {
        getOwned(userId, conversationId);
        return messageRepository.findByConversationIdOrderByIdAsc(conversationId).stream()
                .map(ConversationMessageResponse::from)
                .toList();
    }

    /** 새 대화 생성. 제목은 첫 발화에서 만든다(자료만 보낸 턴이면 기본 제목). */
    @Transactional
    public Conversation create(Long userId, String firstMessage) {
        return conversationRepository.save(Conversation.builder()
                .userId(userId)
                .title(titleOf(firstMessage))
                .build());
    }

    @Transactional(readOnly = true)
    public Conversation getOwned(Long userId, Long conversationId) {
        Conversation conversation = conversationRepository.findById(conversationId)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "CONVERSATION_NOT_FOUND",
                        "대화를 찾을 수 없습니다."));
        if (!conversation.getUserId().equals(userId)) {
            throw new ApiException(HttpStatus.FORBIDDEN, "FORBIDDEN", "이 대화에 대한 권한이 없습니다.");
        }
        return conversation;
    }

    /** 한 턴(사용자 발화 + 답변)을 적재하고 대화의 최근 활동 시각을 올린다. */
    @Transactional
    public void appendTurn(Long conversationId, String userMessage, String reply, List<String> agents) {
        if (userMessage != null && !userMessage.isBlank()) {
            messageRepository.save(ConversationMessage.builder()
                    .conversationId(conversationId)
                    .role(ConversationMessage.Role.USER)
                    .content(userMessage)
                    .build());
        }
        if (reply != null && !reply.isBlank()) {
            messageRepository.save(ConversationMessage.builder()
                    .conversationId(conversationId)
                    .role(ConversationMessage.Role.ASSISTANT)
                    .content(reply)
                    .agents(agents == null || agents.isEmpty() ? null : String.join(",", agents))
                    .build());
        }
        // @UpdateTimestamp 를 태우기 위한 터치 — 목록 정렬(최근 활동 순)이 이 값에 달려 있다.
        conversationRepository.findById(conversationId).ifPresent(c -> c.rename(c.getTitle()));
    }

    @Transactional
    public void delete(Long userId, Long conversationId) {
        getOwned(userId, conversationId);
        messageRepository.deleteAll(messageRepository.findByConversationIdOrderByIdAsc(conversationId));
        conversationRepository.deleteById(conversationId);
    }

    /** 첫 발화 → 제목. 줄바꿈을 접고 길면 자른다. */
    private static String titleOf(String firstMessage) {
        String text = firstMessage == null ? "" : firstMessage.replaceAll("\\s+", " ").trim();
        if (text.isBlank()) {
            return "새 대화";
        }
        return text.length() <= TITLE_MAX ? text : text.substring(0, TITLE_MAX) + "…";
    }
}
