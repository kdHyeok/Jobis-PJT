package com.jobiss.analysis.v3;

import com.jobiss.db.RlsTransactionExecutor;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.Locale;
import java.util.UUID;

@Component
public class V3AnalysisRequestFactory {

    private final RlsTransactionExecutor rls;
    private final V3AtomicCapabilityStateService atomicCapabilityStateService;
    private final V3ProjectProgressService projectProgressService;
    private final V3CareerProgressOverlay careerProgressOverlay;
    private final ObjectMapper objectMapper;

    public V3AnalysisRequestFactory(
            RlsTransactionExecutor rls,
            V3AtomicCapabilityStateService atomicCapabilityStateService,
            V3ProjectProgressService projectProgressService,
            V3CareerProgressOverlay careerProgressOverlay,
            ObjectMapper objectMapper
    ) {
        this.rls = rls;
        this.atomicCapabilityStateService = atomicCapabilityStateService;
        this.projectProgressService = projectProgressService;
        this.careerProgressOverlay = careerProgressOverlay;
        this.objectMapper = objectMapper;
    }

    public AnalysisContext create(UUID userId, UUID analysisJobId) {
        return rls.write(userId, jdbc -> create(jdbc, userId, analysisJobId));
    }

    public JsonNode currentRoadmap(UUID userId) {
        return rls.read(userId, jdbc -> {
            long version = currentRoadmapVersion(jdbc, userId);
            return currentRoadmap(jdbc, userId, version);
        });
    }

    JsonNode currentRoadmapInTransaction(JdbcClient jdbc, UUID userId) {
        long version = currentRoadmapVersion(jdbc, userId);
        return currentRoadmap(jdbc, userId, version);
    }

