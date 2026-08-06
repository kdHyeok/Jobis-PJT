package com.jobiss.analysis.v3;

import com.jobiss.common.ApiException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;

/**
 * Spring-owned deterministic compiler for the jobis.ai.v3alpha1 roadmap contract.
 *
 * <p>This mirrors AI-v3's compiler_reference.py. AI may propose a DRAFT, but it
 * cannot publish a roadmap or overwrite a user's progress.</p>
 */
@Component
public class V3RoadmapCompiler {

    private static final Set<String> BLOCKING_RELATIONS = Set.of(
            "HARD_PREREQUISITE",
            "CONDITIONAL_PREREQUISITE",
            "UNLOCKS_PROJECT",
            "REQUIRES_GATE",
            "UNLOCKS_OPPORTUNITY",
            "CAREER_STAGE_ORDER",
            "POTENTIAL_CAREER_ENTRY",
            "STARTS_EXPERIENCE",
            "SATISFIES_EXPERIENCE_GATE"
    );

    private final ObjectMapper objectMapper;

    public V3RoadmapCompiler(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    public ObjectNode compile(JsonNode current, JsonNode proposal) {
        requireObject(current, "current roadmap");
        requireObject(proposal, "roadmap proposal");
        if (!"DRAFT".equals(text(proposal, "status"))) {
            throw failure("V3_ROADMAP_PROPOSAL_NOT_DRAFT", "초안 상태의 로드맵만 미리 볼 수 있습니다.");
        }

        long currentVersion = integral(current, "roadmapVersion");
        long basedOnVersion = integral(proposal, "basedOnRoadmapVersion");
        if (currentVersion != basedOnVersion) {
            throw failure(
                    "V3_ROADMAP_STALE_PROPOSAL",
                    "현재 지도 버전이 바뀌었습니다. 공고를 다시 분석해 새 초안을 만들어 주세요."
            );
        }

        Map<String, ObjectNode> nodes = new LinkedHashMap<>();
        Set<String> removeTargetRefs = stringSet(proposal.path("removeTargetRefs"));
        List<String> removedNodeIds = new ArrayList<>();
        List<String> removedRelationIds = new ArrayList<>();
        for (JsonNode value : array(current, "nodes")) {
            ObjectNode node = object(value, "current roadmap node").deepCopy();
            String nodeId = text(node, "nodeId");
            if ((!removeTargetRefs.isEmpty() && isSyntheticCareerNode(node))
                    || shouldRemoveTargetNode(node, removeTargetRefs)) {
                removedNodeIds.add(nodeId);
                continue;
            }
            if (nodes.putIfAbsent(nodeId, node) != null) {
                throw invalid("중복된 현재 지도 노드입니다: " + nodeId);
            }
        }

        Map<String, String> operationNodes = new HashMap<>();
        List<String> createdNodeIds = new ArrayList<>();
        List<String> reusedNodeIds = new ArrayList<>();
        for (JsonNode value : array(proposal, "operations")) {
            ObjectNode operation = object(value, "roadmap operation");
            String operationId = text(operation, "operationId");
            String action = text(operation, "action");
            if (operationNodes.containsKey(operationId)) {
                throw invalid("중복된 로드맵 작업입니다: " + operationId);
            }
            if ("REUSE_NODE".equals(action)) {
                String existingNodeId = text(operation, "existingNodeId");
                ObjectNode existing = nodes.get(existingNodeId);
                if (existing == null) {
                    throw failure(
                            "V3_ROADMAP_REUSED_NODE_MISSING",
                            "재사용하려는 기존 지도 노드를 찾을 수 없습니다: " + existingNodeId
                    );
                }
                validateReuseIdentity(existing, operation);
                nodes.put(existingNodeId, updatedExisting(existing, operation));
                operationNodes.put(operationId, existingNodeId);
                reusedNodeIds.add(existingNodeId);
                continue;
            }

            String nodeId = stableId("node", operationId);
            if (nodes.containsKey(nodeId)) {
                throw invalid("새 지도 노드 ID가 기존 노드와 충돌합니다: " + nodeId);
            }
            ObjectNode created = createdNode(nodeId, operation);
            nodes.put(nodeId, created);
            operationNodes.put(operationId, nodeId);
            createdNodeIds.add(nodeId);
        }

        Map<String, ObjectNode> relations = new LinkedHashMap<>();
        Set<String> semanticRelations = new HashSet<>();
        for (JsonNode value : array(current, "relations")) {
            ObjectNode relation = object(value, "current roadmap relation").deepCopy();
            if ("CAREER_STAGE_ORDER".equals(optionalText(relation, "relationType"))) {
                // Legacy snapshots connected an opportunity straight to an experience gate.
                // Rebuild that display-only edge with explicit employment and experience nodes.
                continue;
            }
            String relationId = text(relation, "relationId");
            if (!nodes.containsKey(optionalText(relation, "fromNodeId"))
                    || !nodes.containsKey(optionalText(relation, "toNodeId"))) {
                removedRelationIds.add(relationId);
                continue;
            }
            validateRelationEndpoints(relation, nodes);
            if (relations.putIfAbsent(relationId, relation) != null) {
                throw invalid("중복된 현재 지도 연결입니다: " + relationId);
            }
            semanticRelations.add(semanticKey(relation));
        }

        List<String> createdRelationIds = new ArrayList<>();
        for (JsonNode value : array(proposal, "relations")) {
            ObjectNode proposed = object(value, "roadmap relation");
            String fromOperationId = text(proposed, "fromOperationId");
            String toOperationId = text(proposed, "toOperationId");
            String fromNodeId = operationNodes.get(fromOperationId);
            String toNodeId = operationNodes.get(toOperationId);
            if (fromNodeId == null || toNodeId == null) {
                throw invalid("연결이 존재하지 않는 로드맵 작업을 참조합니다.");
            }
            String relationType = text(proposed, "relationType");
            String semanticKey = semanticKey(fromNodeId, toNodeId, relationType);
            if (!semanticRelations.add(semanticKey)) {
                continue;
            }
            String relationId = stableId("edge", fromNodeId, toNodeId, relationType);
            ObjectNode relation = objectMapper.createObjectNode();
            relation.put("relationId", relationId);
            relation.put("fromNodeId", fromNodeId);
            relation.put("toNodeId", toNodeId);
            relation.put("relationType", relationType);
            copyIfPresent(proposed, relation, "conditions");
            if (!relation.has("conditions")) {
                relation.set("conditions", objectMapper.createArrayNode());
            }
            relation.put("reason", text(proposed, "reason"));
            relations.put(relationId, relation);
            createdRelationIds.add(relationId);
        }

        if (!removeTargetRefs.isEmpty()) {
            pruneOrphanCapabilities(nodes, relations, removedNodeIds, removedRelationIds);
        }

        for (ObjectNode relation : careerGraphRelations(nodes, relations, createdNodeIds)) {
            String semanticKey = semanticKey(relation);
            if (!semanticRelations.add(semanticKey)) {
                continue;
            }
            String relationId = text(relation, "relationId");
            relations.put(relationId, relation);
            createdRelationIds.add(relationId);
        }

        Map<String, Integer> ranks = displayRanks(nodes, relations);
        nodes.forEach((nodeId, node) -> node.put("displayRank", ranks.getOrDefault(nodeId, 0)));

        List<ObjectNode> sortedNodes = new ArrayList<>(nodes.values());
        sortedNodes.sort(Comparator
                .comparingInt((ObjectNode node) -> node.path("displayRank").intValue())
                .thenComparing(node -> optionalText(node, "sectionKey"))
                .thenComparing(node -> optionalText(node, "nodeKind"))
                .thenComparing(node -> optionalText(node, "title"))
                .thenComparing(node -> optionalText(node, "nodeId")));
        List<ObjectNode> sortedRelations = new ArrayList<>(relations.values());
        sortedRelations.sort(Comparator.comparing(node -> text(node, "relationId")));

        long proposedVersion = currentVersion + 1;
        ObjectNode snapshot = objectMapper.createObjectNode();
        snapshot.put("roadmapVersion", proposedVersion);
        snapshot.set("nodes", toArray(sortedNodes));
        snapshot.set("relations", toArray(sortedRelations));

        ObjectNode preview = objectMapper.createObjectNode();
        preview.put("contractVersion", "jobis.ai.v3alpha1");
        preview.put("proposalId", text(proposal, "proposalId"));
        preview.put("basedOnRoadmapVersion", currentVersion);
        preview.put("proposedRoadmapVersion", proposedVersion);
        preview.set("snapshot", snapshot);
        preview.set("createdNodeIds", strings(createdNodeIds.stream().sorted().toList()));
        preview.set("reusedNodeIds", strings(reusedNodeIds.stream().distinct().sorted().toList()));
        preview.set("createdRelationIds", strings(createdRelationIds.stream().sorted().toList()));
        preview.set("removedNodeIds", strings(removedNodeIds.stream().distinct().sorted().toList()));
        preview.set(
                "removedRelationIds",
                strings(removedRelationIds.stream().distinct().sorted().toList())
        );
        return preview;
    }

    private static boolean isSyntheticCareerNode(ObjectNode node) {
        return Set.of("EMPLOYMENT_EVENT", "EXPERIENCE_INTERVAL")
                .contains(optionalText(node, "nodeKind"));
    }

    private static boolean shouldRemoveTargetNode(ObjectNode node, Set<String> targets) {
        if (targets.isEmpty()) {
            return false;
        }
        String targetRef = optionalText(node, "targetRef");
        if (targetRef.isBlank()) {
            return false;
        }
        for (String target : targets) {
            if (targetRef.equals(target)
                    || targetRef.equals("project:" + target)
                    || targetRef.startsWith("gate:" + target + ":")) {
                return true;
            }
        }
        return false;
    }

    private void pruneOrphanCapabilities(
            Map<String, ObjectNode> nodes,
            Map<String, ObjectNode> relations,
            List<String> removedNodeIds,
            List<String> removedRelationIds
    ) {
        Map<String, Set<String>> incoming = new HashMap<>();
        nodes.keySet().forEach(nodeId -> incoming.put(nodeId, new HashSet<>()));
        relations.values().forEach(relation -> incoming
                .get(text(relation, "toNodeId"))
                .add(text(relation, "fromNodeId")));
        Set<String> keep = new HashSet<>();
        List<String> pending = nodes.values().stream()
                .filter(node -> !"CAPABILITY".equals(optionalText(node, "nodeKind")))
                .map(node -> text(node, "nodeId"))
                .collect(java.util.stream.Collectors.toCollection(ArrayList::new));
        while (!pending.isEmpty()) {
            String nodeId = pending.remove(pending.size() - 1);
            if (!keep.add(nodeId)) {
                continue;
            }
            pending.addAll(incoming.getOrDefault(nodeId, Set.of()));
        }
        for (ObjectNode node : new ArrayList<>(nodes.values())) {
            if (!"CAPABILITY".equals(optionalText(node, "nodeKind"))) {
                continue;
            }
            boolean preserveProgress = !"NOT_STARTED".equals(optionalText(node, "progressState"));
            boolean preserveFoundation = "section.common".equals(optionalText(node, "sectionKey"));
            if (keep.contains(text(node, "nodeId")) || preserveProgress || preserveFoundation) {
                continue;
            }
            String nodeId = text(node, "nodeId");
            nodes.remove(nodeId);
            removedNodeIds.add(nodeId);
        }
        for (ObjectNode relation : new ArrayList<>(relations.values())) {
            if (nodes.containsKey(text(relation, "fromNodeId"))
                    && nodes.containsKey(text(relation, "toNodeId"))) {
                continue;
            }
            String relationId = text(relation, "relationId");
            relations.remove(relationId);
            removedRelationIds.add(relationId);
        }
    }

    private void validateReuseIdentity(ObjectNode existing, ObjectNode operation) {
        String existingKind = text(existing, "nodeKind");
        String operationKind = text(operation, "nodeKind");
        if (!existingKind.equals(operationKind)) {
            throw invalid("재사용 노드의 종류가 제안과 다릅니다.");
        }
        if ("CAPABILITY".equals(existingKind)) {
            if (!optionalText(existing, "canonicalKey").equals(optionalText(operation, "canonicalKey"))
                    || !optionalText(existing, "provisionalCandidateId").equals(
                    optionalText(operation, "provisionalCandidateId"))) {
                throw invalid("재사용 역량 노드의 정체성이 제안과 다릅니다.");
            }
        } else if (!optionalText(existing, "targetRef").equals(optionalText(operation, "targetRef"))) {
            throw invalid("재사용 목표 노드의 참조값이 제안과 다릅니다.");
        }
    }

    private ObjectNode updatedExisting(ObjectNode existing, ObjectNode operation) {
        ObjectNode updated = existing.deepCopy();
        putIfNonBlank(operation, updated, "title");
        if (optionalText(updated, "sectionKey").isBlank()) {
            putIfNonBlank(operation, updated, "sectionKey");
        }
        mergeSectionMemberships(updated, operation.path("sectionMemberships"));
        putIfNonBlank(operation, updated, "scopeDefinition");
        putIfNonBlank(operation, updated, "technologyKey");
        copyIfPresent(operation, updated, "verificationMethods");
        putIfNonBlank(operation, updated, "objective");
        copyIfPresent(operation, updated, "excludedScope");
        putIfNonBlank(operation, updated, "completionPolicy");
        if (operation.path("graphNodeVersion").isIntegralNumber()) {
            updated.put("graphNodeVersion", operation.path("graphNodeVersion").intValue());
        }
        if (operation.path("level").isIntegralNumber()) {
            updated.put("level", operation.path("level").intValue());
        }
        // progressState is deliberately never copied from the proposal.
        return updated;
    }

    private ObjectNode createdNode(String nodeId, ObjectNode operation) {
        String action = text(operation, "action");
        String nodeKind = text(operation, "nodeKind");
        if ("CREATE_NODE".equals(action) && !"CAPABILITY".equals(nodeKind)) {
            throw invalid("CREATE_NODE는 역량 노드만 만들 수 있습니다.");
        }
        ObjectNode node = objectMapper.createObjectNode();
        node.put("nodeId", nodeId);
        node.put("nodeKind", nodeKind);
        node.put("title", text(operation, "title"));
        for (String field : List.of(
                "canonicalKey", "technologyKey", "graphNodeVersion", "verificationMethods",
                "objective", "excludedScope",
                "completionPolicy",
                "provisionalCandidateId", "targetRef", "scopeDefinition",
                "projectSpec", "gateSpec", "opportunitySpec", "sectionMemberships")) {
            copyIfPresent(operation, node, field);
        }
        node.put("sectionKey", text(operation, "sectionKey"));
        node.put("progressState", optionalText(operation, "initialProgressState").isBlank()
                ? "NOT_STARTED"
                : text(operation, "initialProgressState"));
        if (operation.path("level").isIntegralNumber()) {
            node.put("level", operation.path("level").intValue());
        }
        node.put("displayRank", 0);
        return node;
    }

    private void mergeSectionMemberships(ObjectNode target, JsonNode additions) {
        Map<String, JsonNode> memberships = new LinkedHashMap<>();
        JsonNode existing = target.path("sectionMemberships");
        if (existing.isArray()) {
            existing.forEach(item -> memberships.put(sectionMembershipKey(item), item.deepCopy()));
        }
        if (additions.isArray()) {
            additions.forEach(item -> memberships.put(sectionMembershipKey(item), item.deepCopy()));
        }
        ArrayNode merged = objectMapper.createArrayNode();
        memberships.values().forEach(merged::add);
        target.set("sectionMemberships", merged);
    }

    private static String sectionMembershipKey(JsonNode value) {
        return optionalText(value, "sectionKey") + "\n"
                + optionalText(value, "chapterKey") + "\n"
                + optionalText(value, "targetRef");
    }

    private List<ObjectNode> careerGraphRelations(
            Map<String, ObjectNode> nodes,
            Map<String, ObjectNode> relations,
            List<String> createdNodeIds
    ) {
        List<ObjectNode> opportunities = nodes.values().stream()
                .filter(node -> "OPPORTUNITY".equals(optionalText(node, "nodeKind")))
                .filter(node -> node.path("opportunitySpec").isObject())
                .filter(node -> node.path("opportunitySpec").path("minimumExperienceMonths").isIntegralNumber())
                .toList();
        List<ObjectNode> result = new ArrayList<>();
        for (ObjectNode relation : relations.values()) {
            if (!"REQUIRES_GATE".equals(optionalText(relation, "relationType"))) {
                continue;
            }
            ObjectNode gate = nodes.get(optionalText(relation, "fromNodeId"));
            ObjectNode target = nodes.get(optionalText(relation, "toNodeId"));
            if (gate == null || target == null
                    || !"EXPERIENCE".equals(gate.path("gateSpec").path("gateType").stringValue(""))
                    || !target.path("opportunitySpec").isObject()) {
                continue;
            }
            JsonNode targetSpec = target.path("opportunitySpec");
            if (!targetSpec.path("minimumExperienceMonths").isIntegralNumber()) {
                continue;
            }
            int targetMonths = targetSpec.path("minimumExperienceMonths").intValue();
            if (targetMonths <= 0) {
                continue;
            }
            String family = targetSpec.path("roleFamily").stringValue("");
            String specialization = targetSpec.path("roleSpecialization").stringValue("");
            List<ObjectNode> entryOptions = new ArrayList<>();
            for (ObjectNode opportunity : opportunities) {
                if (optionalText(opportunity, "nodeId").equals(optionalText(target, "nodeId"))) {
                    continue;
                }
                JsonNode spec = opportunity.path("opportunitySpec");
                int months = spec.path("minimumExperienceMonths").intValue();
                if (family.equals(spec.path("roleFamily").stringValue(""))
                        && specialization.equals(spec.path("roleSpecialization").stringValue(""))
                        && months == 0) {
                    entryOptions.add(opportunity);
                }
            }

            String canonicalRoleId = targetSpec.path("canonicalRoleId").stringValue("");
            String roleIdentity = canonicalRoleId.isBlank()
                    ? family + ":" + specialization
                    : canonicalRoleId;
            String sectionKey = text(target, "sectionKey");
            String employmentTarget = "employment:" + roleIdentity;
            String employmentId = stableId("employment", employmentTarget);
            ObjectNode employment = nodes.get(employmentId);
            if (employment == null) {
                employment = objectMapper.createObjectNode();
                employment.put("nodeId", employmentId);
                employment.put("nodeKind", "EMPLOYMENT_EVENT");
                employment.put("title", "관련 " + specialization + " 직무 취업");
                employment.put("targetRef", employmentTarget);
                employment.put("sectionKey", sectionKey);
                employment.put("progressState", "NOT_STARTED");
                employment.put(
                        "scopeDefinition",
                        "지원이나 프로젝트 완료와 구분되는 실제 관련 직무 취업 사건입니다. "
                                + "근무 증거가 확인되기 전에는 경력이 시작되지 않습니다."
                );
                employment.put("displayRank", 0);
                nodes.put(employmentId, employment);
                createdNodeIds.add(employmentId);
            }
            ObjectNode employmentSpec = employment.path("employmentSpec").isObject()
                    ? ((ObjectNode) employment.path("employmentSpec")).deepCopy()
                    : objectMapper.createObjectNode();
            employmentSpec.put("roleFamily", family);
            employmentSpec.put("roleSpecialization", specialization);
            if (!canonicalRoleId.isBlank()) {
                employmentSpec.put("canonicalRoleId", canonicalRoleId);
            }
            if (!employmentSpec.path("evidenceState").isString()) {
                employmentSpec.put("evidenceState", "UNKNOWN");
            }
            Set<String> sourceOpportunityIds = new TreeSet<>();
            if (employmentSpec.path("sourceOpportunityNodeIds").isArray()) {
                employmentSpec.path("sourceOpportunityNodeIds").forEach(value -> {
                    if (value.isString()) {
                        sourceOpportunityIds.add(value.stringValue());
                    }
                });
            }
            entryOptions.forEach(value -> sourceOpportunityIds.add(text(value, "nodeId")));
            employmentSpec.set("sourceOpportunityNodeIds", strings(new ArrayList<>(sourceOpportunityIds)));
            employment.set("employmentSpec", employmentSpec);

            Integer maximumMonths = targetSpec.path("maximumExperienceMonths").isIntegralNumber()
                    ? targetSpec.path("maximumExperienceMonths").intValue()
                    : null;
            String intervalTarget = "experience:" + roleIdentity + ":" + targetMonths + ":"
                    + (maximumMonths == null ? "open" : maximumMonths);
            String intervalId = stableId("experience", intervalTarget);
            ObjectNode interval = nodes.get(intervalId);
            if (interval == null) {
                interval = objectMapper.createObjectNode();
                interval.put("nodeId", intervalId);
                interval.put("nodeKind", "EXPERIENCE_INTERVAL");
                interval.put("title", experienceTitle(targetMonths, maximumMonths));
                interval.put("targetRef", intervalTarget);
                interval.put("sectionKey", sectionKey);
                interval.put("progressState", "NOT_STARTED");
                interval.put(
                        "scopeDefinition",
                        "실제 관련 직무 취업 뒤 근무 증거로 누적하는 경력 구간입니다. "
                                + "프로젝트 완료나 지원만으로는 누적되지 않습니다."
                );
                interval.put("displayRank", 0);
                nodes.put(intervalId, interval);
                createdNodeIds.add(intervalId);
            }
            ObjectNode intervalSpec = interval.path("experienceIntervalSpec").isObject()
                    ? ((ObjectNode) interval.path("experienceIntervalSpec")).deepCopy()
                    : objectMapper.createObjectNode();
            intervalSpec.put("roleFamily", family);
            intervalSpec.put("roleSpecialization", specialization);
            if (!canonicalRoleId.isBlank()) {
                intervalSpec.put("canonicalRoleId", canonicalRoleId);
            }
            intervalSpec.put("minimumMonths", targetMonths);
            if (maximumMonths == null) {
                intervalSpec.putNull("maximumMonths");
            } else {
                intervalSpec.put("maximumMonths", maximumMonths);
            }
            if (!intervalSpec.path("evidenceState").isString()) {
                intervalSpec.put("evidenceState", "UNKNOWN");
            }
            if (!intervalSpec.has("accruedMonths")) {
                intervalSpec.putNull("accruedMonths");
            }
            interval.set("experienceIntervalSpec", intervalSpec);

            for (ObjectNode previous : entryOptions) {
                String fromNodeId = text(previous, "nodeId");
                ObjectNode created = objectMapper.createObjectNode();
                created.put("relationId", stableId("career-entry", fromNodeId, employmentId));
                created.put("fromNodeId", fromNodeId);
                created.put("toNodeId", employmentId);
                created.put("relationType", "POTENTIAL_CAREER_ENTRY");
                created.set("conditions", objectMapper.createArrayNode());
                created.put(
                        "reason",
                        "This is one possible entry opportunity for related employment; "
                                + "the opportunity itself does not prove employment."
                );
                result.add(created);
            }

            result.add(careerRelation(
                    "experience-start",
                    employmentId,
                    intervalId,
                    "STARTS_EXPERIENCE",
                    "Verified related employment starts this experience interval."
            ));
            result.add(careerRelation(
                    "experience-gate",
                    intervalId,
                    text(gate, "nodeId"),
                    "SATISFIES_EXPERIENCE_GATE",
                    "Only verified related work experience can satisfy the formal experience gate."
            ));
        }
        return result;
    }

    private ObjectNode careerRelation(
            String idKind,
            String fromNodeId,
            String toNodeId,
            String relationType,
            String reason
    ) {
        ObjectNode relation = objectMapper.createObjectNode();
        relation.put("relationId", stableId(idKind, fromNodeId, toNodeId));
        relation.put("fromNodeId", fromNodeId);
        relation.put("toNodeId", toNodeId);
        relation.put("relationType", relationType);
        relation.set("conditions", objectMapper.createArrayNode());
        relation.put("reason", reason);
        return relation;
    }

    private static String experienceTitle(int minimumMonths, Integer maximumMonths) {
        if (maximumMonths != null && minimumMonths % 12 == 0 && maximumMonths % 12 == 0) {
            return "관련 실무 경력 " + minimumMonths / 12 + "~" + maximumMonths / 12 + "년";
        }
        if (minimumMonths % 12 == 0) {
            return "관련 실무 경력 " + minimumMonths / 12 + "년";
        }
        return "관련 실무 경력 " + minimumMonths + "개월";
    }

    private Map<String, Integer> displayRanks(
            Map<String, ObjectNode> nodes,
            Map<String, ObjectNode> relations
    ) {
        Map<String, Set<String>> incoming = new HashMap<>();
        Map<String, Set<String>> outgoing = new HashMap<>();
        nodes.keySet().forEach(nodeId -> {
            incoming.put(nodeId, new HashSet<>());
            outgoing.put(nodeId, new HashSet<>());
        });
        for (ObjectNode relation : relations.values()) {
            validateRelationEndpoints(relation, nodes);
            if (!BLOCKING_RELATIONS.contains(text(relation, "relationType"))) {
                continue;
            }
            String from = text(relation, "fromNodeId");
            String to = text(relation, "toNodeId");
            incoming.get(to).add(from);
            outgoing.get(from).add(to);
        }

        TreeSet<String> ready = new TreeSet<>();
        incoming.forEach((nodeId, values) -> {
            if (values.isEmpty()) {
                ready.add(nodeId);
            }
        });
        Map<String, Integer> ranks = new HashMap<>();
        ready.forEach(nodeId -> ranks.put(nodeId, 0));
        int visited = 0;
        while (!ready.isEmpty()) {
            String nodeId = ready.pollFirst();
            visited++;
            for (String target : new TreeSet<>(outgoing.get(nodeId))) {
                ranks.put(target, Math.max(ranks.getOrDefault(target, 0), ranks.get(nodeId) + 1));
                incoming.get(target).remove(nodeId);
                if (incoming.get(target).isEmpty()) {
                    ready.add(target);
                }
            }
        }
        if (visited != nodes.size()) {
            throw failure(
                    "V3_ROADMAP_CYCLE",
                    "로드맵의 필수 진행 관계에 순환이 있어 적용할 수 없습니다."
            );
        }
        return ranks;
    }

    private void validateRelationEndpoints(ObjectNode relation, Map<String, ObjectNode> nodes) {
        String from = text(relation, "fromNodeId");
        String to = text(relation, "toNodeId");
        if (from.equals(to) || !nodes.containsKey(from) || !nodes.containsKey(to)) {
            throw invalid("지도 연결이 존재하지 않는 노드를 참조합니다.");
        }
    }

    private String semanticKey(ObjectNode relation) {
        return semanticKey(
                text(relation, "fromNodeId"),
                text(relation, "toNodeId"),
                text(relation, "relationType")
        );
    }

    private static String semanticKey(String from, String to, String type) {
        return from + "\n" + to + "\n" + type;
    }

    private String stableId(String kind, String... parts) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] hash = digest.digest(String.join("\n", parts).getBytes(StandardCharsets.UTF_8));
            StringBuilder value = new StringBuilder(kind).append('-');
            for (int index = 0; index < 8; index++) {
                value.append(String.format("%02x", hash[index]));
            }
            return value.toString();
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("SHA-256 is unavailable", impossible);
        }
    }

    private ArrayNode toArray(List<ObjectNode> values) {
        ArrayNode result = objectMapper.createArrayNode();
        values.forEach(result::add);
        return result;
    }

    private ArrayNode strings(List<String> values) {
        ArrayNode result = objectMapper.createArrayNode();
        values.forEach(result::add);
        return result;
    }

    private static Set<String> stringSet(JsonNode value) {
        Set<String> result = new TreeSet<>();
        if (!value.isArray()) {
            return result;
        }
        value.forEach(item -> {
            if (item.isString() && !item.stringValue("").isBlank()) {
                result.add(item.stringValue());
            }
        });
        return result;
    }

    private static void putIfNonBlank(ObjectNode source, ObjectNode target, String field) {
        String value = optionalText(source, field);
        if (!value.isBlank()) {
            target.put(field, value);
        }
    }

    private static void copyIfPresent(ObjectNode source, ObjectNode target, String field) {
        JsonNode value = source.path(field);
        if (!value.isMissingNode() && !value.isNull()) {
            target.set(field, value.deepCopy());
        }
    }

    private static ObjectNode requireObject(JsonNode value, String label) {
        return object(value, label);
    }

    private static ObjectNode object(JsonNode value, String label) {
        if (value == null || !value.isObject()) {
            throw invalid(label + " 형식이 올바르지 않습니다.");
        }
        return (ObjectNode) value;
    }

    private static ArrayNode array(JsonNode value, String field) {
        JsonNode result = value.path(field);
        if (!result.isArray()) {
            throw invalid(field + " 배열이 없습니다.");
        }
        return (ArrayNode) result;
    }

    private static String text(JsonNode value, String field) {
        String result = optionalText(value, field);
        if (result.isBlank()) {
            throw invalid(field + " 값이 없습니다.");
        }
        return result;
    }

    private static String optionalText(JsonNode value, String field) {
        JsonNode result = value.path(field);
        return result.isString() ? result.stringValue("") : "";
    }

    private static long integral(JsonNode value, String field) {
        JsonNode result = value.path(field);
        if (!result.isIntegralNumber() || result.longValue() < 0) {
            throw invalid(field + " 버전 값이 올바르지 않습니다.");
        }
        return result.longValue();
    }

    private static ApiException invalid(String message) {
        return failure("V3_ROADMAP_INVALID_PROPOSAL", message);
    }

    private static ApiException failure(String code, String message) {
        return new ApiException(HttpStatus.CONFLICT, code, message);
    }
}
