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

    public NotificationPage list(
            UUID userId,
            boolean unreadOnly,
            String category,
            int limit,
            OffsetDateTime beforeCreatedAt,
            UUID beforeId
    ) {
        int safeLimit = Math.max(1, Math.min(limit, 100));
        String normalizedCategory = switch (category == null ? "ALL" : category.trim().toUpperCase()) {
            case "ANALYSIS", "CAREER", "ROADMAP", "VERIFICATION", "CHAT" ->
                    category.trim().toUpperCase();
            default -> "ALL";
        };
        return rls.read(userId, jdbc -> {
            String cursorClause = beforeCreatedAt != null && beforeId != null
                    ? "and (created_at, id) < (:beforeCreatedAt, :beforeId)"
                    : "";
            var statement = jdbc.sql("""
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
                              and (
                                  :category = 'ALL'
                                  or (:category = 'ANALYSIS' and notification_type like 'ANALYSIS%%')
                                  or (:category = 'CAREER' and notification_type like 'CAREER_SOURCE%%')
                                  or (:category = 'ROADMAP' and (
                                      notification_type like 'ROADMAP%%'
                                      or notification_type like 'CAREER_MAP%%'
                                  ))
                                  or (:category = 'VERIFICATION' and (
                                      notification_type like 'EVIDENCE%%'
                                      or notification_type like 'COMPETENCY%%'
                                      or notification_type like 'ASSESSMENT%%'
                                  ))
                                  or (:category = 'CHAT' and notification_type like 'CHAT%%')
                              )
                            %s
                            order by created_at desc, id desc
                            limit :limit
                            """.formatted(cursorClause))
                    .param("unreadOnly", unreadOnly)
                    .param("category", normalizedCategory)
                    .param("limit", safeLimit + 1);
            if (!cursorClause.isBlank()) {
                statement = statement
                        .param("beforeCreatedAt", beforeCreatedAt)
                        .param("beforeId", beforeId);
            }
            List<NotificationView> rows = statement
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
            boolean hasMore = rows.size() > safeLimit;
            List<NotificationView> items = hasMore ? rows.subList(0, safeLimit) : rows;
            long unreadCount = jdbc.sql("""
                            select count(*) from notifications where read_at is null
                            """)
                    .query(Long.class)
                    .single();
            return new NotificationPage(items, unreadCount, hasMore);
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

    public void delete(UUID userId, UUID notificationId) {
        rls.write(userId, jdbc -> {
            int deleted = jdbc.sql("delete from notifications where id = :notificationId")
                    .param("notificationId", notificationId)
                    .update();
            if (deleted == 0) {
                throw new ApiException(
                        HttpStatus.NOT_FOUND,
                        "NOTIFICATION_NOT_FOUND",
                        "삭제할 알림을 찾을 수 없습니다."
                );
            }
            return null;
        });
    }

    public void deleteRead(UUID userId) {
        rls.write(userId, jdbc -> {
            jdbc.sql("delete from notifications where read_at is not null").update();
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
            long unreadCount,
            boolean hasMore
    ) {
    }
}
