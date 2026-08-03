package com.jobiss.career;

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
public class CareerMapService {

    private final RlsTransactionExecutor rls;
    private final ObjectMapper objectMapper;

    public CareerMapService(RlsTransactionExecutor rls, ObjectMapper objectMapper) {
        this.rls = rls;
        this.objectMapper = objectMapper;
    }

    public CareerMap get(UUID userId) {
        return rls.read(userId, jdbc -> {
            Graph graph = jdbc.sql("""
                            select id, title, version, updated_at
                            from career_graphs
                            where user_id = :userId
                            """)
                    .param("userId", userId)
                    .query((rs, rowNum) -> new Graph(
                            rs.getObject("id", UUID.class),
                            rs.getString("title"),
                            rs.getLong("version"),
                            rs.getObject("updated_at", OffsetDateTime.class)
                    ))
                    .optional()
                    .orElseThrow(() -> new ApiException(
                            HttpStatus.NOT_FOUND,
                            "CAREER_MAP_NOT_FOUND",
                            "커리어 지도를 찾을 수 없습니다."
                    ));

            List<Node> nodes = jdbc.sql("""
                            select
                                n.id,
                                n.canonical_key,
                                n.title,
                                n.subtitle,
                                n.domain,
                                n.kind,
                                n.scope_definition,
                                n.level,
                                n.detail,
                                n.rank,
                                p.status as progress_status,
                                p.completion_method,
                                p.completed_at
                            from career_nodes n
                            left join node_progress p on p.node_id = n.id
                            where n.graph_id = :graphId
                              and n.archived_at is null
                            order by n.rank, n.created_at
                            """)
                    .param("graphId", graph.id())
                    .query((rs, rowNum) -> new Node(
                            rs.getObject("id", UUID.class),
                            rs.getString("canonical_key"),
                            rs.getString("title"),
                            rs.getString("subtitle"),
                            rs.getString("domain"),
                            rs.getString("kind"),
                            rs.getString("scope_definition"),
                            rs.getInt("level"),
                            readJson(rs.getString("detail")),
                            rs.getInt("rank"),
                            rs.getString("progress_status"),
                            rs.getString("completion_method"),
                            rs.getObject("completed_at", OffsetDateTime.class)
                    ))
                    .list();

            List<Edge> edges = jdbc.sql("""
                            select e.id, e.from_node_id, e.to_node_id, e.edge_kind
                            from career_edges e
                            join career_nodes source on source.id = e.from_node_id
                            join career_nodes target on target.id = e.to_node_id
                            where e.graph_id = :graphId
                              and source.archived_at is null
                              and target.archived_at is null
                            order by e.created_at
                            """)
                    .param("graphId", graph.id())
                    .query((rs, rowNum) -> new Edge(
                            rs.getObject("id", UUID.class),
                            rs.getObject("from_node_id", UUID.class),
                            rs.getObject("to_node_id", UUID.class),
                            rs.getString("edge_kind")
                    ))
                    .list();

            List<Requirement> requirements = jdbc.sql("""
                            select
                                r.posting_id,
                                r.node_id,
                                r.requirement,
                                r.source_text,
                                r.confidence
                            from job_requirements r
                            join career_nodes n on n.id = r.node_id
                            where n.graph_id = :graphId
                              and n.archived_at is null
                            """)
                    .param("graphId", graph.id())
                    .query((rs, rowNum) -> new Requirement(
                            rs.getObject("posting_id", UUID.class),
                            rs.getObject("node_id", UUID.class),
                            rs.getString("requirement"),
                            rs.getString("source_text"),
                            rs.getBigDecimal("confidence")
                    ))
                    .list();

            return new CareerMap(graph, nodes, edges, requirements);
        });
    }

    public void selfConfirm(UUID userId, UUID nodeId) {
        rls.write(userId, jdbc -> {
            int updated = jdbc.sql("""
                            update node_progress p
                            set
                                status = 'COMPLETED',
                                completion_method = 'SELF_CONFIRM',
                                completed_at = now()
                            from career_nodes n
                            where p.node_id = n.id
                              and n.id = :nodeId
                              and n.user_id = :userId
                              and n.kind = 'FOUNDATION'
                              and coalesce((n.detail ->> 'selfConfirmable')::boolean, false)
                            """)
                    .param("nodeId", nodeId)
                    .param("userId", userId)
                    .update();
            if (updated == 0) {
                throw new ApiException(
                        HttpStatus.BAD_REQUEST,
                        "NODE_NOT_SELF_CONFIRMABLE",
                        "직접 완료할 수 없는 단계입니다."
                );
            }
            jdbc.sql("""
                            update user_competencies c
                            set
                                progress_status = 'COMPLETED',
                                verified_level = greatest(c.verified_level, n.level),
                                completion_method = 'SELF_CONFIRM',
                                completed_at = now()
                            from career_nodes n
                            where n.id = :nodeId
                              and c.user_id = :userId
                              and c.canonical_key = n.canonical_key
                            """)
                    .param("nodeId", nodeId)
                    .param("userId", userId)
                    .update();
            return null;
        });
    }

    private JsonNode readJson(String value) {
        try {
            return value == null ? objectMapper.createObjectNode() : objectMapper.readTree(value);
        } catch (RuntimeException exception) {
            throw new IllegalStateException("Stored graph JSON is invalid", exception);
        }
    }

    public record CareerMap(
            Graph graph,
            List<Node> nodes,
            List<Edge> edges,
            List<Requirement> requirements
    ) {
    }

    public record Graph(UUID id, String title, long version, OffsetDateTime updatedAt) {
    }

    public record Node(
            UUID id,
            String canonicalKey,
            String title,
            String subtitle,
            String domain,
            String kind,
            String scopeDefinition,
            int level,
            JsonNode detail,
            int rank,
            String progressStatus,
            String completionMethod,
            OffsetDateTime completedAt
    ) {
    }

    public record Edge(UUID id, UUID fromNodeId, UUID toNodeId, String edgeKind) {
    }

    public record Requirement(
            UUID postingId,
            UUID nodeId,
            String kind,
            String sourceText,
            java.math.BigDecimal confidence
    ) {
    }
}
