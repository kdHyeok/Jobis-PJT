package com.jobiss.analysis.v3;

import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

import java.time.LocalDate;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Component
public class V3CareerProgressOverlay {

    public JsonNode overlay(JdbcClient jdbc, JsonNode snapshot) {
        if (snapshot == null || !snapshot.isObject()) return snapshot;
        List<Employment> records = jdbc.sql("""
                        select canonical_role_id, role_family, role_specialization,
                               started_on, coalesce(ended_on, current_date) as ended_on,
                               evidence_state
                        from user_employment_records
                        where evidence_state in ('CLAIMED', 'EVIDENCED', 'VERIFIED')
                        """)
                .query((rs, rowNum) -> new Employment(
                        rs.getString("canonical_role_id"), rs.getString("role_family"),
                        rs.getString("role_specialization"),
                        rs.getObject("started_on", LocalDate.class),
                        rs.getObject("ended_on", LocalDate.class),
                        rs.getString("evidence_state")
                )).list();
        ObjectNode result = ((ObjectNode) snapshot).deepCopy();
        Map<String, ObjectNode> byId = new HashMap<>();
        for (JsonNode item : result.path("nodes")) {
            if (item instanceof ObjectNode node) byId.put(node.path("nodeId").stringValue(""), node);
        }
        for (ObjectNode node : byId.values()) {
            if ("EMPLOYMENT_EVENT".equals(node.path("nodeKind").stringValue(""))) {
                ObjectNode spec = object(node, "employmentSpec");
                List<Employment> matching = matching(records, spec);
                String state = strongest(matching);
                spec.put("evidenceState", state);
                node.put("progressState", progress(state));
            } else if ("EXPERIENCE_INTERVAL".equals(node.path("nodeKind").stringValue(""))) {
                ObjectNode spec = object(node, "experienceIntervalSpec");
                List<Employment> matching = matching(records, spec);
                List<Employment> evidenced = matching.stream()
                        .filter(item -> "EVIDENCED".equals(item.state()) || "VERIFIED".equals(item.state()))
                        .toList();
                List<Employment> verified = matching.stream()
                        .filter(item -> "VERIFIED".equals(item.state())).toList();
                int evidencedMonths = accruedMonths(evidenced);
                int verifiedMonths = accruedMonths(verified);
                int minimum = spec.path("minimumMonths").asInt(0);
                JsonNode maximumValue = spec.get("maximumMonths");
                Integer maximum = maximumValue == null || maximumValue.isNull()
                        ? null : maximumValue.asInt();
                spec.put("accruedMonths", evidencedMonths);
                spec.put("verifiedMonths", verifiedMonths);
                spec.put("evidenceState", strongest(matching));
                spec.put("evidenceMinimumSatisfied", evidencedMonths >= minimum);
                spec.put("minimumSatisfied", verifiedMonths >= minimum);
                spec.put("exceedsMaximum", maximum != null && evidencedMonths > maximum);
                node.put("progressState", verifiedMonths >= minimum ? "VERIFIED"
                        : evidencedMonths > 0 ? "EVIDENCED" : "NOT_STARTED");
            }
        }
        for (JsonNode relation : result.path("relations")) {
            if (!"SATISFIES_EXPERIENCE_GATE".equals(relation.path("relationType").stringValue(""))) continue;
            ObjectNode from = byId.get(relation.path("fromNodeId").stringValue(""));
            ObjectNode to = byId.get(relation.path("toNodeId").stringValue(""));
            if (from != null && to != null && "VERIFIED".equals(from.path("progressState").stringValue(""))) {
                to.put("progressState", "VERIFIED");
            }
        }
        return result;
    }

    private static List<Employment> matching(List<Employment> records, JsonNode spec) {
        String canonical = spec.path("canonicalRoleId").stringValue("");
        String family = spec.path("roleFamily").stringValue("");
        String specialization = spec.path("roleSpecialization").stringValue("");
        return records.stream().filter(record -> {
            if (!canonical.isBlank() && record.canonicalRoleId() != null) {
                return canonical.equalsIgnoreCase(record.canonicalRoleId());
            }
            return family.equalsIgnoreCase(record.roleFamily())
                    && specialization.equalsIgnoreCase(record.roleSpecialization());
        }).toList();
    }

    private static String strongest(List<Employment> records) {
        if (records.stream().anyMatch(item -> "VERIFIED".equals(item.state()))) return "VERIFIED";
        if (records.stream().anyMatch(item -> "EVIDENCED".equals(item.state()))) return "EVIDENCED";
        if (records.stream().anyMatch(item -> "CLAIMED".equals(item.state()))) return "CLAIMED";
        return "UNKNOWN";
    }

    private static String progress(String state) {
        return switch (state) {
            case "VERIFIED" -> "VERIFIED";
            case "EVIDENCED" -> "EVIDENCED";
            case "CLAIMED" -> "CLAIMED";
            default -> "NOT_STARTED";
        };
    }

    private static int accruedMonths(List<Employment> records) {
        List<Range> sorted = records.stream()
                .map(item -> new Range(item.startedOn(), item.endedOn()))
                .sorted((left, right) -> left.start().compareTo(right.start()))
                .toList();
        List<Range> merged = new ArrayList<>();
        for (Range range : sorted) {
            if (merged.isEmpty() || range.start().isAfter(merged.get(merged.size() - 1).end().plusDays(1))) {
                merged.add(range);
            } else {
                Range last = merged.remove(merged.size() - 1);
                merged.add(new Range(last.start(), last.end().isAfter(range.end()) ? last.end() : range.end()));
            }
        }
        long months = merged.stream().mapToLong(range -> ChronoUnit.MONTHS.between(
                range.start(), range.end().plusDays(1)
        )).sum();
        return (int) Math.min(Integer.MAX_VALUE, Math.max(0, months));
    }

    private static ObjectNode object(ObjectNode node, String field) {
        if (node.path(field) instanceof ObjectNode value) return value;
        ObjectNode value = node.objectNode();
        node.set(field, value);
        return value;
    }

    private record Employment(String canonicalRoleId, String roleFamily, String roleSpecialization,
                              LocalDate startedOn, LocalDate endedOn, String state) {}
    private record Range(LocalDate start, LocalDate end) {}
}
