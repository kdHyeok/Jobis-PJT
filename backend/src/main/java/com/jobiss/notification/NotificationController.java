package com.jobiss.notification;

import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.UUID;

@RestController
@RequestMapping("/api/notifications")
public class NotificationController {

    private final NotificationService service;

    public NotificationController(NotificationService service) {
        this.service = service;
    }

    @GetMapping
    NotificationService.NotificationPage list(
            @AuthenticationPrincipal UUID userId,
            @RequestParam(defaultValue = "false") boolean unreadOnly,
            @RequestParam(defaultValue = "30") int limit
    ) {
        return service.list(userId, unreadOnly, limit);
    }

    @PostMapping("/{notificationId}/read")
    ResponseEntity<Void> markRead(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID notificationId
    ) {
        service.markRead(userId, notificationId);
        return ResponseEntity.noContent().build();
    }

    @PostMapping("/read-all")
    ResponseEntity<Void> markAllRead(@AuthenticationPrincipal UUID userId) {
        service.markAllRead(userId);
        return ResponseEntity.noContent().build();
    }
}
