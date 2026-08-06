package com.jobiss.analysis.v3;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

@Component
public class V3AtomicCapabilityStateService {

    private final ObjectMapper objectMapper;

    public V3AtomicCapabilityStateService(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    public JsonNode overlay(JdbcClient jdbc, JsonNode snapshot) {
        if (snapshot == null || !snapshot.isObject()) {
            return snapshot;
        }
        Map<String, String> states = new HashMap<>();
        jdbc.sql("""
                        select canonical_key, progress_state
                        from user_atomic_capabilities
                        """)
                .query((rs, rowNum) -> Map.entry(
                        rs.getString("canonical_key"),
                        rs.getString("progress_state")
                ))
                .list()
                .forEach(entry -> states.put(entry.getKey(), entry.getValue()));

        ObjectNode result = ((ObjectNode) snapshot).deepCopy();
        JsonNode nodes = result.path("nodes");
        if (!nodes.isArray()) {
            return result;
        }
        for (JsonNode item : nodes) {
            if (!(item instanceof ObjectNode node)
                    || !"CAPABILITY".equals(node.path("nodeKind").stringValue(""))) {
                continue;
            }
            String state = states.get(node.path("canonicalKey").stringValue(""));
            if (state != null) {
                node.put("progressState", state);
            }
        }
        return result;
    }

    public void synchronize(
            JdbcClient jdbc,
            UUID userId,
            JsonNode snapshot,
            String graphVersion
    ) {
        if (snapshot == null || !snapshot.path("nodes").isArray()) {
            return;
        }
        for (JsonNode node : snapshot.path("nodes")) {
            if (!isApprovedAtomicCapability(node)) {
                continue;
            }
            String canonicalKey = node.path("canonicalKey").stringValue("");
            String technologyKey = node.path("technologyKey").stringValue("");
            int graphNodeVersion = Math.max(1, node.path("graphNodeVersion").asInt(1));
            ArrayNode methods = node.path("verificationMethods").isArray()
                    ? (ArrayNode) node.path("verificationMethods")
                    : objectMapper.createArrayNode();

            int inserted = jdbc.sql("""
                            insert into user_atomic_capabilities (
                                user_id,
                                canonical_key,
                                graph_version,
                                graph_node_version,
                                technology_key,
                                title,
                                scope_definition,
                                verification_methods,
                                objective,
                                excluded_scope,
                                completion_policy
                            )
                            values (
                                :userId,
                                :canonicalKey,
                                :graphVersion,
                                :graphNodeVersion,
                                :technologyKey,
                                :title,
                                :scopeDefinition,
                                cast(:verificationMethods as jsonb),
                                :objective,
                                cast(:excludedScope as jsonb),
                                :completionPolicy
                            )
                            on conflict (user_id, canonical_key) do nothing
                            """)
                    .param("userId", userId)
                    .param("canonicalKey", canonicalKey)
                    .param("graphVersion", graphVersion)
                    .param("graphNodeVersion", graphNodeVersion)
                    .param("technologyKey", technologyKey)
                    .param("title", node.path("title").stringValue(canonicalKey))
                    .param("scopeDefinition", node.path("scopeDefinition").stringValue(canonicalKey))
                    .param("verificationMethods", objectMapper.writeValueAsString(methods))
                    .param("objective", nullableText(node, "objective"))
                    .param("excludedScope", objectMapper.writeValueAsString(array(node, "excludedScope")))
                    .param("completionPolicy", text(node, "completionPolicy", "ASSESSMENT"))
                    .update();

            jdbc.sql("""
                            update user_atomic_capabilities
                            set
                                graph_version = :graphVersion,
                                graph_node_version = :graphNodeVersion,
                                technology_key = :technologyKey,
                                title = :title,
                                scope_definition = :scopeDefinition,
                                verification_methods = cast(:verificationMethods as jsonb),
                                objective = :objective,
                                excluded_scope = cast(:excludedScope as jsonb),
                                completion_policy = :completionPolicy
                            where canonical_key = :canonicalKey
                            """)
                    .param("canonicalKey", canonicalKey)
                    .param("graphVersion", graphVersion)
                    .param("graphNodeVersion", graphNodeVersion)
                    .param("technologyKey", technologyKey)
                    .param("title", node.path("title").stringValue(canonicalKey))
                    .param("scopeDefinition", node.path("scopeDefinition").stringValue(canonicalKey))
                    .param("verificationMethods", objectMapper.writeValueAsString(methods))
                    .param("objective", nullableText(node, "objective"))
                    .param("excludedScope", objectMapper.writeValueAsString(array(node, "excludedScope")))
                    .param("completionPolicy", text(node, "completionPolicy", "ASSESSMENT"))
                    .update();

            if (inserted == 1) {
                jdbc.sql("""
                                insert into user_atomic_capability_events (
                                    user_id,
                                    atomic_capability_id,
                                    from_state,
                                    to_state,
                                    event_type,
                                    source_ref
                                )
                                select
                                    :userId,
                                    id,
                                    null,
                                    'NOT_STARTED',
                                    'ROADMAP_REGISTERED',
                                    :sourceRef
                                from user_atomic_capabilities
                                where canonical_key = :canonicalKey
                                """)
                        .param("userId", userId)
                        .param("canonicalKey", canonicalKey)
                        .param("sourceRef", "roadmap:" + snapshot.path("roadmapVersion").asLong())
                        .update();
            }

            createMigrationCandidates(jdbc, userId, canonicalKey, technologyKey);
        }
    }

    private void createMigrationCandidates(
            JdbcClient jdbc,
            UUID userId,
            String canonicalKey,
            String technologyKey
    ) {
        jdbc.sql("""
                        insert into user_atomic_migration_candidates (
                            user_id,
                            legacy_competency_id,
                            atomic_capability_id,
                            technology_key,
                            legacy_progress_status,
                            legacy_verified_level,
                            confidence,
                            reason
                        )
                        select
                            :userId,
                            legacy.id,
                            atomic.id,
                            :technologyKey,
                            legacy.progress_status::text,
                            legacy.verified_level,
                            0.500,
                            'Legacy broad competency matches the atomic node technology container; atomic scope still requires review.'
                        from user_competencies legacy
                        join user_atomic_capabilities atomic
                          on atomic.canonical_key = :canonicalKey
                        where legacy.canonical_key = :technologyKey
                          and (
                              legacy.progress_status <> 'NOT_STARTED'
                              or legacy.verified_level > 0
                          )
                        on conflict (user_id, legacy_competency_id, atomic_capability_id) do nothing
                        """)
                .param("userId", userId)
                .param("canonicalKey", canonicalKey)
                .param("technologyKey", technologyKey)
                .update();
    }

    private boolean isApprovedAtomicCapability(JsonNode node) {
        return "CAPABILITY".equals(node.path("nodeKind").stringValue(""))
                && !node.path("canonicalKey").stringValue("").isBlank()
                && !node.path("technologyKey").stringValue("").isBlank()
                && node.path("provisionalCandidateId").stringValue("").isBlank();
    }

    private ArrayNode array(JsonNode node, String field) {
        return node.path(field).isArray()
                ? (ArrayNode) node.path(field)
                : objectMapper.createArrayNode();
    }

    private String nullableText(JsonNode node, String field) {
        String value = node.path(field).stringValue("");
        return value.isBlank() ? null : value;
    }

    private String text(JsonNode node, String field, String fallback) {
        String value = node.path(field).stringValue("");
        return value.isBlank() ? fallback : value;
    }
}