    private AnalysisContext create(
            JdbcClient jdbc,
            UUID userId,
            UUID analysisJobId
    ) {
        StoredInputs inputs = jdbc.sql("""
                        select
                            job.id,
                            job.posting_id,
                            job.question_count,
                            source.id as source_id,
                            source.source_document_id,
                            source.document::text as source_document,
                            snapshot.id as snapshot_id,
                            snapshot.verified_snapshot_id,
                            snapshot.snapshot_hash,
                            snapshot.snapshot::text as verified_snapshot,
                            coalesce(
                                (
                                    select version_number
                                    from ai_v3_roadmap_versions
                                    where status = 'PUBLISHED'
                                    limit 1
                                ),
                                (
                                    select version_number
                                    from roadmap_versions
                                    where status = 'PUBLISHED'
                                    limit 1
                                ),
                                (
                                    select version
                                    from career_graphs
                                    where user_id = :userId
                                ),
                                0
                            ) as roadmap_version,
                            coalesce(run.evidence_question_count, 0) as evidence_question_count,
                            coalesce(
                                run.structured_posting,
                                shared_structure.structured_posting
                            )::text as structured_posting_checkpoint
                        from analysis_jobs job
                        join job_postings posting on posting.id = job.posting_id
                        join ai_v3_source_documents source
                          on source.id = coalesce(
                              job.v3_source_id,
                              (
                                  select fallback_source.id
                                  from ai_v3_source_documents fallback_source
                                  where fallback_source.posting_id = posting.id
                                  order by fallback_source.updated_at desc,
                                           fallback_source.created_at desc
                                  limit 1
                              )
                          )
                        join ai_v3_verified_posting_snapshots snapshot
                          on snapshot.id = coalesce(
                              job.v3_snapshot_id,
                              (
                                  select fallback_snapshot.id
                                  from ai_v3_verified_posting_snapshots fallback_snapshot
                                  where fallback_snapshot.source_id = source.id
                                  order by fallback_snapshot.created_at desc
                                  limit 1
                              )
                          )
                        left join ai_v3_analysis_runs run
                          on run.analysis_job_id = job.id
                        left join ai_v3_posting_structure_cache shared_structure
                          on shared_structure.snapshot_hash = snapshot.snapshot_hash
                         and shared_structure.contract_version = 'jobis.ai.v3alpha1'
                         and shared_structure.invalidated_at is null
                        where job.id = :analysisJobId
                          and job.analysis_provider = 'UNIFIED'
                        """)
                .param("userId", userId)
                .param("analysisJobId", analysisJobId)
                .query((rs, rowNum) -> new StoredInputs(
                        rs.getObject("id", UUID.class),
                        rs.getObject("posting_id", UUID.class),
                        rs.getInt("question_count"),
                        rs.getObject("source_id", UUID.class),
                        rs.getString("source_document_id"),
                        readJson(rs.getString("source_document")),
                        rs.getObject("snapshot_id", UUID.class),
                        rs.getString("verified_snapshot_id"),
                        rs.getString("snapshot_hash"),
                        readJson(rs.getString("verified_snapshot")),
                        rs.getLong("roadmap_version"),
                        rs.getInt("evidence_question_count"),
                        readJson(rs.getString("structured_posting_checkpoint"))
                ))
                .optional()
                .orElseThrow(() -> new IllegalStateException(
                    "Career analysis requires a verified source linked to the analysis job"
                ));

        if (!"VERIFIED".equals(inputs.sourceDocument().path("status").stringValue(""))) {
            throw new IllegalStateException("Career analysis source is not VERIFIED");
        }

        String commonAnalysisId = "common:" + inputs.verifiedSnapshotId();
        String opportunityId = "opportunity:" + inputs.postingId();
        ObjectNode request = objectMapper.createObjectNode();
        request.put("jobId", inputs.jobId().toString());
        request.put("commonAnalysisId", commonAnalysisId);
        request.put("asOfDate", LocalDate.now().toString());
        request.set("sourceDocument", inputs.sourceDocument());
        request.set("verifiedSnapshot", inputs.verifiedSnapshot());
        if (inputs.structuredPostingCheckpoint() != null
                && inputs.structuredPostingCheckpoint().isObject()) {
            ((ObjectNode) inputs.structuredPostingCheckpoint()).put(
                    "verifiedSnapshotId",
                    inputs.verifiedSnapshotId()
            );
            request.set(
                    "structuredPostingCheckpoint",
                    inputs.structuredPostingCheckpoint()
            );
        }
        request.set("clarificationAnswers", clarificationAnswers(jdbc, analysisJobId));
        // 대화 흐름에서 공고 내용을 이미 에이전트가 정리·확인하므로 파이프라인의
        // 별도 원문 확인 게이트(AWAITING_POSTING_CONFIRMATION)는 걸지 않는다.
        request.put("requirePostingConfirmation", false);
        String confirmedReviewId = confirmedPostingReviewId(jdbc, analysisJobId);
        if (confirmedReviewId != null) {
            request.put("confirmedPostingReviewId", confirmedReviewId);
        }
        request.set(
                "userEvidence",
                userEvidence(jdbc, userId, analysisJobId, inputs.roadmapVersion())
        );
        request.set(
                "currentRoadmap",
                projectProgressService.withoutInternalLinkage(
                        currentRoadmap(jdbc, userId, inputs.roadmapVersion())
                )
        );
        ArrayNode approvedRoles = objectMapper.createArrayNode();
        jdbc.sql("""
                        select canonical_role_id, family, specialization
                        from approved_role_catalog
                        where active
                        order by canonical_role_id
                        """)
                .query((rs, rowNum) -> {
                    ObjectNode role = objectMapper.createObjectNode();
                    role.put("canonicalRoleId", rs.getString("canonical_role_id"));
                    role.put("family", rs.getString("family"));
                    role.put("specialization", rs.getString("specialization"));
                    return role;
                }).list().forEach(approvedRoles::add);
        request.set("approvedRoleCatalog", approvedRoles);
        request.put("opportunityId", opportunityId);
        request.put(
                "skipRemainingEvidenceQuestions",
                inputs.evidenceQuestionCount() >= 3
        );

        return new AnalysisContext(
                request,
                inputs.jobId(),
                inputs.postingId(),
                inputs.sourceId(),
                inputs.snapshotId(),
                inputs.snapshotHash(),
                commonAnalysisId,
                opportunityId,
                inputs.roadmapVersion(),
                inputs.questionCount(),
                inputs.evidenceQuestionCount()
        );
    }

    private ArrayNode clarificationAnswers(JdbcClient jdbc, UUID analysisJobId) {
        ArrayNode result = objectMapper.createArrayNode();
        jdbc.sql("""
                        select
                            question_key,
                            input_type,
                            answer_value,
                            answered_at
                        from analysis_questions
                        where analysis_job_id = :analysisJobId
                          and status = 'ANSWERED'
                          and absence_scope = 'NONE'
                          and question_key not like 'posting-review-%'
                        order by ordinal
                        """)
                .param("analysisJobId", analysisJobId)
                .query((rs, rowNum) -> {
                    ObjectNode answer = objectMapper.createObjectNode();
                    answer.put("ambiguityId", rs.getString("question_key"));
                    if ("TEXT".equals(rs.getString("input_type"))) {
                        answer.put("textValue", rs.getString("answer_value"));
                    } else {
                        answer.put("selectedValue", rs.getString("answer_value"));
                    }
                    answer.put(
                            "answeredAt",
                            rs.getObject("answered_at", OffsetDateTime.class).toString()
                    );
                    return answer;
                })
                .list()
                .forEach(result::add);
        return result;
    }

