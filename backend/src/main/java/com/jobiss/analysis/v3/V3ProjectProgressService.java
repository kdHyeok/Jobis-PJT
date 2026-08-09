package com.jobiss.analysis.v3;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

@Component
public class V3ProjectProgressService {

    private final ObjectMapper objectMapper;
    private final V3ProjectTaskProgressService taskProgressService;

    public V3ProjectProgressService(
            ObjectMapper objectMapper,
            V3ProjectTaskProgressService taskProgressService
    ) {
        this.objectMapper = objectMapper;
        this.taskProgressService = taskProgressService;
    }

    public JsonNode synchronizeAndOverlay(JdbcClient jdbc, UUID userId, JsonNode snapshot) {
        synchronize(jdbc, userId, snapshot);
        taskProgressService.synchronize(jdbc, userId, snapshot);
        return overlay(jdbc, snapshot);
    }

    public JsonNode overlay(JdbcClient jdbc, JsonNode snapshot) {
        if (snapshot == null || !snapshot.isObject()) return snapshot;
        Map<String, ProjectState> states = new HashMap<>();
        jdbc.sql("""
                        select node.canonical_key,
                               node.id,
                               progress.status::text,
                               exists(select 1 from evidence e where e.node_id = node.id) as has_evidence
                        from career_nodes node
                        join node_progress progress on progress.node_id = node.id
                        where node.kind = 'PROJECT'
                          and node.canonical_key like 'v3.project:%'
                          and node.archived_at is null
                        """)
                .query((rs, rowNum) -> Map.entry(
                        rs.getString("canonical_key"),
                        new ProjectState(
                                rs.getObject("id", UUID.class),
                                rs.getString("status"),
                                rs.getBoolean("has_evidence")
                        )
                ))
                .list()
                .forEach(entry -> states.put(entry.getKey(), entry.getValue()));

        Map<String, String> capabilities = new HashMap<>();
        jdbc.sql("select canonical_key, progress_state from user_atomic_capabilities")
                .query((rs, rowNum) -> Map.entry(
                        rs.getString("canonical_key"), rs.getString("progress_state")
                ))
                .list()
                .forEach(entry -> capabilities.put(entry.getKey(), entry.getValue()));

        ObjectNode result = ((ObjectNode) snapshot).deepCopy();
        for (JsonNode item : result.path("nodes")) {
            if (!(item instanceof ObjectNode node)
                    || !"TARGET_PROJECT".equals(node.path("nodeKind").stringValue(""))) {
                continue;
            }
            String key = projectKey(node);
            ProjectState state = states.get(key);
            if (state == null) continue;
            node.put("careerNodeId", state.nodeId().toString());
            boolean requiredVerified = true;
            for (JsonNode required : node.path("projectSpec").path("requiredCapabilityKeys")) {
                if (!"VERIFIED".equals(capabilities.get(required.stringValue("")))) {
                    requiredVerified = false;
                    break;
                }
            }
            if (requiredVerified && "COMPLETED".equals(state.progressStatus())) {
                node.put("progressState", "VERIFIED");
            } else if (state.hasEvidence()) {
                node.put("progressState", "EVIDENCED");
            } else if (requiredVerified) {
                node.put("progressState", "CLAIMED");
            } else {
                node.put("progressState", "NOT_STARTED");
            }
        }
        return taskProgressService.overlay(jdbc, result);
    }

    /**
     * Removes backend-only runtime fields before a roadmap snapshot crosses the
     * AI contract boundary or is stored as a canonical roadmap version.
     *
     * <p>{@code careerNodeId} is only used by the service UI to address the
     * legacy {@code career_nodes} row. AI v3 identifies roadmap nodes with
     * {@code nodeId}/{@code targetRef} and consumes the already overlaid
     * {@code progressState}, so exposing the database UUID would couple the
     * contract to local persistence details. Project-task progress and atomic
     * assessment availability are service projections as well: they belong in
     * the UI response, not in the immutable AI planning contract.</p>
     */
    public JsonNode withoutInternalLinkage(JsonNode snapshot) {
        if (snapshot == null || !snapshot.isObject()) return snapshot;
        ObjectNode result = ((ObjectNode) snapshot).deepCopy();
        for (JsonNode item : result.path("nodes")) {
            if (item instanceof ObjectNode node) {
                node.remove("careerNodeId");
                node.remove("atomicAssessmentAvailable");
                for (JsonNode task : node.path("projectSpec").path("tasks")) {
                    if (task instanceof ObjectNode taskNode) {
                        taskNode.remove("progressState");
                        taskNode.remove("evidenceCount");
                    }
                }
            }
        }
        return result;
    }

