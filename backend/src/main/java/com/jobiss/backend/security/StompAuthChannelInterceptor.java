package com.jobiss.backend.security;

import com.jobiss.backend.repository.AnalysisRunRepository;
import com.jobiss.backend.repository.UserRepository;
import org.springframework.lang.NonNull;
import org.springframework.messaging.Message;
import org.springframework.messaging.MessageChannel;
import org.springframework.messaging.MessagingException;
import org.springframework.messaging.simp.stomp.StompCommand;
import org.springframework.messaging.simp.stomp.StompHeaderAccessor;
import org.springframework.messaging.support.ChannelInterceptor;
import org.springframework.messaging.support.MessageHeaderAccessor;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.authority.AuthorityUtils;
import org.springframework.stereotype.Component;

import java.security.Principal;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * STOMP 실시간 채널 인증/인가 (전화선 2 보안). **fail-closed**: 허용된 목적지만 통과, 나머지는 모두 거부.
 * - CONNECT   : Authorization: Bearer 토큰 검증 → 세션 Principal(userId) 설정. 없거나 틀리면 연결 거부.
 * - SUBSCRIBE : 오직 /topic/analysis/{내가 소유한 id} 만 허용. 그 외(와일드카드 /topic/** 포함) 전부 거부.
 * - SEND      : 오직 /app/agent/{내가 소유한 id}/message 만 허용. /topic 직접 전송 등은 전부 거부.
 * REST와 동일한 사용자 격리를 실시간 채널에도 적용한다.
 */
@Component
public class StompAuthChannelInterceptor implements ChannelInterceptor {

    // analysisId 는 서버 발급 UUID 뿐 → id 세그먼트를 UUID 문자셋으로 못박아 와일드카드/템플릿 문자(* ? { })까지 원천 차단.
    private static final Pattern SUBSCRIBE_DEST = Pattern.compile("^/topic/analysis/([0-9a-fA-F-]+)$");
    private static final Pattern SEND_DEST = Pattern.compile("^/app/agent/([0-9a-fA-F-]+)/message$");

    private final JwtTokenProvider tokenProvider;
    private final AnalysisRunRepository runRepository;
    private final UserRepository userRepository;

    public StompAuthChannelInterceptor(JwtTokenProvider tokenProvider, AnalysisRunRepository runRepository,
                                       UserRepository userRepository) {
        this.tokenProvider = tokenProvider;
        this.runRepository = runRepository;
        this.userRepository = userRepository;
    }

    @Override
    public Message<?> preSend(@NonNull Message<?> message, @NonNull MessageChannel channel) {
        StompHeaderAccessor accessor = MessageHeaderAccessor.getAccessor(message, StompHeaderAccessor.class);
        if (accessor == null || accessor.getCommand() == null) {
            return message;   // 하트비트 등 STOMP 프레임이 아닌 것은 통과
        }

        StompCommand command = accessor.getCommand();
        if (StompCommand.CONNECT.equals(command)) {
            Long userId = resolveUserId(accessor.getFirstNativeHeader("Authorization"));
            if (userId == null) {
                throw new MessagingException("실시간 연결 인증 실패(토큰 없음/만료)");
            }
            accessor.setUser(UsernamePasswordAuthenticationToken.authenticated(userId, null, AuthorityUtils.NO_AUTHORITIES));
        } else if (StompCommand.SUBSCRIBE.equals(command)) {
            authorizeAnalysisDestination(accessor, SUBSCRIBE_DEST, "구독");
        } else if (StompCommand.SEND.equals(command)) {
            authorizeAnalysisDestination(accessor, SEND_DEST, "전송");
        }
        return message;
    }

    /**
     * 토큰 → userId. 서명이 맞아도 **그 사용자가 실제로 있어야** 통과시킨다.
     * 계정이 사라진 토큰으로 실시간 채널을 열면, 연결은 되지만 이후 동작이 알 수 없는 이유로
     * 실패한다(HTTP 필터와 같은 이유로 존재 확인을 넣는다).
     */
    private Long resolveUserId(String authorizationHeader) {
        if (authorizationHeader == null || !authorizationHeader.startsWith("Bearer ")) {
            return null;
        }
        Long userId = tokenProvider.parseUserId(authorizationHeader.substring(7));
        if (userId == null || !userRepository.existsById(userId)) {
            return null;
        }
        return userId;
    }

    /**
     * fail-closed 인가: destination 이 정확히 허용 패턴이어야 하고, 그 분석의 소유자여야 한다.
     * 패턴에 안 맞는 목적지(와일드카드·/topic 직접 전송·다중 세그먼트 등)는 즉시 거부.
     */
    private void authorizeAnalysisDestination(StompHeaderAccessor accessor, Pattern allowed, String action) {
        String destination = accessor.getDestination();
        Matcher m = (destination == null) ? null : allowed.matcher(destination);
        if (m == null || !m.matches()) {
            throw new MessagingException("허용되지 않은 " + action + " 경로입니다: " + destination);
        }
        String analysisId = m.group(1);
        Long userId = currentUserId(accessor);
        if (userId == null) {
            throw new MessagingException("실시간 채널 인증이 필요합니다");
        }
        Long ownerId = runRepository.findOwnerIdByAnalysisId(analysisId).orElse(null);
        if (ownerId == null || !ownerId.equals(userId)) {
            throw new MessagingException("이 분석에 접근할 권한이 없습니다");
        }
    }

    private Long currentUserId(StompHeaderAccessor accessor) {
        Principal user = accessor.getUser();
        if (user instanceof Authentication auth && auth.getPrincipal() instanceof Long id) {
            return id;
        }
        return null;
    }
}
