package com.jobiss.backend.service;

import com.jobiss.backend.domain.AnalysisRun;
import com.jobiss.backend.domain.Conversation;
import com.jobiss.backend.domain.ConversationMessage;
import com.jobiss.backend.domain.MessageRole;
import com.jobiss.backend.domain.User;
import com.jobiss.backend.dto.conversation.ConversationDtos;
import com.jobiss.backend.exception.ApiException;
import com.jobiss.backend.repository.AnalysisRunRepository;
import com.jobiss.backend.repository.ConversationMessageRepository;
import com.jobiss.backend.repository.ConversationRepository;
import com.jobiss.backend.repository.EvidenceRepository;
import com.jobiss.backend.repository.UserRepository;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * 대화 스레드. 목록의 단위이고, 분석은 이 안에서 일어나는 사건이다.
 * <p>
 * 대화를 저장하는 이유는 기록이 아까워서가 아니라, 거기서 나온 사실이 다음 단계로 이어져야 하기
 * 때문이다. 그래서 분석은 대화를 떠나지 않고 role=ANALYSIS 메시지로 같은 스레드에 붙는다.
 */
@Service
public class ConversationService {

    /** 한 사용자가 만들 수 있는 대화 수 상한(무한 증식 방지). */
    private static final int MAX_PER_USER = 200;

    private final ConversationRepository conversationRepository;
    private final ConversationMessageRepository messageRepository;
    private final AnalysisRunRepository runRepository;
    private final EvidenceRepository evidenceRepository;
    private final UserRepository userRepository;
    private final ConversationAiClient ai;

    public ConversationService(ConversationRepository conversationRepository,
                               ConversationMessageRepository messageRepository,
                               AnalysisRunRepository runRepository,
                               EvidenceRepository evidenceRepository,
                               UserRepository userRepository,
                               ConversationAiClient ai) {
        this.conversationRepository = conversationRepository;
        this.messageRepository = messageRepository;
        this.runRepository = runRepository;
        this.evidenceRepository = evidenceRepository;
        this.userRepository = userRepository;
        this.ai = ai;
    }

    /* ------------------------------------------------------------------ 목록 */

    /** 사이드바 목록. 대화 안에서 분석이 돌았으면 그 상태를 함께 얹는다. */
    @Transactional(readOnly = true)
    public List<ConversationDtos.Summary> list(Long userId) {
        List<Conversation> conversations = conversationRepository.findByUserIdOrderByUpdatedAtDesc(userId);
        if (conversations.isEmpty()) return List.of();

        // 대화별 "마지막 분석" 한 건만 매핑 (조회는 최신순이라 먼저 담긴 것이 마지막 분석)
        List<Long> ids = conversations.stream().map(Conversation::getId).toList();
        Map<Long, AnalysisRun> lastRun = new HashMap<>();
        for (AnalysisRun run : runRepository.findByConversationIds(ids)) {
            lastRun.putIfAbsent(run.getConversation().getId(), run);
        }

        List<ConversationDtos.Summary> out = new ArrayList<>(conversations.size());
        for (Conversation c : conversations) {
            AnalysisRun run = lastRun.get(c.getId());
            out.add(new ConversationDtos.Summary(
                    c.getConversationId(), c.getTitle(), c.getUpdatedAt(),
                    run == null ? null : run.getAnalysisId(),
                    run == null ? null : run.getStatus().name()));
        }
        return out;
    }

    /* ------------------------------------------------------------------ 열기 */

    @Transactional(readOnly = true)
    public ConversationDtos.Detail get(Long userId, String conversationId) {
        Conversation c = findOwned(userId, conversationId);
        return ConversationDtos.Detail.of(c, messageRepository.findByConversationIdOrderBySeqAsc(c.getId()));
    }

    /* ------------------------------------------------------------------ 만들기 */