    private void synchronize(JdbcClient jdbc, UUID userId, JsonNode snapshot) {
        if (snapshot == null || !snapshot.path("nodes").isArray()) return;
        UUID graphId = jdbc.sql("select id from career_graphs where user_id = :userId")
                .param("userId", userId)
                .query(UUID.class)
                .single();
        for (JsonNode node : snapshot.path("nodes")) {
            if (!"TARGET_PROJECT".equals(node.path("nodeKind").stringValue(""))) continue;
            String canonicalKey = projectKey(node);
            JsonNode spec = node.path("projectSpec");
            String detail = objectMapper.writeValueAsString(spec);
            String title = clip(node.path("title").stringValue("회사 맞춤 프로젝트"), 160);
            String domain = clip(node.path("sectionKey").stringValue("COMMON"), 40);
            String scope = projectScope(spec);
            UUID postingId = postingId(node.path("targetRef").stringValue(""));

            ProjectExisting existing = jdbc.sql("""
                            select id, detail::text
                            from career_nodes
                            where graph_id = :graphId and canonical_key = :canonicalKey
                            for update
                            """)
                    .param("graphId", graphId)
                    .param("canonicalKey", canonicalKey)
                    .query((rs, rowNum) -> new ProjectExisting(
                            rs.getObject("id", UUID.class), rs.getString("detail")
                    ))
                    .optional()
                    .orElse(null);
            UUID nodeId;
            if (existing == null) {
                nodeId = jdbc.sql("""
                                insert into career_nodes (
                                    user_id, graph_id, posting_id, kind, canonical_key,
                                    title, subtitle, domain, scope_definition, detail, rank
                                ) values (
                                    :userId, :graphId, :postingId, 'PROJECT', :canonicalKey,
                                    :title, :subtitle, :domain, :scope, cast(:detail as jsonb), :rank
                                ) returning id
                                """)
                        .param("userId", userId)
                        .param("graphId", graphId)
                        .param("postingId", postingId)
                        .param("canonicalKey", canonicalKey)
                        .param("title", title)
                        .param("subtitle", clip(spec.path("objective").stringValue(""), 240))
                        .param("domain", domain)
                        .param("scope", scope)
                        .param("detail", detail)
                        .param("rank", node.path("displayRank").asInt())
                        .query(UUID.class)
                        .single();
                jdbc.sql("""
                                insert into node_progress (user_id, node_id, status)
                                values (:userId, :nodeId, 'NOT_STARTED')
                                """)
                        .param("userId", userId)
                        .param("nodeId", nodeId)
                        .update();
            } else {
                nodeId = existing.id();
                boolean changed = !objectMapper.readTree(existing.detail()).equals(spec);
                jdbc.sql("""
                                update career_nodes
                                set posting_id = :postingId, title = :title, subtitle = :subtitle,
                                    domain = :domain, scope_definition = :scope,
                                    detail = cast(:detail as jsonb), rank = :rank, archived_at = null
                                where id = :nodeId
                                """)
                        .param("postingId", postingId)
                        .param("title", title)
                        .param("subtitle", clip(spec.path("objective").stringValue(""), 240))
                        .param("domain", domain)
                        .param("scope", scope)
                        .param("detail", detail)
                        .param("rank", node.path("displayRank").asInt())
                        .param("nodeId", nodeId)
                        .update();
                if (changed) {
                    jdbc.sql("""
                                    update node_progress
                                    set status = 'NOT_STARTED', completion_method = null,
                                        completed_at = null, updated_at = now()
                                    where node_id = :nodeId
                                    """)
                            .param("nodeId", nodeId)
                            .update();
                }
            }
        }
    }

    private String projectScope(JsonNode spec) {
        StringBuilder text = new StringBuilder(spec.path("objective").stringValue(""));
        for (JsonNode task : spec.path("tasks")) {
            text.append("\n\n필수 과제: ").append(task.path("title").stringValue(""));
            text.append("\n목표: ").append(task.path("objective").stringValue(""));
            for (JsonNode criterion : task.path("acceptanceCriteria")) {
                text.append("\n- 완료 기준: ").append(criterion.stringValue(""));
            }
        }
        for (JsonNode criterion : spec.path("verificationCriteria")) {
            text.append("\n- 최종 검증 기준: ").append(criterion.stringValue(""));
        }
        return text.toString();
    }

    static String projectKey(JsonNode node) {
        String target = node.path("targetRef").stringValue(node.path("nodeId").stringValue(""));
        return clip("v3.project:" + target.replaceFirst("^project:", ""), 160);
    }

    private static UUID postingId(String targetRef) {
        try {
            return UUID.fromString(targetRef.replaceFirst("^project:", ""));
        } catch (IllegalArgumentException exception) {
            return null;
        }
    }

    private static String clip(String value, int max) {
        if (value == null) return "";
        return value.length() <= max ? value : value.substring(0, max);
    }

    private record ProjectState(UUID nodeId, String progressStatus, boolean hasEvidence) {}
    private record ProjectExisting(UUID id, String detail) {}
}
