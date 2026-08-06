package com.jobiss.analysis.v3;

import com.jobiss.common.ApiException;
import com.jobiss.db.RlsTransactionExecutor;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

@Service
public class V3RoadmapService {

    private final RlsTransactionExecutor rls;
    private final V3AnalysisRequestFactory requestFactory;
    private final V3RoadmapCompiler compiler;
    private final V3AtomicCapabilityStateService atomicCapabilityStateService;
    private final V3ProjectProgressService projectProgressService;
    private final V3CareerProgressOverlay careerProgressOverlay;
    private final ObjectMapper objectMapper;

    public V3RoadmapService(
            RlsTransactionExecutor rls,
            V3AnalysisRequestFactory requestFactory,
            V3RoadmapCompiler compiler,
            V3AtomicCapabilityStateService atomicCapabilityStateService,
            V3ProjectProgressService projectProgressService,
            V3CareerProgressOverlay careerProgressOverlay,
            ObjectMapper objectMapper
    ) {
        this.rls = rls;
        this.requestFactory = requestFactory;
        this.compiler = compiler;
        this.atomicCapabilityStateService = atomicCapabilityStateService;
        this.projectProgressService = projectProgressService;
        this.careerProgressOverlay = careerProgressOverlay;
        this.objectMapper = objectMapper;
    }

    public Workspace get(UUID userId) {
        return rls.read(userId, jdbc -> new Workspace(
                requestFactory.currentRoadmapInTransaction(jdbc, userId),
                latestDraft(jdbc)
        ));
    }

    public ProposalView proposal(UUID userId, UUID proposalId) {
        return rls.read(userId, jdbc -> load(jdbc, proposalId, false));
    }

    public PreviewResult preview(UUID userId, UUID proposalId) {
        return rls.write(userId, jdbc -> {
            ProposalView stored = load(jdbc, proposalId, true);
            requireDraft(stored);
            JsonNode current = requestFactory.currentRoadmapInTransaction(jdbc, userId);
            JsonNode preview = compiler.compile(current, stored.proposal());
            int updated = jdbc.sql("""
                            update ai_v3_roadmap_proposals
                            set preview_snapshot = cast(:preview as jsonb), updated_at = now()
                            where id = :proposalId
                              and status = 'DRAFT'
                            """)
                    .param("preview", writeJson(preview))
                    .param("proposalId", proposalId)
                    .update();
            if (updated != 1) {
                throw staleState();
            }
            return new PreviewResult(proposalId, "DRAFT", preview);
        });
    }

