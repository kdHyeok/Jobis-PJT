package com.jobiss.analysis;

import com.jobiss.common.ApiException;
import com.jobiss.db.RlsTransactionExecutor;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import tools.jackson.databind.ObjectMapper;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.regex.Pattern;

@Service
public class GraphMergeService {

    private static final Pattern CANONICAL_KEY = Pattern.compile("[a-z0-9][a-z0-9._:-]{2,159}");
    private static final Pattern REF_KEY = Pattern.compile("[A-Za-z0-9_-]{1,80}");
    private static final Set<String> NODE_KINDS = Set.of(
            "FOUNDATION",
            "SKILL",
            "PROJECT",
            "CREDENTIAL",
            "EXPERIENCE",
            "OPPORTUNITY",
            "OPPORTUNITY_CLUSTER"
    );
    private static final Set<String> REQUIREMENT_KINDS = Set.of("REQUIRED", "PREFERRED");
    private static final Set<String> EDGE_KINDS = Set.of(
            "PREREQUISITE",
            "BRANCH",
            "MERGE",
            "OPPORTUNITY_PATH"
    );

    private final RlsTransactionExecutor rls;
    private final ObjectMapper objectMapper;

    public GraphMergeService(RlsTransactionExecutor rls, ObjectMapper objectMapper) {
        this.rls = rls;
        this.objectMapper = objectMapper;
    }

