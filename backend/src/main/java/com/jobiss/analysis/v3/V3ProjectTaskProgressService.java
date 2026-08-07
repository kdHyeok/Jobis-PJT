package com.jobiss.analysis.v3;

import com.jobiss.common.ApiException;
import com.jobiss.db.RlsTransactionExecutor;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@Service
public class V3ProjectTaskProgressService {

    private final RlsTransactionExecutor rls;
    private final ObjectMapper objectMapper;

    public V3ProjectTaskProgressService(RlsTransactionExecutor rls, ObjectMapper objectMapper) {
        this.rls = rls;
        this.objectMapper = objectMapper;
    }

    void synchronize(JdbcClient jdbc, UUID userId, JsonNode snapshot) {
        if (snapshot == null || !snapshot.path("nodes").isArray()) return;
        for (JsonNode project : snapshot.path("nodes")) {
            if (!"TARGET_PROJECT".equals(project.path("nodeKind").stringValue(""))) continue;
            String projectKey = V3ProjectProgressService.projectKey(project);
            UUID projectNodeId = jdbc.sql("""
                            select id from career_nodes
                            where canonical_key = :projectKey and kind = 'PROJECT' and archived_at is null
                            """)
                    .param("projectKey", projectKey)
                    .query(UUID.class)
                    .optional()
                    .orElse(null);
            if (projectNodeId == null) continue;

            List<String> activeKeys = new ArrayList<>();
            int order = 0;
            for (JsonNode task : project.path("projectSpec").path("tasks")) {
                String taskKey = task.path("taskKey").stringValue("");
                if (taskKey.isBlank()) continue;
                activeKeys.add(taskKey);
                String revision = sha256(objectMapper.writeValueAsString(task));
                jdbc.sql("""
                                insert into user_project_task_progress (
                                    user_id, project_node_id, task_key, task_order, necessity,
                                    title, objective, acceptance_criteria, capability_keys,
                                    depends_on_task_keys, task_revision_hash
                                ) values (
                                    :userId, :projectNodeId, :taskKey, :taskOrder, :necessity,
                                    :title, :objective, cast(:criteria as jsonb), cast(:capabilities as jsonb),
                                    cast(:dependencies as jsonb), :revision
                                )
                                on conflict (user_id, project_node_id, task_key) do update set
                                    task_order = excluded.task_order,
                                    necessity = excluded.necessity,
                                    title = excluded.title,
                                    objective = excluded.objective,
                                    acceptance_criteria = excluded.acceptance_criteria,
                                    capability_keys = excluded.capability_keys,
                                    depends_on_task_keys = excluded.depends_on_task_keys,
                                    progress_state = case
                                        when user_project_task_progress.task_revision_hash = excluded.task_revision_hash
                                            then user_project_task_progress.progress_state
                                        else 'NOT_STARTED'
                                    end,
                                    task_revision_hash = excluded.task_revision_hash,
                                    archived_at = null,
                                    updated_at = now()
                                """)
                        .param("userId", userId)
                        .param("projectNodeId", projectNodeId)
                        .param("taskKey", taskKey)
                        .param("taskOrder", order++)
                        .param("necessity", task.path("necessity").stringValue("REQUIRED"))
                        .param("title", clip(task.path("title").stringValue("프로젝트 과제"), 240))
                        .param("objective", task.path("objective").stringValue(""))
                        .param("criteria", objectMapper.writeValueAsString(task.path("acceptanceCriteria")))
                        .param("capabilities", objectMapper.writeValueAsString(task.path("capabilityKeys")))
                        .param("dependencies", objectMapper.writeValueAsString(task.path("dependsOnTaskKeys")))
                        .param("revision", revision)
                        .update();
            }
            jdbc.sql("""
                            update user_project_task_progress
                            set archived_at = now(), updated_at = now()
                            where project_node_id = :projectNodeId
                              and archived_at is null
                              and not (task_key = any(cast(:activeKeys as varchar[])))
                            """)
                    .param("projectNodeId", projectNodeId)
                    .param("activeKeys", activeKeys.toArray(String[]::new))
                    .update();
        }
    }

    JsonNode overlay(JdbcClient jdbc, JsonNode snapshot) {
        if (snapshot == null || !snapshot.isObject()) return snapshot;
        Map<String, TaskState> states = new HashMap<>();
        jdbc.sql("""
                        select node.canonical_key, task.task_key, task.progress_state,
                               count(evidence.id) as evidence_count
                        from user_project_task_progress task
                        join career_nodes node on node.id = task.project_node_id
                        left join user_project_task_evidence evidence
                          on evidence.task_progress_id = task.id
                         and evidence.verification_state <> 'REJECTED'
                        where task.archived_at is null and node.archived_at is null
                        group by node.canonical_key, task.task_key, task.progress_state
                        """)
                .query((rs, rowNum) -> Map.entry(
                        rs.getString("canonical_key") + "\n" + rs.getString("task_key"),
                        new TaskState(rs.getString("progress_state"), rs.getInt("evidence_count"))
                ))
                .list()
                .forEach(entry -> states.put(entry.getKey(), entry.getValue()));
        ObjectNode result = ((ObjectNode) snapshot).deepCopy();
        for (JsonNode project : result.path("nodes")) {
            if (!(project instanceof ObjectNode projectNode)
                    || !"TARGET_PROJECT".equals(project.path("nodeKind").stringValue(""))) continue;
            String projectKey = V3ProjectProgressService.projectKey(project);
            for (JsonNode task : project.path("projectSpec").path("tasks")) {
                if (!(task instanceof ObjectNode taskNode)) continue;
                TaskState state = states.get(projectKey + "\n" + task.path("taskKey").stringValue(""));
                if (state == null) continue;
                taskNode.put("progressState", state.progressState());
                taskNode.put("evidenceCount", state.evidenceCount());
            }
        }
        return result;
    }

