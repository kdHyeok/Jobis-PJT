package com.jobiss.notification;

import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.format.annotation.DateTimeFormat;

import java.time.OffsetDateTime;
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
            @RequestParam(defaultValue = "30") int limit,
            @RequestParam(defaultValue = "ALL") String category,
            @RequestParam(required = false)
            @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME)
            OffsetDateTime beforeCreatedAt,
            @RequestParam(required = false) UUID beforeId
    ) {
        return service.list(userId, unreadOnly, category, limit, beforeCreatedAt, beforeId);
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

    @DeleteMapping("/{notificationId}")
    ResponseEntity<Void> delete(
            @AuthenticationPrincipal UUID userId,
            @PathVariable UUID notificationId
    ) {
        service.delete(userId, notificationId);
        return ResponseEntity.noContent().build();
    }

    @DeleteMapping("/read")
    ResponseEntity<Void> deleteRead(@AuthenticationPrincipal UUID userId) {
        service.deleteRead(userId);
        return ResponseEntity.noContent().build();
    }
}