    private String confirmedPostingReviewId(JdbcClient jdbc, UUID analysisJobId) {
        return jdbc.sql("""
                        select question_key
                        from analysis_questions
                        where analysis_job_id = :analysisJobId
                          and status = 'ANSWERED'
                          and question_key like 'posting-review-%'
                          and answer_value = 'CONFIRM'
                        order by ordinal desc
                        limit 1
                        """)
                .param("analysisJobId", analysisJobId)
                .query(String.class)
                .optional()
                .orElse(null);
    }

    private ObjectNode userEvidence(
            JdbcClient jdbc,
            UUID userId,
            UUID analysisJobId,
            long revision
    ) {
        ObjectNode bundle = objectMapper.createObjectNode();
        bundle.put("evidenceSetId", "evidence:" + userId);
        bundle.put("revision", Math.max(0, revision));
        ArrayNode competencies = objectMapper.createArrayNode();
        ArrayNode evidenceItems = objectMapper.createArrayNode();

        jdbc.sql("""
                        select
                            id,
                            canonical_key,
                            title,
                            scope_definition,
                            progress_status::text,
                            verified_level
                        from user_competencies
                        where not exists (
                            select 1
                            from user_atomic_capabilities atomic
                            where atomic.canonical_key = user_competencies.canonical_key
                        )
                        order by canonical_key
                        """)
                .query((rs, rowNum) -> {
                    UUID id = rs.getObject("id", UUID.class);
                    String progress = rs.getString("progress_status");
                    int verifiedLevel = rs.getInt("verified_level");
                    boolean claimed = "IN_PROGRESS".equals(progress)
                            || "COMPLETED".equals(progress);
                    boolean evidenced = "COMPLETED".equals(progress);
                    String evidenceId = "competency:" + id;

                    ObjectNode competency = objectMapper.createObjectNode();
                    competency.put("competencyId", rs.getString("canonical_key"));
                    competency.put("displayName", rs.getString("title"));
                    competency.put("scopeDefinition", rs.getString("scope_definition"));
                    competency.put("claimState", claimed ? "CLAIMED" : "NOT_CLAIMED");
                    competency.put("evidenceState", evidenced ? "EVIDENCED" : "NO_EVIDENCE");
                    competency.put(
                            "verificationState",
                            verifiedLevel > 0 ? "VERIFIED" : "NOT_VERIFIED"
                    );
                    if (claimed) {
                        competency.put("claimedLevel", Math.max(1, verifiedLevel));
                    }
                    competency.put("verifiedLevel", Math.max(0, verifiedLevel));
                    ArrayNode refs = competency.putArray("evidenceRefs");
                    if (evidenced) {
                        refs.add(evidenceId);
                        ObjectNode item = objectMapper.createObjectNode();
                        item.put("evidenceId", evidenceId);
                        item.put("sourceType", "VERIFICATION_ANSWER");
                        item.put("sourceRef", id.toString());
                        item.put("title", rs.getString("title") + " 완료 기록");
                        item.put(
                                "text",
                                rs.getString("scope_definition")
                                        + "에 대한 서비스 내 완료 기록입니다."
                        );
                        item.put(
                                "verificationState",
                                verifiedLevel > 0 ? "VERIFIED" : "NOT_VERIFIED"
                        );
                        item.put("confidence", verifiedLevel > 0 ? 1.0 : 0.7);
                        evidenceItems.add(item);
                    }
                    competency.put(
                            "confidence",
                            verifiedLevel > 0 ? 1.0 : (claimed ? 0.7 : 0.5)
                    );
                    return competency;
                })
                .list()
                .forEach(competencies::add);

        jdbc.sql("""
                        select
                            id,
                            canonical_key,
                            title,
                            scope_definition,
                            progress_state
                        from user_atomic_capabilities
                        order by canonical_key
                        """)
                .query((rs, rowNum) -> {
                    UUID id = rs.getObject("id", UUID.class);
                    String state = rs.getString("progress_state");
                    boolean claimed = !"NOT_STARTED".equals(state);
                    boolean evidenced = "EVIDENCED".equals(state) || "VERIFIED".equals(state);
                    boolean verified = "VERIFIED".equals(state);
                    String evidenceId = "atomic:" + id;

                    ObjectNode competency = objectMapper.createObjectNode();
                    competency.put("competencyId", rs.getString("canonical_key"));
                    competency.put("displayName", rs.getString("title"));
                    competency.put("scopeDefinition", rs.getString("scope_definition"));
                    competency.put("claimState", claimed ? "CLAIMED" : "NOT_CLAIMED");
                    competency.put("evidenceState", evidenced ? "EVIDENCED" : "NO_EVIDENCE");
                    competency.put("verificationState", verified ? "VERIFIED" : "NOT_VERIFIED");
                    if (claimed) {
                        competency.put("claimedLevel", 1);
                    }
                    competency.put("verifiedLevel", verified ? 1 : 0);
                    ArrayNode refs = competency.putArray("evidenceRefs");
                    if (evidenced) {
                        refs.add(evidenceId);
                        ObjectNode item = objectMapper.createObjectNode();
                        item.put("evidenceId", evidenceId);
                        item.put("sourceType", "VERIFICATION_ANSWER");
                        item.put("sourceRef", id.toString());
                        item.put("title", rs.getString("title") + " 원자 역량 검증 기록");
                        item.put("text", rs.getString("scope_definition"));
                        item.put("verificationState", verified ? "VERIFIED" : "NOT_VERIFIED");
                        item.put("confidence", verified ? 1.0 : 0.8);
                        evidenceItems.add(item);
                    }
                    competency.put("confidence", verified ? 1.0 : (claimed ? 0.8 : 0.5));
                    return competency;
                })
                .list()
                .forEach(competencies::add);

        jdbc.sql("""
                        select id, kind, title, description
                        from career_fragments
                        where review_status = 'CONFIRMED'
                          and archived_at is null
                        order by updated_at desc
                        limit 500
                        """)
                .query((rs, rowNum) -> {
                    ObjectNode item = objectMapper.createObjectNode();
                    item.put("evidenceId", rs.getObject("id", UUID.class).toString());
                    item.put(
                            "sourceType",
                            "PROJECT".equalsIgnoreCase(rs.getString("kind"))
                                    ? "PROJECT"
                                    : "CAREER_FRAGMENT"
                    );
                    item.put("sourceRef", rs.getObject("id", UUID.class).toString());
                    item.put("title", rs.getString("title"));
                    item.put(
                            "text",
                            nonBlank(rs.getString("description"), rs.getString("title"))
                    );
                    item.put("verificationState", "NOT_VERIFIED");
                    item.put("confidence", 0.7);
                    return item;
                })
                .list()
                .forEach(evidenceItems::add);

        bundle.set("competencies", competencies);
        bundle.set("evidenceItems", evidenceItems);
        bundle.set("formalFacts", objectMapper.createArrayNode());
        bundle.set(
                "requirementSelfReports",
                requirementSelfReports(jdbc, analysisJobId)
        );
        return bundle;
    }