    public MergeResult approve(UUID userId, UUID analysisJobId) {
        return rls.write(userId, jdbc -> {
            PendingMerge pending = loadPending(jdbc, analysisJobId);
            if (!"SUCCEEDED".equals(pending.analysisStatus())) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "ANALYSIS_NOT_COMPLETED",
                        "완료된 분석만 지도에 반영할 수 있습니다."
                );
            }
            if (!"PROPOSED".equals(pending.changeSetStatus())) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "CHANGE_SET_ALREADY_DECIDED",
                        "이미 처리된 변경안입니다."
                );
            }
            AiContracts.ChangeProposal proposal = parseProposal(pending.proposalJson());
            validateProposal(proposal);

            if (proposal.baseGraphVersion() != pending.graphVersion()) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "CAREER_MAP_CHANGED",
                        "분석 후 커리어 지도가 변경되었습니다. 공고를 다시 분석해 주세요."
                );
            }

            Map<String, UUID> nodeIds = resolveNodes(jdbc, userId, pending, proposal.nodes());
            retireSupersededOpportunities(
                    jdbc,
                    pending.postingId(),
                    proposal.nodes(),
                    nodeIds
            );
            validateAcyclic(jdbc, pending.graphId(), proposal.edges(), nodeIds);
            mergeEdges(jdbc, userId, pending.graphId(), proposal.edges(), nodeIds);
            mergeRequirements(
                    jdbc,
                    userId,
                    pending.postingId(),
                    proposal.requirements(),
                    nodeIds
            );
            recalculateRanks(jdbc, pending.graphId());

            int updated = jdbc.sql("""
                            update graph_change_sets
                            set status = 'APPROVED', approved_at = now()
                            where id = :changeSetId
                              and status = 'PROPOSED'
                            """)
                    .param("changeSetId", pending.changeSetId())
                    .update();
            if (updated == 0) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "CHANGE_SET_ALREADY_DECIDED",
                        "이미 처리된 변경안입니다."
                );
            }

            long newVersion = jdbc.sql("""
                            update career_graphs
                            set version = version + 1
                            where id = :graphId
                            returning version
                            """)
                    .param("graphId", pending.graphId())
                    .query(Long.class)
                    .single();

            jdbc.sql("""
                            insert into notifications (
                                user_id,
                                notification_type,
                                title,
                                body,
                                payload
                            )
                            values (
                                :userId,
                                'CAREER_MAP_UPDATED',
                                '커리어 지도가 업데이트됐어요',
                                '새 공고의 필수·우대 경로를 지도에서 확인해 보세요.',
                                jsonb_build_object(
                                    'analysisJobId',
                                    cast(:analysisJobId as text),
                                    'graphVersion',
                                    :graphVersion
                                )
                            )
                            """)
                    .param("userId", userId)
                    .param("analysisJobId", analysisJobId)
                    .param("graphVersion", newVersion)
                    .update();

            return new MergeResult(
                    pending.graphId(),
                    newVersion,
                    nodeIds.size(),
                    proposal.edges().size(),
                    proposal.requirements().size()
            );
        });
    }

    public void reject(UUID userId, UUID analysisJobId) {
        rls.write(userId, jdbc -> {
            int updated = jdbc.sql("""
                            update graph_change_sets c
                            set status = 'REJECTED', rejected_at = now()
                            from analysis_jobs j
                            where c.analysis_job_id = :analysisJobId
                              and j.id = c.analysis_job_id
                              and c.status = 'PROPOSED'
                            """)
                    .param("analysisJobId", analysisJobId)
                    .update();
            if (updated == 0) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "CHANGE_SET_NOT_REJECTABLE",
                        "거절할 수 있는 변경안이 없습니다."
                );
            }
            return null;
        });
    }

    private PendingMerge loadPending(JdbcClient jdbc, UUID analysisJobId) {
        return jdbc.sql("""
                        select
                            c.id as change_set_id,
                            c.proposal::text as proposal_json,
                            c.status as change_set_status,
                            j.status as analysis_status,
                            j.posting_id,
                            g.id as graph_id,
                            g.version as graph_version
                        from graph_change_sets c
                        join analysis_jobs j on j.id = c.analysis_job_id
                        join career_graphs g on g.user_id = c.user_id
                        where c.analysis_job_id = :analysisJobId
                        for update of c
                        """)
                .param("analysisJobId", analysisJobId)
                .query((rs, rowNum) -> new PendingMerge(
                        rs.getObject("change_set_id", UUID.class),
                        rs.getString("proposal_json"),
                        rs.getString("change_set_status"),
                        rs.getString("analysis_status"),
                        rs.getObject("posting_id", UUID.class),
                        rs.getObject("graph_id", UUID.class),
                        rs.getLong("graph_version")
                ))
                .optional()
                .orElseThrow(() -> new ApiException(
                        HttpStatus.NOT_FOUND,
                        "CHANGE_SET_NOT_FOUND",
                        "승인할 변경안을 찾을 수 없습니다."
                ));
    }

    private AiContracts.ChangeProposal parseProposal(String value) {
        try {
            return objectMapper.readValue(value, AiContracts.ChangeProposal.class);
        } catch (RuntimeException exception) {
            throw new ApiException(
                    HttpStatus.UNPROCESSABLE_CONTENT,
                    "INVALID_CHANGE_SET",
                    "AI 변경안의 형식이 올바르지 않습니다."
            );
        }
    }

    private void validateProposal(AiContracts.ChangeProposal proposal) {
        if (proposal.nodes() == null || proposal.edges() == null || proposal.requirements() == null) {
            invalid("변경안 목록이 누락되었습니다.");
        }
        if (proposal.nodes().size() > 100
                || proposal.edges().size() > 200
                || proposal.requirements().size() > 200) {
            invalid("한 번에 반영할 수 있는 변경 수를 초과했습니다.");
        }

        Set<String> refs = new HashSet<>();
        Set<String> identities = new HashSet<>();
        Set<UUID> reusedNodeIds = new HashSet<>();
        for (AiContracts.ProposedNode node : proposal.nodes()) {
            if (node.ref() == null || !REF_KEY.matcher(node.ref()).matches() || !refs.add(node.ref())) {
                invalid("노드 참조 키가 올바르지 않거나 중복되었습니다.");
            }
            if (node.canonicalKey() == null
                    || !CANONICAL_KEY.matcher(node.canonicalKey()).matches()) {
                invalid("정규화된 역량 키가 올바르지 않습니다.");
            }
            if (!Set.of("CREATE", "REUSE").contains(node.action())) {
                invalid("노드 작업은 CREATE 또는 REUSE여야 합니다.");
            }
            if (!NODE_KINDS.contains(node.kind())) {
                invalid("지원하지 않는 노드 종류입니다.");
            }
            if (node.level() < 1 || node.level() > 5) {
                invalid("노드 수준은 1부터 5 사이여야 합니다.");
            }
            if (blank(node.title()) || node.title().length() > 160
                    || blank(node.domain()) || node.domain().length() > 40) {
                invalid("노드 제목과 분야가 필요합니다.");
            }
            if ("CREATE".equals(node.action()) && blank(node.scopeDefinition())) {
                invalid("새 노드에는 범위 정의가 필요합니다.");
            }
            if (node.scopeDefinition() != null && node.scopeDefinition().length() > 4000) {
                invalid("노드 범위 정의가 너무 깁니다.");
            }
            if ("REUSE".equals(node.action())) {
                if (node.existingNodeId() == null || !reusedNodeIds.add(node.existingNodeId())) {
                    invalid("재사용 노드는 고유한 existingNodeId가 필요합니다.");
                }
            } else if (node.existingNodeId() != null) {
                invalid("새 노드에는 existingNodeId를 사용할 수 없습니다.");
            }
            String identity = node.canonicalKey()
                    + "|" + node.level()
                    + "|" + normalizeScope(node.scopeDefinition());
            if (!identities.add(identity)) {
                invalid("같은 범위와 수준의 노드가 변경안에 중복되었습니다.");
            }
        }

        for (AiContracts.ProposedEdge edge : proposal.edges()) {
            if (!refs.contains(edge.fromRef()) || !refs.contains(edge.toRef())) {
                invalid("연결선이 존재하지 않는 노드를 참조합니다.");
            }
            if (edge.fromRef().equals(edge.toRef())) {
                invalid("노드가 자기 자신을 선행 조건으로 가질 수 없습니다.");
            }
            if (!blank(edge.edgeKind()) && !EDGE_KINDS.contains(edge.edgeKind())) {
                invalid("지원하지 않는 연결 종류입니다.");
            }
        }

        for (AiContracts.ProposedRequirement requirement : proposal.requirements()) {
            if (!refs.contains(requirement.nodeRef())) {
                invalid("공고 조건이 존재하지 않는 노드를 참조합니다.");
            }
            if (!REQUIREMENT_KINDS.contains(requirement.kind())) {
                invalid("공고 조건은 REQUIRED 또는 PREFERRED여야 합니다.");
            }
            if (requirement.confidence() != null
                    && (requirement.confidence().signum() < 0
                    || requirement.confidence().compareTo(java.math.BigDecimal.ONE) > 0)) {
                invalid("신뢰도는 0부터 1 사이여야 합니다.");
            }
        }
    }

    private Map<String, UUID> resolveNodes(
            JdbcClient jdbc,
            UUID userId,
            PendingMerge pending,
            List<AiContracts.ProposedNode> nodes
    ) {
        Map<String, UUID> resolved = new HashMap<>();
        for (AiContracts.ProposedNode node : nodes) {
            UUID nodeId;
            if ("REUSE".equals(node.action())) {
                nodeId = jdbc.sql("""
                                select id
                                from career_nodes
                                where graph_id = :graphId
                                  and id = :existingNodeId
                                  and canonical_key = :canonicalKey
                                  and level = :level
                                  and lower(regexp_replace(
                                        coalesce(scope_definition, ''),
                                        '\\s+',
                                        ' ',
                                        'g'
                                      )) = :scopeDefinition
                                  and archived_at is null
                                """)
                        .param("graphId", pending.graphId())
                        .param("existingNodeId", node.existingNodeId())
                        .param("canonicalKey", node.canonicalKey())
                        .param("level", node.level())
                        .param("scopeDefinition", normalizeScope(node.scopeDefinition()))
                        .query(UUID.class)
                        .optional()
                        .orElseThrow(() -> new ApiException(
                                HttpStatus.CONFLICT,
                                "REUSED_NODE_NOT_FOUND",
                                "재사용하려는 기존 역량을 찾을 수 없습니다: " + node.canonicalKey()
                        ));
            } else {
                boolean exists = jdbc.sql("""
                                select exists (
                                    select 1
                                    from career_nodes
                                    where graph_id = :graphId
                                      and canonical_key = :canonicalKey
                                      and level = :level
                                      and lower(regexp_replace(
                                            coalesce(scope_definition, ''),
                                            '\\s+',
                                            ' ',
                                            'g'
                                          )) = :scopeDefinition
                                      and archived_at is null
                                )
                                """)
                        .param("graphId", pending.graphId())
                        .param("canonicalKey", node.canonicalKey())
                        .param("level", node.level())
                        .param("scopeDefinition", normalizeScope(node.scopeDefinition()))
                        .query(Boolean.class)
                        .single();
                if (exists) {
                    throw new ApiException(
                            HttpStatus.CONFLICT,
                            "CANONICAL_NODE_ALREADY_EXISTS",
                            "같은 정규화 키가 이미 존재합니다. 새 분석이 필요합니다."
                    );
                }

                UUID postingId = "OPPORTUNITY".equals(node.kind())
                        ? pending.postingId()
                        : null;
                nodeId = jdbc.sql("""
                                insert into career_nodes (
                                    user_id,
                                    graph_id,
                                    posting_id,
                                    kind,
                                    canonical_key,
                                    title,
                                    subtitle,
                                    domain,
                                    scope_definition,
                                    level,
                                    detail,
                                    rank
                                )
                                values (
                                    :userId,
                                    :graphId,
                                    :postingId,
                                    cast(:kind as graph_node_kind),
                                    :canonicalKey,
                                    :title,
                                    :subtitle,
                                    :domain,
                                    :scopeDefinition,
                                    :level,
                                    cast(:detail as jsonb),
                                    :rank
                                )
                                returning id
                                """)
                        .param("userId", userId)
                        .param("graphId", pending.graphId())
                        .param("postingId", postingId)
                        .param("kind", node.kind())
                        .param("canonicalKey", node.canonicalKey())
                        .param("title", node.title())
                        .param("subtitle", node.subtitle())
                        .param("domain", node.domain())
                        .param("scopeDefinition", node.scopeDefinition())
                        .param("level", node.level())
                        .param("detail", writeJson(node.detail()))
                        .param("rank", node.rank())
                        .query(UUID.class)
                        .single();

                jdbc.sql("""
                                insert into node_progress (user_id, node_id)
                                values (:userId, :nodeId)
                                on conflict (node_id) do nothing
                                """)
                        .param("userId", userId)
                        .param("nodeId", nodeId)
                        .update();
            }
            resolved.put(node.ref(), nodeId);
        }
        return resolved;
    }

    private void mergeEdges(
            JdbcClient jdbc,
            UUID userId,
            UUID graphId,
            List<AiContracts.ProposedEdge> edges,
            Map<String, UUID> nodeIds
    ) {
        for (AiContracts.ProposedEdge edge : edges) {
            jdbc.sql("""
                            insert into career_edges (
                                user_id,
                                graph_id,
                                from_node_id,
                                to_node_id,
                                edge_kind
                            )
                            values (
                                :userId,
                                :graphId,
                                :fromNodeId,
                                :toNodeId,
                                :edgeKind
                            )
                            on conflict (graph_id, from_node_id, to_node_id, edge_kind)
                            do nothing
                            """)
                    .param("userId", userId)
                    .param("graphId", graphId)
                    .param("fromNodeId", nodeIds.get(edge.fromRef()))
                    .param("toNodeId", nodeIds.get(edge.toRef()))
                    .param("edgeKind", defaultText(edge.edgeKind(), "PREREQUISITE"))
                    .update();
        }
    }

    private void validateAcyclic(
            JdbcClient jdbc,
            UUID graphId,
            List<AiContracts.ProposedEdge> proposedEdges,
            Map<String, UUID> nodeIds
    ) {
        List<UUID> nodes = jdbc.sql("""
                        select id from career_nodes
                        where graph_id = :graphId and archived_at is null
                        """)
                .param("graphId", graphId)
                .query(UUID.class)
                .list();
        Map<UUID, List<UUID>> adjacency = new HashMap<>();
        Map<UUID, Integer> indegree = new HashMap<>();
        for (UUID node : nodes) {
            adjacency.put(node, new ArrayList<>());
            indegree.put(node, 0);
        }
        List<IdEdge> existing = jdbc.sql("""
                        select from_node_id, to_node_id
                        from career_edges
                        where graph_id = :graphId
                        """)
                .param("graphId", graphId)
                .query((rs, rowNum) -> new IdEdge(
                        rs.getObject("from_node_id", UUID.class),
                        rs.getObject("to_node_id", UUID.class)
                ))
                .list();
        Set<String> seen = new HashSet<>();
        for (IdEdge edge : existing) {
            addEdge(adjacency, indegree, seen, edge.from(), edge.to());
        }
        for (AiContracts.ProposedEdge edge : proposedEdges) {
            addEdge(
                    adjacency,
                    indegree,
                    seen,
                    nodeIds.get(edge.fromRef()),
                    nodeIds.get(edge.toRef())
            );
        }
        if (topologicalOrder(adjacency, indegree).size() != nodes.size()) {
            invalid("변경안이 커리어 지도에 순환 경로를 만듭니다.");
        }
    }

    private void recalculateRanks(JdbcClient jdbc, UUID graphId) {
        List<UUID> nodes = jdbc.sql("""
                        select id from career_nodes
                        where graph_id = :graphId and archived_at is null
                        """)
                .param("graphId", graphId)
                .query(UUID.class)
                .list();
        Map<UUID, List<UUID>> adjacency = new HashMap<>();
        Map<UUID, Integer> indegree = new HashMap<>();
        for (UUID node : nodes) {
            adjacency.put(node, new ArrayList<>());
            indegree.put(node, 0);
        }
        Set<String> seen = new HashSet<>();
        List<IdEdge> edges = jdbc.sql("""
                        select from_node_id, to_node_id
                        from career_edges
                        where graph_id = :graphId
                        """)
                .param("graphId", graphId)
                .query((rs, rowNum) -> new IdEdge(
                        rs.getObject("from_node_id", UUID.class),
                        rs.getObject("to_node_id", UUID.class)
                ))
                .list();
        for (IdEdge edge : edges) {
            addEdge(adjacency, indegree, seen, edge.from(), edge.to());
        }
        List<UUID> order = topologicalOrder(adjacency, new HashMap<>(indegree));
        if (order.size() != nodes.size()) {
            invalid("기존 커리어 지도에 순환 경로가 있습니다.");
        }
        Map<UUID, Integer> ranks = new HashMap<>();
        for (UUID node : order) {
            int current = ranks.getOrDefault(node, 0);
            for (UUID next : adjacency.getOrDefault(node, List.of())) {
                ranks.merge(next, current + 1, Math::max);
            }
        }
        for (UUID node : nodes) {
            jdbc.sql("update career_nodes set rank = :rank where id = :nodeId")
                    .param("rank", ranks.getOrDefault(node, 0))
                    .param("nodeId", node)
                    .update();
        }
    }

    private void addEdge(
            Map<UUID, List<UUID>> adjacency,
            Map<UUID, Integer> indegree,
            Set<String> seen,
            UUID from,
            UUID to
    ) {
        String key = from + ">" + to;
        if (seen.add(key)) {
            adjacency.computeIfAbsent(from, ignored -> new ArrayList<>()).add(to);
            indegree.merge(to, 1, Integer::sum);
        }
    }

    private List<UUID> topologicalOrder(
            Map<UUID, List<UUID>> adjacency,
            Map<UUID, Integer> indegree
    ) {
        ArrayDeque<UUID> queue = new ArrayDeque<>();
        indegree.forEach((node, count) -> {
            if (count == 0) {
                queue.add(node);
            }
        });
        List<UUID> order = new ArrayList<>();
        while (!queue.isEmpty()) {
            UUID node = queue.removeFirst();
            order.add(node);
            for (UUID next : adjacency.getOrDefault(node, List.of())) {
                int remaining = indegree.merge(next, -1, Integer::sum);
                if (remaining == 0) {
                    queue.add(next);
                }
            }
        }
        return order;
    }

    private void mergeRequirements(
            JdbcClient jdbc,
            UUID userId,
            UUID postingId,
            List<AiContracts.ProposedRequirement> requirements,
            Map<String, UUID> nodeIds
    ) {
        jdbc.sql("delete from job_requirements where posting_id = :postingId")
                .param("postingId", postingId)
                .update();

        for (AiContracts.ProposedRequirement requirement : requirements) {
            jdbc.sql("""
                            insert into job_requirements (
                                user_id,
                                posting_id,
                                node_id,
                                requirement,
                                source_text,
                                confidence
                            )
                            values (
                                :userId,
                                :postingId,
                                :nodeId,
                                cast(:requirement as requirement_kind),
                                :sourceText,
                                :confidence
                            )
                            """)
                    .param("userId", userId)
                    .param("postingId", postingId)
                    .param("nodeId", nodeIds.get(requirement.nodeRef()))
                    .param("requirement", requirement.kind())
                    .param("sourceText", requirement.sourceText())
                    .param("confidence", requirement.confidence())
                    .update();
        }
    }

    private void retireSupersededOpportunities(
            JdbcClient jdbc,
            UUID postingId,
            List<AiContracts.ProposedNode> proposedNodes,
            Map<String, UUID> nodeIds
    ) {
        Set<UUID> retained = new HashSet<>();
        for (AiContracts.ProposedNode node : proposedNodes) {
            if ("OPPORTUNITY".equals(node.kind())) {
                retained.add(nodeIds.get(node.ref()));
            }
        }
        List<UUID> previous = jdbc.sql("""
                        select id
                        from career_nodes
                        where posting_id = :postingId
                          and kind = 'OPPORTUNITY'
                          and archived_at is null
                        """)
                .param("postingId", postingId)
                .query(UUID.class)
                .list();
        for (UUID nodeId : previous) {
            if (retained.contains(nodeId)) {
                continue;
            }
            jdbc.sql("""
                            delete from career_edges
                            where from_node_id = :nodeId or to_node_id = :nodeId
                            """)
                    .param("nodeId", nodeId)
                    .update();
            jdbc.sql("""
                            update career_nodes
                            set archived_at = now(), updated_at = now()
                            where id = :nodeId
                            """)
                    .param("nodeId", nodeId)
                    .update();
        }
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value == null
                    ? objectMapper.createObjectNode()
                    : value);
        } catch (RuntimeException exception) {
            throw new ApiException(
                    HttpStatus.UNPROCESSABLE_CONTENT,
                    "INVALID_NODE_DETAIL",
                    "노드 상세 정보의 형식이 올바르지 않습니다."
            );
        }
    }

    private void invalid(String message) {
        throw new ApiException(HttpStatus.UNPROCESSABLE_CONTENT, "INVALID_CHANGE_SET", message);
    }

    private boolean blank(String value) {
        return value == null || value.isBlank();
    }

    private String normalizeScope(String value) {
        return value == null
                ? ""
                : value.trim().replaceAll("\\s+", " ").toLowerCase(java.util.Locale.ROOT);
    }

    private String defaultText(String value, String fallback) {
        return blank(value) ? fallback : value;
    }

    private record PendingMerge(
            UUID changeSetId,
            String proposalJson,
            String changeSetStatus,
            String analysisStatus,
            UUID postingId,
            UUID graphId,
            long graphVersion
    ) {
    }

    public record MergeResult(
            UUID graphId,
            long graphVersion,
            int resolvedNodeCount,
            int edgeCount,
            int requirementCount
    ) {
    }

    private record IdEdge(UUID from, UUID to) {
    }
}
