package com.jobiss.backend.config;

import com.jobiss.backend.security.StompAuthChannelInterceptor;
import org.springframework.context.annotation.Configuration;
import org.springframework.messaging.simp.config.ChannelRegistration;
import org.springframework.messaging.simp.config.MessageBrokerRegistry;
import org.springframework.web.socket.config.annotation.EnableWebSocketMessageBroker;
import org.springframework.web.socket.config.annotation.StompEndpointRegistry;
import org.springframework.web.socket.config.annotation.WebSocketMessageBrokerConfigurer;

/**
 * 브라우저 ↔ 백엔드 실시간 통신 (전화선 2). STOMP over WebSocket.
 * - 브라우저 접속 지점: /ws
 * - 서버→브라우저 브로드캐스트(구독): /topic/**   (예: /topic/analysis/{analysisId})
 * - 브라우저→서버 메시지: /app/**                (예: /app/agent/{analysisId}/message)
 * 인바운드 채널에 인증/인가 인터셉터를 걸어 REST와 동일한 사용자 격리를 적용한다.
 */
@Configuration
@EnableWebSocketMessageBroker
public class WebSocketConfig implements WebSocketMessageBrokerConfigurer {

    private final StompAuthChannelInterceptor authInterceptor;

    public WebSocketConfig(StompAuthChannelInterceptor authInterceptor) {
        this.authInterceptor = authInterceptor;
    }

    @Override
    public void registerStompEndpoints(StompEndpointRegistry registry) {
        registry.addEndpoint("/ws").setAllowedOriginPatterns("*");   // 개발용: 모든 오리진 허용
    }

    @Override
    public void configureMessageBroker(MessageBrokerRegistry registry) {
        registry.enableSimpleBroker("/topic");               // 구독 기반 브로드캐스트
        registry.setApplicationDestinationPrefixes("/app");  // 클라이언트가 서버로 보낼 때
    }

    @Override
    public void configureClientInboundChannel(ChannelRegistration registration) {
        registration.interceptors(authInterceptor);          // CONNECT 인증 + SUBSCRIBE/SEND 소유권 검증
    }
}