    private ArrayNode requirementSelfReports(JdbcClient jdbc, UUID analysisJobId) {
        ArrayNode result = objectMapper.createArrayNode();
        jdbc.sql("""
                        select
                            requirement.requirement_id,
                            question.answer_value,
                            question.answer_status,
                            question.answered_at
                        from analysis_questions question
                        cross join lateral jsonb_array_elements_text(
                            question.related_requirement_ids
                        ) as requirement(requirement_id)
                        where question.analysis_job_id = :analysisJobId
                          and question.status = 'ANSWERED'
                          and question.absence_scope = 'REQUIREMENTS'
                        order by question.ordinal, requirement.requirement_id
                        """)
                .param("analysisJobId", analysisJobId)
                .query((rs, rowNum) -> {
                    ObjectNode report = objectMapper.createObjectNode();
                    report.put("requirementId", rs.getString("requirement_id"));
                    report.put(
                            "claimState",
                            requirementClaimState(
                                    rs.getString("answer_value"),
                                    rs.getString("answer_status")
                            )
                    );
                    report.put(
                            "answeredAt",
                            rs.getObject("answered_at", OffsetDateTime.class).toString()
                    );
                    report.set("evidenceRefs", objectMapper.createArrayNode());
                    return report;
                })
                .list()
                .forEach(result::add);
        return result;
    }

    static String requirementClaimState(String answerValue, String answerStatus) {
        if ("CONFIRMED_ABSENT".equals(answerStatus)
                || "claim-absent".equals(answerValue)) {
            return "NOT_CLAIMED";
        }
        if ("claim-present".equals(answerValue)) {
            return "CLAIMED";
        }
        return "UNKNOWN";
    }