    public List<TaskView> tasks(UUID userId, UUID projectNodeId) {
        return rls.read(userId, jdbc -> list(jdbc, projectNodeId));
    }

    public TaskView updateState(UUID userId, UUID projectNodeId, String taskKey, String state) {
        if (!List.of("NOT_STARTED", "CLAIMED").contains(state)) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "PROJECT_TASK_STATE_INVALID",
                    "과제는 시작 전 또는 진행 중 상태로만 직접 변경할 수 있습니다.");
        }
        return rls.write(userId, jdbc -> {
            int updated = jdbc.sql("""
                            update user_project_task_progress
                            set progress_state = :state, updated_at = now()
                            where project_node_id = :projectNodeId and task_key = :taskKey and archived_at is null
                            """)
                    .param("state", state)
                    .param("projectNodeId", projectNodeId)
                    .param("taskKey", taskKey)
                    .update();
            if (updated != 1) throw notFound();
            return one(jdbc, projectNodeId, taskKey);
        });
    }

    public TaskView addEvidence(
            UUID userId,
            UUID projectNodeId,
            String taskKey,
            String title,
            String evidenceUrl,
            String description
    ) {
        return rls.write(userId, jdbc -> {
            UUID taskId = jdbc.sql("""
                            select id from user_project_task_progress
                            where project_node_id = :projectNodeId and task_key = :taskKey and archived_at is null
                            """)
                    .param("projectNodeId", projectNodeId)
                    .param("taskKey", taskKey)
                    .query(UUID.class)
                    .optional()
                    .orElseThrow(V3ProjectTaskProgressService::notFound);
            jdbc.sql("""
                            insert into user_project_task_evidence (
                                user_id, task_progress_id, title, evidence_url, description
                            ) values (:userId, :taskId, :title, :evidenceUrl, :description)
                            """)
                    .param("userId", userId)
                    .param("taskId", taskId)
                    .param("title", clip(title, 240))
                    .param("evidenceUrl", evidenceUrl)
                    .param("description", description)
                    .update();
            jdbc.sql("""
                            update user_project_task_progress
                            set progress_state = 'EVIDENCED', updated_at = now()
                            where id = :taskId
                            """)
                    .param("taskId", taskId)
                    .update();
            return one(jdbc, projectNodeId, taskKey);
        });
    }

    private List<TaskView> list(JdbcClient jdbc, UUID projectNodeId) {
        return jdbc.sql("""
                        select task.id, task.project_node_id, task.task_key, task.task_order,
                               task.necessity, task.title, task.objective,
                               task.acceptance_criteria::text, task.capability_keys::text,
                               task.depends_on_task_keys::text, task.progress_state,
                               count(evidence.id) as evidence_count
                        from user_project_task_progress task
                        left join user_project_task_evidence evidence
                          on evidence.task_progress_id = task.id
                         and evidence.verification_state <> 'REJECTED'
                        where task.project_node_id = :projectNodeId and task.archived_at is null
                        group by task.id
                        order by task.task_order, task.task_key
                        """)
                .param("projectNodeId", projectNodeId)
                .query((rs, rowNum) -> new TaskView(
                        rs.getObject("id", UUID.class),
                        rs.getObject("project_node_id", UUID.class),
                        rs.getString("task_key"),
                        rs.getInt("task_order"),
                        rs.getString("necessity"),
                        rs.getString("title"),
                        rs.getString("objective"),
                        objectMapper.readTree(rs.getString("acceptance_criteria")),
                        objectMapper.readTree(rs.getString("capability_keys")),
                        objectMapper.readTree(rs.getString("depends_on_task_keys")),
                        rs.getString("progress_state"),
                        rs.getInt("evidence_count")
                ))
                .list();
    }

    private TaskView one(JdbcClient jdbc, UUID projectNodeId, String taskKey) {
        return list(jdbc, projectNodeId).stream()
                .filter(item -> item.taskKey().equals(taskKey))
                .findFirst()
                .orElseThrow(V3ProjectTaskProgressService::notFound);
    }

    private static ApiException notFound() {
        return new ApiException(HttpStatus.NOT_FOUND, "PROJECT_TASK_NOT_FOUND", "프로젝트 과제를 찾을 수 없습니다.");
    }

    private static String sha256(String value) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is unavailable", exception);
        }
    }

    private static String clip(String value, int maximum) {
        if (value == null) return "";
        return value.length() <= maximum ? value : value.substring(0, maximum);
    }

    private record TaskState(String progressState, int evidenceCount) {}

    public record TaskView(
            UUID id,
            UUID projectNodeId,
            String taskKey,
            int taskOrder,
            String necessity,
            String title,
            String objective,
            JsonNode acceptanceCriteria,
            JsonNode capabilityKeys,
            JsonNode dependsOnTaskKeys,
            String progressState,
            int evidenceCount
    ) {}
}
