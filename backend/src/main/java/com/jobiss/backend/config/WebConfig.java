package com.jobiss.backend.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.ResourceHandlerRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * 프론트를 /chat-app/ 로도 서빙(옛 주소 호환). 실제 파일은 classpath:/static/ 에 번들되어 있다.
 * → 브라우저와 백엔드가 동일 오리진(localhost:8080)이라 CORS 문제가 없다.
 *   접속: http://localhost:8080/login.html (또는 /chat-app/chat.html)
 */
@Configuration
public class WebConfig implements WebMvcConfigurer {

    @Override
    public void addResourceHandlers(ResourceHandlerRegistry registry) {
        registry.addResourceHandler("/chat-app/**")
                .addResourceLocations("classpath:/static/");
    }
}