    private ObjectNode currentRoadmap(
            JdbcClient jdbc,
            UUID userId,
            long roadmapVersion
    ) {
        String published = jdbc.sql("""
                        select snapshot::text
                        from ai_v3_roadmap_versions
                        where status = 'PUBLISHED'
                        limit 1
                        """)
                .query(String.class)
                .optional()
                .orElse(null);
        if (published != null) {
            JsonNode stored = readJson(published);
            if (stored == null || !stored.isObject()) {
                throw new IllegalStateException("저장된 커리어 그래프 스냅샷이 올바르지 않습니다.");
            }
            JsonNode overlaid = atomicCapabilityStateService.overlay(jdbc, stored);
            overlaid = projectProgressService.overlay(jdbc, overlaid);
            return (ObjectNode) careerProgressOverlay.overlay(jdbc, overlaid);
        }
        ObjectNode snapshot = objectMapper.createObjectNode();
        snapshot.put("roadmapVersion", Math.max(0, roadmapVersion));
        ArrayNode nodes = objectMapper.createArrayNode();
        int[] displayRank = {0};
        jdbc.sql("""
                        select
                            id,
                            canonical_key,
                            title,
                            domain,
                            scope_definition,
                            progress_status::text,
                            verified_level
                        from user_competencies
                        where roadmap_eligible
                        order by default_stage, canonical_key
                        """)
                .query((rs, rowNum) -> {
                    ObjectNode node = objectMapper.createObjectNode();
                    node.put("nodeId", rs.getObject("id", UUID.class).toString());
                    node.put("nodeKind", "CAPABILITY");
                    node.put("title", rs.getString("title"));
                    node.put("canonicalKey", rs.getString("canonical_key"));
                    node.put("sectionKey", sectionKey(rs.getString("domain")));
                    node.put(
                            "progressState",
                            roadmapProgress(
                                    rs.getString("progress_status"),
                                    rs.getInt("verified_level")
                            )
                    );
                    node.put("scopeDefinition", rs.getString("scope_definition"));
                    node.put("level", Math.max(1, rs.getInt("verified_level")));
                    node.put("displayRank", displayRank[0]++);
                    return node;
                })
                .list()
                .forEach(nodes::add);
        snapshot.set("nodes", nodes);
        snapshot.set("relations", objectMapper.createArrayNode());
        return snapshot;
    }

    private long currentRoadmapVersion(JdbcClient jdbc, UUID userId) {
        return jdbc.sql("""
                        select coalesce(
                            (
                                select version_number
                                from ai_v3_roadmap_versions
                                where status = 'PUBLISHED'
                                limit 1
                            ),
                            (
                                select version_number
                                from roadmap_versions
                                where status = 'PUBLISHED'
                                limit 1
                            ),
                            (
                                select version
                                from career_graphs
                                where user_id = :userId
                            ),
                            0
                        )
                        """)
                .param("userId", userId)
                .query(Long.class)
                .single();
    }

    private static String sectionKey(String domain) {
        String normalized = nonBlank(domain, "common")
                .toLowerCase(Locale.ROOT)
                .replaceAll("[^a-z0-9]+", "-")
                .replaceAll("(^-+|-+$)", "");
        return "section." + (normalized.isBlank() ? "common" : normalized);
    }

    private static String roadmapProgress(String progress, int verifiedLevel) {
        if ("COMPLETED".equals(progress)) {
            return verifiedLevel > 0 ? "VERIFIED" : "EVIDENCED";
        }
        if ("IN_PROGRESS".equals(progress)) {
            return "CLAIMED";
        }
        return "NOT_STARTED";
    }

    private static String nonBlank(String value, String fallback) {
        return value == null || value.isBlank() ? fallback : value.trim();
    }

    private JsonNode readJson(String value) {
        return value == null ? null : objectMapper.readTree(value);
    }

    public record AnalysisContext(
            JsonNode request,
            UUID jobId,
            UUID postingId,
            UUID sourceId,
            UUID verifiedSnapshotId,
            String snapshotHash,
            String commonAnalysisId,
            String opportunityId,
            long basedOnRoadmapVersion,
            int questionCount,
            int evidenceQuestionCount
    ) {
    }

    private record StoredInputs(
            UUID jobId,
            UUID postingId,
            int questionCount,
            UUID sourceId,
            String sourceDocumentId,
            JsonNode sourceDocument,
            UUID snapshotId,
            String verifiedSnapshotId,
            String snapshotHash,
            JsonNode verifiedSnapshot,
            long roadmapVersion,
            int evidenceQuestionCount,
            JsonNode structuredPostingCheckpoint
    ) {
    }
}