    public ApplyResult apply(UUID userId, UUID proposalId, long expectedRoadmapVersion) {
        return rls.write(userId, jdbc -> {
            lockUserRoadmap(jdbc, userId);
            ProposalView stored = load(jdbc, proposalId, true);
            requireDraft(stored);
            JsonNode current = requestFactory.currentRoadmapInTransaction(jdbc, userId);
            long currentVersion = current.path("roadmapVersion").longValue();
            if (expectedRoadmapVersion != currentVersion
                    || stored.basedOnRoadmapVersion() != currentVersion) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "V3_ROADMAP_STALE_PROPOSAL",
                        "현재 지도 버전이 바뀌었습니다. 최신 상태에서 다시 미리보기 해주세요."
                );
            }

            JsonNode preview = compiler.compile(current, stored.proposal());
            JsonNode snapshot = preview.path("snapshot");
            long nextVersion = preview.path("proposedRoadmapVersion").longValue();
            atomicCapabilityStateService.synchronize(
                    jdbc,
                    userId,
                    snapshot,
                    stored.proposal().path("capabilityGraphVersion").stringValue("unknown")
            );
            snapshot = atomicCapabilityStateService.overlay(jdbc, snapshot);
            snapshot = projectProgressService.synchronizeAndOverlay(jdbc, userId, snapshot);
            snapshot = careerProgressOverlay.overlay(jdbc, snapshot);
            JsonNode canonicalSnapshot = projectProgressService.withoutInternalLinkage(snapshot);
            if (preview instanceof tools.jackson.databind.node.ObjectNode previewObject) {
                previewObject.set("snapshot", snapshot);
            }
            jdbc.sql("""
                            update ai_v3_roadmap_versions
                            set status = 'SUPERSEDED'
                            where status = 'PUBLISHED'
                            """)
                    .update();
            UUID publicationId = jdbc.sql("""
                            insert into ai_v3_roadmap_versions (
                                user_id,
                                proposal_id,
                                version_number,
                                status,
                                snapshot,
                                published_at
                            )
                            values (
                                :userId,
                                :proposalId,
                                :versionNumber,
                                'PUBLISHED',
                                cast(:snapshot as jsonb),
                                now()
                            )
                            returning id
                            """)
                    .param("userId", userId)
                    .param("proposalId", proposalId)
                    .param("versionNumber", nextVersion)
                    .param("snapshot", writeJson(canonicalSnapshot))
                    .query(UUID.class)
                    .single();
            int updated = jdbc.sql("""
                            update ai_v3_roadmap_proposals
                            set
                                status = 'APPLIED',
                                preview_snapshot = cast(:preview as jsonb),
                                applied_at = now(),
                                updated_at = now()
                            where id = :proposalId
                              and status = 'DRAFT'
                            """)
                    .param("preview", writeJson(preview))
                    .param("proposalId", proposalId)
                    .update();
            if (updated != 1) {
                throw staleState();
            }
            return new ApplyResult(
                    proposalId,
                    publicationId,
                    nextVersion,
                    "PUBLISHED",
                    snapshot
            );
        });
    }

    public CancelResult cancel(UUID userId, UUID proposalId) {
        return rls.write(userId, jdbc -> {
            ProposalView stored = load(jdbc, proposalId, true);
            requireDraft(stored);
            int updated = jdbc.sql("""
                            update ai_v3_roadmap_proposals
                            set status = 'CANCELLED', cancelled_at = now(), updated_at = now()
                            where id = :proposalId
                              and status = 'DRAFT'
                            """)
                    .param("proposalId", proposalId)
                    .update();
            if (updated != 1) {
                throw staleState();
            }
            return new CancelResult(
                    proposalId,
                    "CANCELLED",
                    requestFactory.currentRoadmapInTransaction(jdbc, userId)
            );
        });
    }

    public ProposalView createTargetRemovalDraft(UUID userId, String postingId) {
        return rls.write(userId, jdbc -> {
            lockUserRoadmap(jdbc, userId);
            ensureNoDraft(jdbc);
            JsonNode current = requestFactory.currentRoadmapInTransaction(jdbc, userId);
            String targetRef = findOpportunityTargetRef(current, postingId);
            return storeLifecycleDraft(
                    jdbc,
                    userId,
                    current,
                    List.of(targetRef),
                    "REMOVE_TARGET"
            );
        });
    }

    public ProposalView createResetDraft(UUID userId) {
        return rls.write(userId, jdbc -> {
            lockUserRoadmap(jdbc, userId);
            ensureNoDraft(jdbc);
            JsonNode current = requestFactory.currentRoadmapInTransaction(jdbc, userId);
            List<String> targets = new ArrayList<>();
            for (JsonNode node : current.path("nodes")) {
                if (!"OPPORTUNITY".equals(node.path("nodeKind").stringValue(""))) {
                    continue;
                }
                String targetRef = node.path("targetRef").stringValue("");
                if (!targetRef.isBlank()) {
                    targets.add(targetRef);
                }
            }
            if (targets.isEmpty()) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "V3_ROADMAP_NO_TARGETS",
                        "초기화할 목표 공고가 없습니다."
                );
            }
            return storeLifecycleDraft(jdbc, userId, current, targets, "RESET_TARGETS");
        });
    }

    public List<VersionView> versions(UUID userId) {
        return rls.read(userId, jdbc -> jdbc.sql("""
                        select id, version_number, status, snapshot::text, created_at, published_at
                        from ai_v3_roadmap_versions
                        order by version_number desc
                        """)
                .query((rs, rowNum) -> {
                    JsonNode snapshot = readJson(rs.getString("snapshot"));
                    long targetCount = java.util.stream.StreamSupport
                            .stream(snapshot.path("nodes").spliterator(), false)
                            .filter(node -> "OPPORTUNITY".equals(
                                    node.path("nodeKind").stringValue("")))
                            .count();
                    return new VersionView(
                            rs.getObject("id", UUID.class),
                            rs.getLong("version_number"),
                            rs.getString("status"),
                            targetCount,
                            rs.getObject("created_at", OffsetDateTime.class),
                            rs.getObject("published_at", OffsetDateTime.class)
                    );
                })
                .list());
    }

    public ApplyResult restoreVersion(UUID userId, UUID versionId) {
        return rls.write(userId, jdbc -> {
            lockUserRoadmap(jdbc, userId);
            JsonNode current = requestFactory.currentRoadmapInTransaction(jdbc, userId);
            long nextVersion = current.path("roadmapVersion").longValue() + 1;
            JsonNode source = jdbc.sql("""
                            select snapshot::text
                            from ai_v3_roadmap_versions
                            where id = :versionId
                            for update
                            """)
                    .param("versionId", versionId)
                    .query(String.class)
                    .optional()
                    .map(this::readJson)
                    .orElseThrow(() -> new ApiException(
                            HttpStatus.NOT_FOUND,
                            "V3_ROADMAP_VERSION_NOT_FOUND",
                            "복원할 로드맵 버전을 찾을 수 없습니다."
                    ));
            ObjectNode restored = ((ObjectNode) source.deepCopy());
            restored.put("roadmapVersion", nextVersion);
            restored = (ObjectNode) atomicCapabilityStateService.overlay(jdbc, restored);
            restored = (ObjectNode) projectProgressService.overlay(jdbc, restored);
            restored = (ObjectNode) careerProgressOverlay.overlay(jdbc, restored);
            JsonNode canonicalRestored = projectProgressService.withoutInternalLinkage(restored);
            jdbc.sql("""
                            update ai_v3_roadmap_versions
                            set status = 'SUPERSEDED'
                            where status = 'PUBLISHED'
                            """)
                    .update();
            UUID publicationId = jdbc.sql("""
                            insert into ai_v3_roadmap_versions (
                                user_id, proposal_id, version_number, status, snapshot, published_at
                            ) values (
                                :userId, null, :versionNumber, 'PUBLISHED', cast(:snapshot as jsonb), now()
                            ) returning id
                            """)
                    .param("userId", userId)
                    .param("versionNumber", nextVersion)
                    .param("snapshot", writeJson(canonicalRestored))
                    .query(UUID.class)
                    .single();
            return new ApplyResult(null, publicationId, nextVersion, "PUBLISHED", restored);
        });
    }

    private ProposalView storeLifecycleDraft(
            JdbcClient jdbc,
            UUID userId,
            JsonNode current,
            List<String> removeTargetRefs,
            String proposalKind
    ) {
        long basedOnVersion = current.path("roadmapVersion").longValue();
        String contractProposalId = "roadmap-lifecycle-" + UUID.randomUUID();
        ObjectNode proposal = objectMapper.createObjectNode();
        proposal.put("contractVersion", "jobis.ai.v3alpha1");
        proposal.put("proposalId", contractProposalId);
        proposal.put("status", "DRAFT");
        proposal.put("basedOnRoadmapVersion", basedOnVersion);
        proposal.set("operations", objectMapper.createArrayNode());
        proposal.set("relations", objectMapper.createArrayNode());
        ArrayNode targets = objectMapper.createArrayNode();
        removeTargetRefs.stream().distinct().sorted().forEach(targets::add);
        proposal.set("removeTargetRefs", targets);
        JsonNode preview = compiler.compile(current, proposal);
        UUID proposalId = jdbc.sql("""
                        insert into ai_v3_roadmap_proposals (
                            user_id, analysis_job_id, proposal_id,
                            based_on_roadmap_version, proposed_roadmap_version,
                            status, proposal_kind, proposal, preview_snapshot
                        ) values (
                            :userId, null, :proposalId,
                            :basedOnVersion, :proposedVersion,
                            'DRAFT', :proposalKind, cast(:proposal as jsonb), cast(:preview as jsonb)
                        ) returning id
                        """)
                .param("userId", userId)
                .param("proposalId", contractProposalId)
                .param("basedOnVersion", basedOnVersion)
                .param("proposedVersion", basedOnVersion + 1)
                .param("proposalKind", proposalKind)
                .param("proposal", writeJson(proposal))
                .param("preview", writeJson(preview))
                .query(UUID.class)
                .single();
        return load(jdbc, proposalId, false);
    }

    private void ensureNoDraft(JdbcClient jdbc) {
        boolean exists = jdbc.sql("""
                        select exists(
                            select 1 from ai_v3_roadmap_proposals where status = 'DRAFT'
                        )
                        """)
                .query(Boolean.class)
                .single();
        if (exists) {
            throw new ApiException(
                    HttpStatus.CONFLICT,
                    "V3_ROADMAP_DRAFT_ALREADY_EXISTS",
                    "먼저 준비 중인 로드맵 초안을 적용하거나 취소해 주세요."
            );
        }
    }

    private static String findOpportunityTargetRef(JsonNode current, String postingId) {
        for (JsonNode node : current.path("nodes")) {
            if (!"OPPORTUNITY".equals(node.path("nodeKind").stringValue(""))) {
                continue;
            }
            String opportunityId = node.path("opportunitySpec").path("opportunityId").stringValue("");
            String targetRef = node.path("targetRef").stringValue("");
            if (postingId.equals(opportunityId)
                    || opportunityId.endsWith(":" + postingId)
                    || postingId.equals(targetRef)
                    || targetRef.endsWith(":" + postingId)) {
                return targetRef;
            }
        }
        throw new ApiException(
                HttpStatus.NOT_FOUND,
                "V3_ROADMAP_TARGET_NOT_FOUND",
                "로드맵에서 해당 목표 공고를 찾을 수 없습니다."
        );
    }

    private ProposalView latestDraft(JdbcClient jdbc) {
        return jdbc.sql("""
                        select
                            id,
                            analysis_job_id,
                            proposal_id,
                            based_on_roadmap_version,
                            proposed_roadmap_version,
                            status,
                            proposal::text,
                            preview_snapshot::text,
                            created_at,
                            updated_at,
                            applied_at,
                            cancelled_at
                        from ai_v3_roadmap_proposals
                        where status = 'DRAFT'
                        order by created_at desc
                        limit 1
                        """)
                .query(this::proposalView)
                .optional()
                .orElse(null);
    }

    private ProposalView load(JdbcClient jdbc, UUID proposalId, boolean forUpdate) {
        String lock = forUpdate ? " for update" : "";
        return jdbc.sql("""
                        select
                            id,
                            analysis_job_id,
                            proposal_id,
                            based_on_roadmap_version,
                            proposed_roadmap_version,
                            status,
                            proposal::text,
                            preview_snapshot::text,
                            created_at,
                            updated_at,
                            applied_at,
                            cancelled_at
                        from ai_v3_roadmap_proposals
                        where id = :proposalId
                        """ + lock)
                .param("proposalId", proposalId)
                .query(this::proposalView)
                .optional()
                .orElseThrow(() -> new ApiException(
                        HttpStatus.NOT_FOUND,
                        "V3_ROADMAP_PROPOSAL_NOT_FOUND",
                        "로드맵 초안을 찾을 수 없습니다."
                ));
    }

    private ProposalView proposalView(java.sql.ResultSet rs, int rowNum) throws java.sql.SQLException {
        return new ProposalView(
                rs.getObject("id", UUID.class),
                rs.getObject("analysis_job_id", UUID.class),
                rs.getString("proposal_id"),
                rs.getLong("based_on_roadmap_version"),
                rs.getLong("proposed_roadmap_version"),
                rs.getString("status"),
                readJson(rs.getString("proposal")),
                readJson(rs.getString("preview_snapshot")),
                rs.getObject("created_at", OffsetDateTime.class),
                rs.getObject("updated_at", OffsetDateTime.class),
                rs.getObject("applied_at", OffsetDateTime.class),
                rs.getObject("cancelled_at", OffsetDateTime.class)
        );
    }

    private void lockUserRoadmap(JdbcClient jdbc, UUID userId) {
        jdbc.sql("select id from users where id = :userId for update")
                .param("userId", userId)
                .query(UUID.class)
                .single();
    }

    private static void requireDraft(ProposalView proposal) {
        if (!"DRAFT".equals(proposal.status())) {
            throw new ApiException(
                    HttpStatus.CONFLICT,
                    "V3_ROADMAP_PROPOSAL_NOT_DRAFT",
                    "이미 적용하거나 취소한 로드맵 초안입니다."
            );
        }
    }

    private static ApiException staleState() {
        return new ApiException(
                HttpStatus.CONFLICT,
                "V3_ROADMAP_PROPOSAL_CHANGED",
                "로드맵 초안 상태가 바뀌었습니다. 새로고침 후 다시 시도해 주세요."
        );
    }

    private String writeJson(JsonNode value) {
        return objectMapper.writeValueAsString(value);
    }

    private JsonNode readJson(String value) {
        return value == null ? null : objectMapper.readTree(value);
    }

    public record Workspace(JsonNode currentRoadmap, ProposalView draftProposal) {
    }

    public record ProposalView(
            UUID id,
            UUID analysisJobId,
            String contractProposalId,
            long basedOnRoadmapVersion,
            long proposedRoadmapVersion,
            String status,
            JsonNode proposal,
            JsonNode preview,
            OffsetDateTime createdAt,
            OffsetDateTime updatedAt,
            OffsetDateTime appliedAt,
            OffsetDateTime cancelledAt
    ) {
    }

    public record PreviewResult(UUID proposalId, String status, JsonNode preview) {
    }

    public record ApplyResult(
            UUID proposalId,
            UUID publicationId,
            long roadmapVersion,
            String status,
            JsonNode roadmap
    ) {
    }

    public record CancelResult(UUID proposalId, String status, JsonNode currentRoadmap) {
    }

    public record VersionView(
            UUID id,
            long versionNumber,
            String status,
            long targetCount,
            OffsetDateTime createdAt,
            OffsetDateTime publishedAt
    ) {
    }
}
