package com.jobiss.notification;

import com.jobiss.common.ApiException;
import com.jobiss.db.RlsTransactionExecutor;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

@Service
public class NotificationService {

    private final RlsTransactionExecutor rls;
    private final ObjectMapper objectMapper;

    public NotificationService(RlsTransactionExecutor rls, ObjectMapper objectMapper) {
        this.rls = rls;
        this.objectMapper = objectMapper;
    }

    public NotificationPage list(UUID userId, boolean unreadOnly, int limit) {
        int safeLimit = Math.max(1, Math.min(limit, 100));
        return rls.read(userId, jdbc -> {
            List<NotificationView> items = jdbc.sql("""
                            select
                                id,
                                notification_type,
                                title,
                                body,
                                payload::text,
                                read_at,
                                created_at
                            from notifications
                            where (not :unreadOnly or read_at is null)
                            order by created_at desc
                            limit :limit
                            """)
                    .param("unreadOnly", unreadOnly)
                    .param("limit", safeLimit)
                    .query((rs, rowNum) -> new NotificationView(
                            rs.getObject("id", UUID.class),
                            rs.getString("notification_type"),
                            rs.getString("title"),
                            rs.getString("body"),
                            readJson(rs.getString("payload")),
                            rs.getObject("read_at", OffsetDateTime.class),
                            rs.getObject("created_at", OffsetDateTime.class)
                    ))
                    .list();
            long unreadCount = jdbc.sql("""
                            select count(*) from notifications where read_at is null
                            """)
                    .query(Long.class)
                    .single();
            return new NotificationPage(items, unreadCount);
        });
    }

    public void markRead(UUID userId, UUID notificationId) {
        rls.write(userId, jdbc -> {
            int updated = jdbc.sql("""
                            update notifications
                            set read_at = coalesce(read_at, now())
                            where id = :notificationId
                            """)
                    .param("notificationId", notificationId)
                    .update();
            if (updated == 0) {
                throw new ApiException(
                        HttpStatus.NOT_FOUND,
                        "NOTIFICATION_NOT_FOUND",
                        "알림을 찾을 수 없습니다."
                );
            }
            return null;
        });
    }

    public void markAllRead(UUID userId) {
        rls.write(userId, jdbc -> {
            jdbc.sql("update notifications set read_at = now() where read_at is null")
                    .update();
            return null;
        });
    }

    private JsonNode readJson(String value) {
        return value == null ? objectMapper.createObjectNode() : objectMapper.readTree(value);
    }

    public record NotificationView(
            UUID id,
            String type,
            String title,
            String body,
            JsonNode payload,
            OffsetDateTime readAt,
            OffsetDateTime createdAt
    ) {
    }

    public record NotificationPage(
            List<NotificationView> items,
            long unreadCount
    ) {
    }
}