    @Transactional
    public ConversationDtos.Summary create(Long userId, String title) {
        if (conversationRepository.countByUserId(userId) >= MAX_PER_USER) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "TOO_MANY_CONVERSATIONS",
                    "대화가 너무 많아요. 오래된 대화를 정리한 뒤 다시 시도해 주세요.");
        }
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "USER_NOT_FOUND", "사용자를 찾을 수 없습니다."));
        Conversation c = conversationRepository.save(Conversation.builder()
                .conversationId(UUID.randomUUID().toString())
                .user(user)
                .title(title == null || title.isBlank() ? "새 대화" : title)
                .build());
        return new ConversationDtos.Summary(c.getConversationId(), c.getTitle(), c.getUpdatedAt(), null, null);
    }

    /* ------------------------------------------------------------------ 보내기 */

    /**
     * 한마디 보내기 — 사용자 발화 저장 → AI 응답 → 응답 저장.
     * 대화가 없으면(conversationId == null) 새로 만들고, 첫 발화로 제목을 정한다.
     */
    @Transactional
    public ConversationDtos.SendResponse send(Long userId, String conversationId, String text) {
        if (text == null || text.isBlank()) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "EMPTY_INPUT", "내용을 입력해 주세요.");
        }
        Conversation c = (conversationId == null || conversationId.isBlank())
                ? newConversation(userId, text)
                : findOwned(userId, conversationId);

        // 첫 발화면 제목을 그 문장으로 (ChatGPT 와 같은 방식)
        List<ConversationMessage> history = messageRepository.findByConversationIdOrderBySeqAsc(c.getId());
        if (history.isEmpty()) c.rename(text);

        append(c, MessageRole.USER, text, null);

        Map<String, Object> answer = ai.chat(toAiMessages(history, text),
                (int) evidenceRepository.countByUserId(userId));
        String reply = String.valueOf(answer.getOrDefault("reply", ""));
        append(c, MessageRole.ASSISTANT, reply, null);

        return new ConversationDtos.SendResponse(
                c.getConversationId(), c.getTitle(), reply,
                String.valueOf(answer.getOrDefault("action", "NONE")),
                String.valueOf(answer.getOrDefault("actionLabel", "")));
    }

    /* ------------------------------------------------------------------ 분석 연결 */

    /**
     * 분석이 시작될 때 그 대화에 카드 한 줄을 남긴다.
     * 대화 밖(새 분석 화면)에서 시작했으면 대화를 새로 만들어 그 안에 담는다 — 목록의 단위는 항상 대화다.
     */
    @Transactional
    public Conversation attachAnalysis(Long userId, String conversationId, String analysisId, String fallbackTitle) {
        Conversation c = (conversationId == null || conversationId.isBlank())
                ? newConversation(userId, fallbackTitle)
                : findOwned(userId, conversationId);
        append(c, MessageRole.ANALYSIS, null, analysisId);
        return c;
    }

    /* ------------------------------------------------------------------ 삭제 */

    @Transactional
    public void delete(Long userId, String conversationId) {
        Conversation c = findOwned(userId, conversationId);
        // 안에서 돌던 분석은 대화와의 연결만 끊는다 — 분석 자체는 별도 삭제 흐름(소유·연쇄 규칙)이 있다.
        for (AnalysisRun run : runRepository.findByConversationIds(List.of(c.getId()))) {
            run.detachConversation();
        }
        messageRepository.deleteByConversationId(c.getId());
        conversationRepository.delete(c);
    }

    /* ------------------------------------------------------------------ 내부 */

    private Conversation newConversation(Long userId, String title) {
        ConversationDtos.Summary created = create(userId, title);
        return conversationRepository.findByConversationId(created.conversationId())
                .orElseThrow(() -> new ApiException(HttpStatus.INTERNAL_SERVER_ERROR, "CONVERSATION_CREATE_FAILED",
                        "대화를 만들지 못했어요."));
    }

    private Conversation findOwned(Long userId, String conversationId) {
        Conversation c = conversationRepository.findByConversationId(conversationId)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "CONVERSATION_NOT_FOUND",
                        "대화를 찾을 수 없습니다."));
        if (!c.getUser().getId().equals(userId)) {
            throw new ApiException(HttpStatus.FORBIDDEN, "FORBIDDEN", "이 대화에 대한 권한이 없습니다.");
        }
        return c;
    }

    private void append(Conversation c, MessageRole role, String content, String analysisId) {
        messageRepository.save(ConversationMessage.builder()
                .conversation(c)
                .seq(messageRepository.maxSeq(c.getId()) + 1)
                .role(role)
                .content(content)
                .analysisId(analysisId)
                .build());
        c.touch();   // 목록 정렬이 "최근 활동" 순이 되도록
    }

    /** 저장된 기록 + 방금 발화를 AI 계약 형태로. 분석 카드는 말이 아니므로 뺀다. */
    private static List<Map<String, String>> toAiMessages(List<ConversationMessage> history, String justSaid) {
        List<Map<String, String>> out = new ArrayList<>();
        for (ConversationMessage m : history) {
            if (m.getRole() == MessageRole.ANALYSIS || m.getContent() == null) continue;
            Map<String, String> one = new LinkedHashMap<>();
            one.put("role", m.getRole() == MessageRole.USER ? "user" : "assistant");
            one.put("content", m.getContent());
            out.add(one);
        }
        Map<String, String> last = new LinkedHashMap<>();
        last.put("role", "user");
        last.put("content", justSaid);
        out.add(last);
        return out;
    }
}
