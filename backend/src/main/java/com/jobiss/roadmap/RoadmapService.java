package com.jobiss.roadmap;

import com.jobiss.common.ApiException;
import com.jobiss.db.RlsTransactionExecutor;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import tools.jackson.databind.ObjectMapper;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Collectors;

@Service
public class RoadmapService {

    private static final List<String> STAGE_ORDER = List.of(
            "FOUNDATION",
            "WEB",
            "LANGUAGE",
            "FRAMEWORK",
            "DATA",
            "QUALITY",
            "OPERATIONS",
            "SCALE",
            "DOMAIN",
            "EXPERIENCE",
            "CREDENTIAL"
    );
    private static final Map<String, String> STAGE_LABELS = Map.ofEntries(
            Map.entry("FOUNDATION", "공통 기반"),
            Map.entry("WEB", "웹·네트워크 기초"),
            Map.entry("LANGUAGE", "프로그래밍 언어"),
            Map.entry("FRAMEWORK", "서비스 개발"),
            Map.entry("DATA", "데이터·영속성"),
            Map.entry("QUALITY", "테스트·코드 품질"),
            Map.entry("OPERATIONS", "배포·운영"),
            Map.entry("SCALE", "성능·분산 시스템"),
            Map.entry("DOMAIN", "도메인 이해"),
            Map.entry("EXPERIENCE", "실무 경험"),
            Map.entry("CREDENTIAL", "자격")
    );
    private static final Map<String, String> TRACK_LABELS = Map.ofEntries(
            Map.entry("BACKEND", "백엔드"),
            Map.entry("FRONTEND", "프론트엔드"),
            Map.entry("FULLSTACK", "풀스택"),
            Map.entry("DATA", "데이터"),
            Map.entry("AI", "AI"),
            Map.entry("DEVOPS", "DevOps"),
            Map.entry("CLOUD", "클라우드"),
            Map.entry("SECURITY", "보안"),
            Map.entry("GAME", "게임"),
            Map.entry("MOBILE", "모바일"),
            Map.entry("QA", "QA·테스트 자동화"),
            Map.entry("EMBEDDED", "임베디드·펌웨어")
    );
    private static final int CAREER_TIER_WIDTH = 16;
    private static final int FIRST_TIER_BASE_RANK = 3;
    private static final int PROJECT_RANK_OFFSET = 12;
    private static final int OPPORTUNITY_RANK_OFFSET = 13;

    private final RlsTransactionExecutor rls;
    private final ObjectMapper objectMapper;

    public RoadmapService(RlsTransactionExecutor rls, ObjectMapper objectMapper) {
        this.rls = rls;
        this.objectMapper = objectMapper;
    }

    public Workspace get(UUID userId) {
        return rls.read(userId, jdbc -> workspace(jdbc, userId));
    }

    public List<VersionSummary> versions(UUID userId) {
        return rls.read(userId, jdbc -> jdbc.sql("""
                        select
                            id,
                            version_number,
                            status,
                            base_version_number,
                            jsonb_array_length(coalesce(snapshot -> 'targets', '[]'::jsonb)) as target_count,
                            change_summary::text,
                            created_at,
                            published_at
                        from roadmap_versions
                        where status in ('PUBLISHED', 'SUPERSEDED')
                        order by version_number desc
                        limit 30
                        """)
                .query((rs, rowNum) -> new VersionSummary(
                        rs.getObject("id", UUID.class),
                        rs.getLong("version_number"),
                        rs.getString("status"),
                        rs.getObject("base_version_number", Long.class),
                        rs.getInt("target_count"),
                        readChangeSummary(rs.getString("change_summary")),
                        rs.getObject("created_at", OffsetDateTime.class),
                        rs.getObject("published_at", OffsetDateTime.class)
                ))
                .list());
    }

    public DraftResult restoreVersion(UUID userId, UUID versionId) {
        return rls.write(userId, jdbc -> {
            StoredVersion source = jdbc.sql("""
                            select
                                id,
                                version_number,
                                snapshot::text,
                                change_summary::text,
                                created_at
                            from roadmap_versions
                            where id = :versionId
                              and status in ('PUBLISHED', 'SUPERSEDED')
                            for update
                            """)
                    .param("versionId", versionId)
                    .query((rs, rowNum) -> new StoredVersion(
                            rs.getObject("id", UUID.class),
                            rs.getLong("version_number"),
                            rs.getString("snapshot"),
                            rs.getString("change_summary"),
                            rs.getObject("created_at", OffsetDateTime.class)
                    ))
                    .optional()
                    .orElseThrow(() -> new ApiException(
                            HttpStatus.NOT_FOUND,
                            "ROADMAP_VERSION_NOT_FOUND",
                            "복원할 로드맵 버전을 찾을 수 없습니다."
                    ));
            RoadmapSnapshot restored = readSnapshot(source.snapshotJson());
            List<UUID> postingIds = restored.targets().stream()
                    .map(TargetSummary::postingId)
                    .distinct()
                    .toList();

            for (UUID postingId : postingIds) {
                boolean restorable = jdbc.sql("""
                                select exists (
                                    select 1
                                    from roadmap_targets target
                                    join job_postings posting on posting.id = target.posting_id
                                    join analysis_jobs analysis on analysis.id = target.analysis_job_id
                                    where target.posting_id = :postingId
                                      and analysis.status = 'SUCCEEDED'
                                )
                                """)
                        .param("postingId", postingId)
                        .query(Boolean.class)
                        .single();
                if (!restorable) {
                    throw new ApiException(
                            HttpStatus.CONFLICT,
                            "ROADMAP_VERSION_TARGET_MISSING",
                            "이 버전의 공고 또는 분석 기록이 삭제되어 안전하게 복원할 수 없습니다."
                    );
                }
            }

            jdbc.sql("""
                            update roadmap_targets
                            set active = false, removed_at = now()
                            where active
                            """)
                    .update();
            for (UUID postingId : postingIds) {
                jdbc.sql("""
                                update roadmap_targets
                                set active = true, removed_at = null, added_at = now()
                                where posting_id = :postingId
                                """)
                        .param("postingId", postingId)
                        .update();
            }

            StoredVersion published = loadVersion(jdbc, "PUBLISHED", false);
            RoadmapSnapshot current = published == null
                    ? foundationOnlySnapshot(jdbc, userId)
                    : readSnapshot(published.snapshotJson());
            ChangeSummary changes = compare(current, restored);
            jdbc.sql("update roadmap_versions set status = 'DISCARDED' where status = 'DRAFT'")
                    .update();
            long nextVersion = jdbc.sql("""
                            select greatest(
                                coalesce((select max(version_number) from roadmap_versions), 0),
                                coalesce((select version from career_graphs limit 1), 0)
                            ) + 1
                            """)
                    .query(Long.class)
                    .single();
            RoadmapSnapshot versioned = snapshotWithVersion(restored, nextVersion);
            UUID draftId = jdbc.sql("""
                            insert into roadmap_versions (
                                user_id,
                                version_number,
                                status,
                                base_version_number,
                                target_signature,
                                snapshot,
                                change_summary
                            )
                            values (
                                :userId,
                                :versionNumber,
                                'DRAFT',
                                :baseVersion,
                                :targetSignature,
                                cast(:snapshot as jsonb),
                                cast(:changeSummary as jsonb)
                            )
                            returning id
                            """)
                    .param("userId", userId)
                    .param("versionNumber", nextVersion)
                    .param("baseVersion", published == null ? null : published.versionNumber())
                    .param("targetSignature", stableId(postingIds.stream()
                            .map(UUID::toString)
                            .sorted()
                            .collect(Collectors.joining("|"))))
                    .param("snapshot", writeJson(versioned))
                    .param("changeSummary", writeJson(changes))
                    .query(UUID.class)
                    .single();
            return new DraftResult(null, draftId, nextVersion, changes);
        });
    }

    public DraftResult addTarget(UUID userId, UUID analysisJobId) {
        return rls.write(userId, jdbc -> {
            TargetCandidate target = jdbc.sql("""
                            select
                                j.posting_id,
                                j.status::text as analysis_status,
                                c.status::text as change_set_status,
                                posting.lifecycle_status,
                                posting.closes_at
                            from analysis_jobs j
                            join graph_change_sets c on c.analysis_job_id = j.id
                            join job_postings posting on posting.id = j.posting_id
                            where j.id = :analysisJobId
                            for update of j, c
                            """)
                    .param("analysisJobId", analysisJobId)
                    .query((rs, rowNum) -> new TargetCandidate(
                            rs.getObject("posting_id", UUID.class),
                            rs.getString("analysis_status"),
                            rs.getString("change_set_status"),
                            rs.getString("lifecycle_status"),
                            rs.getObject("closes_at", OffsetDateTime.class)
                    ))
                    .optional()
                    .orElseThrow(() -> new ApiException(
                            HttpStatus.NOT_FOUND,
                            "ANALYSIS_JOB_NOT_FOUND",
                            "분석 결과를 찾을 수 없습니다."
                    ));

            if (!"SUCCEEDED".equals(target.analysisStatus())) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "ANALYSIS_NOT_COMPLETED",
                        "완료된 커리어 적합도 분석만 목표에 추가할 수 있습니다."
                );
            }
            int requirementCount = jdbc.sql("""
                            select count(*)
                            from posting_competency_requirements
                            where posting_id = :postingId
                              and analysis_job_id = :analysisJobId
                              and roadmap_eligible
                            """)
                    .param("postingId", target.postingId())
                    .param("analysisJobId", analysisJobId)
                    .query(Integer.class)
                    .single();
            if (requirementCount == 0) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "ANALYSIS_REQUIREMENTS_MISSING",
                        "저장된 공고 역량이 없습니다. 공고를 다시 분석해 주세요."
                );
            }

            jdbc.sql("""
                            insert into roadmap_targets (
                                user_id,
                                posting_id,
                                analysis_job_id,
                                active
                            )
                            values (
                                :userId,
                                :postingId,
                                :analysisJobId,
                                true
                            )
                            on conflict (user_id, posting_id)
                            do update set
                                analysis_job_id = excluded.analysis_job_id,
                                active = true,
                                added_at = now(),
                                removed_at = null
                            """)
                    .param("userId", userId)
                    .param("postingId", target.postingId())
                    .param("analysisJobId", analysisJobId)
                    .update();

            jdbc.sql("""
                            update graph_change_sets
                            set
                                status = 'APPROVED',
                                approved_at = now(),
                                rejected_at = null
                            where analysis_job_id = :analysisJobId
                            """)
                    .param("analysisJobId", analysisJobId)
                    .update();

            DraftVersion draft = generateDraft(jdbc, userId);
            return new DraftResult(
                    target.postingId(),
                    draft.id(),
                    draft.versionNumber(),
                    draft.changeSummary()
            );
        });
    }

    public DraftResult regenerate(UUID userId) {
        return rls.write(userId, jdbc -> {
            DraftVersion draft = generateDraft(jdbc, userId);
            return new DraftResult(
                    null,
                    draft.id(),
                    draft.versionNumber(),
                    draft.changeSummary()
            );
        });
    }

    public DraftResult removeTarget(UUID userId, UUID postingId) {
        return rls.write(userId, jdbc -> {
            int updated = jdbc.sql("""
                            update roadmap_targets
                            set
                                active = false,
                                removed_at = now()
                            where posting_id = :postingId
                              and active
                            """)
                    .param("postingId", postingId)
                    .update();
            if (updated == 0) {
                throw new ApiException(
                        HttpStatus.NOT_FOUND,
                        "ROADMAP_TARGET_NOT_FOUND",
                        "로드맵에서 제거할 목표 공고를 찾을 수 없습니다."
                );
            }
            DraftVersion draft = generateDraft(jdbc, userId);
            return new DraftResult(
                    postingId,
                    draft.id(),
                    draft.versionNumber(),
                    draft.changeSummary()
            );
        });
    }

    public DraftResult resetTargets(UUID userId) {
        return rls.write(userId, jdbc -> {
            jdbc.sql("""
                            update roadmap_targets
                            set
                                active = false,
                                removed_at = now()
                            where active
                            """)
                    .update();
            DraftVersion draft = generateDraft(jdbc, userId);
            return new DraftResult(
                    null,
                    draft.id(),
                    draft.versionNumber(),
                    draft.changeSummary()
            );
        });
    }

    public ApplyResult applyDraft(
            UUID userId,
            UUID expectedDraftId,
            long expectedVersion
    ) {
        return rls.write(userId, jdbc -> {
            StoredVersion draft = loadVersion(jdbc, "DRAFT", true);
            if (draft == null) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "ROADMAP_DRAFT_NOT_FOUND",
                        "적용할 새 로드맵이 없습니다."
                );
            }
            if (!draft.id().equals(expectedDraftId)
                    || draft.versionNumber() != expectedVersion) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "ROADMAP_DRAFT_CHANGED",
                        "검토하던 로드맵 초안이 다른 변경으로 교체되었습니다. 최신 초안을 다시 확인해 주세요."
                );
            }
            RoadmapSnapshot snapshot = readSnapshot(draft.snapshotJson());

            jdbc.sql("""
                            update roadmap_versions
                            set status = 'SUPERSEDED'
                            where status = 'PUBLISHED'
                            """)
                    .update();
            jdbc.sql("""
                            update roadmap_versions
                            set
                                status = 'PUBLISHED',
                                published_at = now()
                            where id = :draftId
                              and status = 'DRAFT'
                            """)
                    .param("draftId", draft.id())
                    .update();

            long graphVersion = jdbc.sql("""
                            update career_graphs
                            set version = :version
                            where user_id = :userId
                            returning version
                            """)
                    .param("version", draft.versionNumber())
                    .param("userId", userId)
                    .query(Long.class)
                    .single();

            materializeCareerNodes(jdbc, userId, snapshot);

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
                                'ROADMAP_UPDATED',
                                '새 로드맵을 적용했어요',
                                '완료한 역량은 유지하고 공통 경로와 회사별 가지를 다시 배치했어요.',
                                jsonb_build_object('roadmapVersion', :version)
                            )
                            """)
                    .param("userId", userId)
                    .param("version", graphVersion)
                    .update();

            return new ApplyResult(draft.id(), graphVersion);
        });
    }

    public DraftDiscardResult discardDraft(
            UUID userId,
            UUID expectedDraftId,
            long expectedVersion
    ) {
        return rls.write(userId, jdbc -> {
            StoredVersion draft = loadVersion(jdbc, "DRAFT", true);
            if (draft == null) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "ROADMAP_DRAFT_NOT_FOUND",
                        "취소할 로드맵 초안이 없습니다."
                );
            }
            if (!draft.id().equals(expectedDraftId)
                    || draft.versionNumber() != expectedVersion) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "ROADMAP_DRAFT_CHANGED",
                        "검토하던 로드맵 초안이 다른 변경으로 교체되었습니다. 최신 초안을 다시 확인해 주세요."
                );
            }
            int discarded = jdbc.sql("""
                            update roadmap_versions
                            set status = 'DISCARDED'
                            where id = :draftId
                              and status = 'DRAFT'
                            """)
                    .param("draftId", draft.id())
                    .update();
            if (discarded != 1) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "ROADMAP_DRAFT_CHANGED",
                        "로드맵 초안 상태가 변경되었습니다. 최신 상태를 다시 확인해 주세요."
                );
            }
            return new DraftDiscardResult(draft.id(), draft.versionNumber());
        });
    }

    private Workspace workspace(JdbcClient jdbc, UUID userId) {
        StoredVersion published = loadVersion(jdbc, "PUBLISHED", false);
        StoredVersion draft = loadVersion(jdbc, "DRAFT", false);

        RoadmapSnapshot currentSnapshot = published == null
                ? foundationOnlySnapshot(jdbc, userId)
                : enrichSnapshot(jdbc, readSnapshot(published.snapshotJson()));
        DraftView draftView = draft == null
                ? null
                : new DraftView(
                        draft.id(),
                        draft.versionNumber(),
                        readChangeSummary(draft.changeSummaryJson()),
                        enrichSnapshot(jdbc, readSnapshot(draft.snapshotJson())),
                        draft.createdAt()
                );
        int targetCount = jdbc.sql("""
                        select count(*)
                        from roadmap_targets
                        where active
                        """)
                .query(Integer.class)
                .single();
        return new Workspace(currentSnapshot, draftView, targetCount);
    }

    private DraftVersion generateDraft(JdbcClient jdbc, UUID userId) {
        List<TargetRow> targets = loadTargets(jdbc);
        List<RequirementRow> requirements = loadRequirements(jdbc);
        RoadmapSnapshot snapshot = targets.isEmpty()
                ? foundationOnlySnapshot(jdbc, userId)
                : buildSnapshot(jdbc, userId, targets, requirements);
        StoredVersion published = loadVersion(jdbc, "PUBLISHED", false);
        RoadmapSnapshot current = published == null
                ? foundationOnlySnapshot(jdbc, userId)
                : readSnapshot(published.snapshotJson());
        ChangeSummary changes = compare(current, snapshot);

        jdbc.sql("""
                        update roadmap_versions
                        set status = 'DISCARDED'
                        where status = 'DRAFT'
                        """)
                .update();

        long nextVersion = jdbc.sql("""
                        select greatest(
                            coalesce((select max(version_number) from roadmap_versions), 0),
                            coalesce((select version from career_graphs limit 1), 0)
                        ) + 1
                        """)
                .query(Long.class)
                .single();
        String targetSignature = stableId(targets.stream()
                .map(target -> target.postingId() + ":" + target.analysisJobId())
                .sorted()
                .collect(Collectors.joining("|")));
        UUID versionId = jdbc.sql("""
                        insert into roadmap_versions (
                            user_id,
                            version_number,
                            status,
                            base_version_number,
                            target_signature,
                            snapshot,
                            change_summary
                        )
                        values (
                            :userId,
                            :versionNumber,
                            'DRAFT',
                            :baseVersion,
                            :targetSignature,
                            cast(:snapshot as jsonb),
                            cast(:changeSummary as jsonb)
                        )
                        returning id
                        """)
                .param("userId", userId)
                .param("versionNumber", nextVersion)
                .param("baseVersion", published == null ? null : published.versionNumber())
                .param("targetSignature", targetSignature)
                .param("snapshot", writeJson(snapshotWithVersion(snapshot, nextVersion)))
                .param("changeSummary", writeJson(changes))
                .query(UUID.class)
                .single();

        return new DraftVersion(versionId, nextVersion, changes);
    }

    private RoadmapSnapshot buildSnapshot(
            JdbcClient jdbc,
            UUID userId,
            List<TargetRow> targets,
            List<RequirementRow> requirements
    ) {
        List<RoadmapNode> nodes = new ArrayList<>();
        List<RoadmapEdge> edges = new ArrayList<>();
        Set<String> edgeKeys = new HashSet<>();

        List<CompetencyRow> foundations = loadFoundations(jdbc, userId);
        String previousFoundation = null;
        for (int index = 0; index < foundations.size(); index++) {
            CompetencyRow foundation = foundations.get(index);
            CompetencyItem item = competencyItem(foundation, 1, "REQUIRED", null);
            RoadmapNode node = new RoadmapNode(
                    foundation.canonicalKey(),
                    "MILESTONE",
                    foundation.title(),
                    "모든 개발 경로가 공유하는 기반",
                    "COMMON",
                    "FOUNDATION",
                    index,
                    false,
                    List.of(),
                    List.of(item),
                    null,
                    null,
                    progressStatus(List.of(item)),
                    null,
                    Map.of()
            );
            nodes.add(node);
            if (previousFoundation != null) {
                addEdge(edges, edgeKeys, previousFoundation, node.id(), "PREREQUISITE");
            }
            previousFoundation = node.id();
        }
        String rootId = previousFoundation;

        Map<UUID, TargetRow> targetById = targets.stream()
                .collect(Collectors.toMap(TargetRow::postingId, target -> target));
        Map<String, List<Integer>> thresholdsByTrack = targets.stream()
                .filter(target -> effectiveExperienceMonths(target) > 0)
                .collect(Collectors.groupingBy(
                        TargetRow::primaryTrack,
                        LinkedHashMap::new,
                        Collectors.mapping(
                                this::effectiveExperienceMonths,
                                Collectors.collectingAndThen(
                                        Collectors.toCollection(java.util.TreeSet::new),
                                        ArrayList::new
                                )
                        )
                ));

        Map<UUID, List<RequirementRow>> byCompetency = requirements.stream()
                .filter(requirement -> !requirement.canonicalKey().startsWith("foundation."))
                .collect(Collectors.groupingBy(
                        RequirementRow::competencyId,
                        LinkedHashMap::new,
                        Collectors.toList()
                ));

        List<GroupBuilder> groups = groupRequirements(byCompetency, targetById);
        List<RoadmapNode> requiredNodes = new ArrayList<>();

        for (GroupBuilder group : groups) {
            boolean optional = group.relationByPosting().values().stream()
                    .noneMatch("REQUIRED"::equals);
            RoadmapNode node = groupNode(
                    group,
                    optional,
                    groupRank(group, targetById, thresholdsByTrack)
            );
            nodes.add(node);
            if (!optional) {
                requiredNodes.add(node);
            }
        }

        Map<String, RoadmapNode> employmentGates = new LinkedHashMap<>();
        Map<String, Map<Integer, RoadmapNode>> experienceGates =
                new LinkedHashMap<>();
        for (Map.Entry<String, List<Integer>> entry : thresholdsByTrack.entrySet()) {
            String track = entry.getKey();
            List<Integer> thresholds = entry.getValue();
            List<TargetRow> trackTargets = targets.stream()
                    .filter(target -> track.equals(target.primaryTrack()))
                    .toList();
            List<UUID> trackPostingIds = trackTargets.stream()
                    .map(TargetRow::postingId)
                    .toList();
            int employmentRank = tierBaseRank(1) - 2;
            RoadmapNode employment = new RoadmapNode(
                    "career:" + track.toLowerCase() + ":employment",
                    "GATE",
                    "관련 " + trackLabel(track) + " 취업",
                    "신입·경력무관 기회에서 실무 경력 경로로 합류합니다.",
                    track,
                    "EMPLOYMENT",
                    employmentRank,
                    false,
                    trackPostingIds,
                    List.of(),
                    null,
                    null,
                    "AVAILABLE",
                    null,
                    Map.of()
            );
            nodes.add(employment);
            employmentGates.put(track, employment);

            Map<Integer, RoadmapNode> trackGates = new LinkedHashMap<>();
            RoadmapNode previousGate = employment;
            for (int thresholdIndex = 0;
                    thresholdIndex < thresholds.size();
                    thresholdIndex++) {
                int months = thresholds.get(thresholdIndex);
                int tierIndex = thresholdIndex + 1;
                List<UUID> gatedPostingIds = trackTargets.stream()
                        .filter(target -> effectiveExperienceMonths(target) >= months)
                        .map(TargetRow::postingId)
                        .toList();
                List<CompetencyItem> careerItems = careerItemsForGate(
                        requirements,
                        targetById,
                        track,
                        months
                );
                Map<UUID, String> requirementKinds = gatedPostingIds.stream()
                        .collect(Collectors.toMap(
                                postingId -> postingId,
                                postingId -> "REQUIRED",
                                (left, right) -> left,
                                LinkedHashMap::new
                        ));
                RoadmapNode gate = new RoadmapNode(
                        "career:" + track.toLowerCase() + ":experience:" + months,
                        "MILESTONE",
                        experienceTitle(track, months),
                        "관련 직무에서 검증 가능한 실무 기간을 충족합니다.",
                        track,
                        "EXPERIENCE",
                        tierBaseRank(tierIndex) - 1,
                        false,
                        gatedPostingIds,
                        careerItems,
                        null,
                        null,
                        progressStatus(careerItems),
                        null,
                        requirementKinds
                );
                nodes.add(gate);
                trackGates.put(months, gate);
                addEdge(
                        edges,
                        edgeKeys,
                        previousGate.id(),
                        gate.id(),
                        "CAREER_PATH"
                );
                previousGate = gate;
            }
            experienceGates.put(track, trackGates);
        }

        Map<UUID, RoadmapNode> opportunityByPosting = new LinkedHashMap<>();
        List<TargetRow> orderedTargets = targets.stream()
                .sorted(Comparator
                        .comparing(TargetRow::primaryTrack)
                        .thenComparingInt(this::effectiveExperienceMonths)
                        .thenComparing(TargetRow::companyName))
                .toList();
        for (TargetRow target : orderedTargets) {
            int tierIndex = targetTierIndex(target, thresholdsByTrack);
            List<RoadmapNode> path = requiredNodes.stream()
                    .filter(node -> "REQUIRED".equals(
                            requirementKind(node, target.postingId())
                    ))
                    .collect(Collectors.toCollection(ArrayList::new));
            if (tierIndex > 0) {
                RoadmapNode employment = employmentGates.get(target.primaryTrack());
                if (employment != null) {
                    path.add(employment);
                }
                RoadmapNode experience = experienceGates
                        .getOrDefault(target.primaryTrack(), Map.of())
                        .get(effectiveExperienceMonths(target));
                if (experience != null) {
                    path.add(experience);
                }
            }
            path = path.stream()
                    .distinct()
                    .sorted(Comparator
                            .comparingInt(RoadmapNode::rank)
                            .thenComparing(RoadmapNode::title))
                    .toList();
            String previous = rootId;
            for (RoadmapNode node : path) {
                boolean entryCompaniesFeedEmployment =
                        "GATE".equals(node.type())
                        && "EMPLOYMENT".equals(node.stage())
                        && hasEntryTarget(targets, target.primaryTrack());
                boolean careerEdgeAlreadyDefined =
                        previous != null
                        && previous.startsWith("career:")
                        && node.id().startsWith("career:");
                if (previous != null
                        && !entryCompaniesFeedEmployment
                        && !careerEdgeAlreadyDefined) {
                    addEdge(edges, edgeKeys, previous, node.id(), "PREREQUISITE");
                }
                previous = node.id();
            }

            String projectId = "project:" + target.postingId();
            ProjectDetail project = new ProjectDetail(
                    target.projectTitle() == null
                            ? target.companyName() + " 맞춤 프로젝트"
                            : target.projectTitle(),
                    target.projectObjective() == null
                            ? "공고의 필수 역량을 통합해 증명하는 결과물을 만듭니다."
                            : target.projectObjective(),
                    target.domainContext() == null ? "" : target.domainContext(),
                    readStringList(target.requiredKeysJson()),
                    readStringList(target.optionalKeysJson()),
                    readStringList(target.deliverablesJson()),
                    readStringList(target.acceptanceCriteriaJson())
            );
            RoadmapNode projectNode = new RoadmapNode(
                    projectId,
                    "PROJECT",
                    project.title(),
                    target.companyName() + " 지원을 위한 검증 과제",
                    target.primaryTrack(),
                    "PROJECT",
                    tierBaseRank(tierIndex) + PROJECT_RANK_OFFSET,
                    false,
                    List.of(target.postingId()),
                    List.of(),
                    project,
                    target.postingId(),
                    projectStatus(jdbc, target.postingId()),
                    careerNodeId(jdbc, projectId),
                    Map.of(target.postingId(), "REQUIRED")
            );
            nodes.add(projectNode);
            if (previous != null) {
                addEdge(edges, edgeKeys, previous, projectId, "PROJECT_PATH");
            }

            List<RequirementRow> targetRequired = requirements.stream()
                    .filter(requirement -> requirement.postingId().equals(target.postingId()))
                    .filter(requirement -> "REQUIRED".equals(requirement.relation()))
                    .toList();
            long completed = targetRequired.stream()
                    .filter(this::requirementCompleted)
                    .count();
            String opportunityId = "opportunity:" + target.postingId();
            RoadmapNode opportunity = new RoadmapNode(
                    opportunityId,
                    "OPPORTUNITY",
                    defaultText(target.companyName(), "목표 회사"),
                    defaultText(target.roleTitle(), "채용 기회"),
                    target.primaryTrack(),
                    "OPPORTUNITY",
                    tierBaseRank(tierIndex) + OPPORTUNITY_RANK_OFFSET,
                    false,
                    List.of(target.postingId()),
                    List.of(),
                    null,
                    target.postingId(),
                    completed == targetRequired.size()
                            && "COMPLETED".equals(projectNode.status())
                            ? "AVAILABLE"
                            : "LOCKED",
                    careerNodeId(jdbc, opportunityId),
                    Map.of(target.postingId(), "REQUIRED")
            );
            nodes.add(opportunity);
            opportunityByPosting.put(target.postingId(), opportunity);
            addEdge(edges, edgeKeys, projectId, opportunityId, "OPPORTUNITY_PATH");
        }

        for (Map.Entry<String, RoadmapNode> entry : employmentGates.entrySet()) {
            String track = entry.getKey();
            RoadmapNode employment = entry.getValue();
            List<TargetRow> entryTargets = targets.stream()
                    .filter(target -> track.equals(target.primaryTrack()))
                    .filter(target -> effectiveExperienceMonths(target) == 0)
                    .toList();
            if (entryTargets.isEmpty()) {
                if (rootId != null) {
                    addEdge(
                            edges,
                            edgeKeys,
                            rootId,
                            employment.id(),
                            "CAREER_PATH"
                    );
                }
                continue;
            }
            for (TargetRow entryTarget : entryTargets) {
                RoadmapNode opportunity =
                        opportunityByPosting.get(entryTarget.postingId());
                if (opportunity != null) {
                    addEdge(
                            edges,
                            edgeKeys,
                            opportunity.id(),
                            employment.id(),
                            "CAREER_PATH"
                    );
                }
            }
        }

        for (RoadmapNode optional : nodes) {
            for (Map.Entry<UUID, String> relation :
                    safeRequirementKinds(optional).entrySet()) {
                if (!"PREFERRED".equals(relation.getValue())) {
                    continue;
                }
                RoadmapNode source = requiredNodes.stream()
                        .filter(node -> node.rank() <= optional.rank())
                        .filter(node -> "REQUIRED".equals(
                                requirementKind(node, relation.getKey())
                        ))
                        .max(Comparator.comparingInt(RoadmapNode::rank))
                        .orElse(null);
                if (source != null) {
                    addEdge(
                            edges,
                            edgeKeys,
                            source.id(),
                            optional.id(),
                            "OPTIONAL"
                    );
                } else if (rootId != null) {
                    addEdge(
                            edges,
                            edgeKeys,
                            rootId,
                            optional.id(),
                            "OPTIONAL"
                    );
                }
            }
        }

        List<TargetSummary> targetSummaries = targets.stream().map(target -> {
            List<RequirementRow> targetRequirements = requirements.stream()
                    .filter(requirement -> requirement.postingId().equals(target.postingId()))
                    .toList();
            int required = (int) targetRequirements.stream()
                    .filter(requirement -> "REQUIRED".equals(requirement.relation()))
                    .count();
            int completedRequired = (int) targetRequirements.stream()
                    .filter(requirement -> "REQUIRED".equals(requirement.relation()))
                    .filter(this::requirementCompleted)
                    .count();
            int preferred = (int) targetRequirements.stream()
                    .filter(requirement -> "PREFERRED".equals(requirement.relation()))
                    .count();
            int completedPreferred = (int) targetRequirements.stream()
                    .filter(requirement -> "PREFERRED".equals(requirement.relation()))
                    .filter(this::requirementCompleted)
                    .count();
            return new TargetSummary(
                    target.postingId(),
                    target.companyName(),
                    target.roleTitle(),
                    completedRequired,
                    required,
                    completedPreferred,
                    preferred,
                    opportunityGoalMode(target.lifecycleStatus(), target.closesAt()),
                    effectiveLifecycleStatus(target.lifecycleStatus(), target.closesAt()),
                    target.closesAt()
            );
        }).toList();

        nodes.sort(Comparator
                .comparingInt(RoadmapNode::rank)
                .thenComparing(RoadmapNode::domain)
                .thenComparing(RoadmapNode::optional)
                .thenComparing(RoadmapNode::title));
        return new RoadmapSnapshot(
                0,
                "나의 목표 기반 커리어 로드맵",
                nodes,
                edges,
                targetSummaries
        );
    }

    private List<GroupBuilder> groupRequirements(
            Map<UUID, List<RequirementRow>> byCompetency,
            Map<UUID, TargetRow> targetById
    ) {
        Map<String, GroupBuilder> groups = new LinkedHashMap<>();
        for (List<RequirementRow> rows : byCompetency.values()) {
            Map<String, List<RequirementRow>> matchingByPlacement = rows.stream()
                    .filter(row -> !isCareerGateRequirement(row, targetById))
                    .collect(Collectors.groupingBy(
                            // 같은 단계라도 기술·지식·업무·개발 실천은 완료 방식이 다르다.
                            // 종류를 빼면 "Celery · REST API · 사용자 중심 태도"처럼 서로
                            // 검증할 수 없는 항목이 한 마일스톤으로 합쳐진다.
                            row -> row.track() + "|" + row.stage() + "|" + row.kind(),
                            LinkedHashMap::new,
                            Collectors.toList()
                    ));
            for (List<RequirementRow> matching : matchingByPlacement.values()) {
                RequirementRow representative = matching.get(0);
                Map<UUID, String> relationByPosting = matching.stream()
                        .collect(Collectors.groupingBy(
                                RequirementRow::postingId,
                                LinkedHashMap::new,
                                Collectors.mapping(
                                        RequirementRow::relation,
                                        Collectors.toList()
                                )
                        ))
                        .entrySet()
                        .stream()
                        .sorted(Map.Entry.comparingByKey())
                        .collect(Collectors.toMap(
                                Map.Entry::getKey,
                                entry -> entry.getValue().contains("REQUIRED")
                                        ? "REQUIRED"
                                        : "PREFERRED",
                                (left, right) -> left,
                                LinkedHashMap::new
                        ));
                List<UUID> postingIds = List.copyOf(
                        relationByPosting.keySet()
                );
                String relationSignature = relationByPosting.entrySet().stream()
                        .map(entry -> entry.getKey() + "=" + entry.getValue())
                        .collect(Collectors.joining(","));
                String groupKey = representative.track() + "|"
                        + representative.stage() + "|"
                        + representative.kind() + "|"
                        + relationSignature;
                GroupBuilder group = groups.computeIfAbsent(
                        groupKey,
                        ignored -> new GroupBuilder(
                                representative.stage(),
                                representative.track(),
                                postingIds,
                                relationByPosting,
                                new ArrayList<>()
                        )
                );
                int requiredLevel = matching.stream()
                        .mapToInt(RequirementRow::requiredLevel)
                        .max()
                        .orElse(representative.requiredLevel());
                group.items().add(new CompetencyItem(
                        representative.competencyId(),
                        representative.canonicalKey(),
                        representative.title(),
                        representative.kind(),
                        representative.requiredScope(),
                        requiredLevel,
                        relationByPosting.values().stream()
                                .allMatch("PREFERRED"::equals)
                                ? "PREFERRED"
                                : relationByPosting.values().stream()
                                .allMatch("REQUIRED"::equals)
                                ? "REQUIRED"
                                : "MIXED",
                        representative.progressStatus(),
                        representative.verifiedLevel(),
                        representative.careerNodeId()
                ));
            }
        }
        return groups.values().stream()
                .sorted(Comparator
                        .comparingInt((GroupBuilder group) -> stageIndex(group.stage()))
                        .thenComparing(group -> group.relationByPosting().toString()))
                .toList();
    }

    private RoadmapNode groupNode(
            GroupBuilder group,
            boolean optional,
            int rank
    ) {
        List<CompetencyItem> items = group.items().stream()
                .sorted(Comparator.comparing(CompetencyItem::title))
                .toList();
        String title = items.size() <= 3
                ? items.stream().map(CompetencyItem::title).collect(Collectors.joining(" · "))
                : STAGE_LABELS.getOrDefault(group.stage(), group.stage())
                + " " + items.size() + "개";
        String signature = group.relationByPosting() + "|" + group.track() + "|"
                + group.stage() + "|"
                + group.postingIds() + "|"
                + items.stream().map(CompetencyItem::canonicalKey)
                .sorted().collect(Collectors.joining(","));
        return new RoadmapNode(
                "milestone:" + stableId(signature),
                "MILESTONE",
                title,
                optional ? "우대사항 선택 퀘스트" : STAGE_LABELS.get(group.stage()),
                group.track(),
                group.stage(),
                rank,
                optional,
                group.postingIds(),
                items,
                null,
                null,
                progressStatus(items),
                null,
                group.relationByPosting()
        );
    }

    private Map<UUID, String> safeRequirementKinds(RoadmapNode node) {
        return node.requirementKinds() == null
                ? Map.of()
                : node.requirementKinds();
    }

    private String requirementKind(RoadmapNode node, UUID postingId) {
        return safeRequirementKinds(node).get(postingId);
    }

    private boolean isCareerGateRequirement(
            RequirementRow requirement,
            Map<UUID, TargetRow> targetById
    ) {
        TargetRow target = targetById.get(requirement.postingId());
        return target != null
                && effectiveExperienceMonths(target) > 0
                && ("EXPERIENCE".equals(requirement.kind())
                || "EXPERIENCE".equals(requirement.stage()));
    }

    private int effectiveExperienceMonths(TargetRow target) {
        if (!"REQUIRED".equals(target.experienceRequirementType())) {
            return 0;
        }
        return Math.max(0, target.minimumExperienceMonths());
    }

    private int targetTierIndex(
            TargetRow target,
            Map<String, List<Integer>> thresholdsByTrack
    ) {
        int months = effectiveExperienceMonths(target);
        if (months <= 0) {
            return 0;
        }
        int index = thresholdsByTrack
                .getOrDefault(target.primaryTrack(), List.of())
                .indexOf(months);
        return index < 0 ? 0 : index + 1;
    }

    private int groupRank(
            GroupBuilder group,
            Map<UUID, TargetRow> targetById,
            Map<String, List<Integer>> thresholdsByTrack
    ) {
        List<UUID> rankPostingIds = group.relationByPosting().entrySet().stream()
                .filter(entry -> "REQUIRED".equals(entry.getValue()))
                .map(Map.Entry::getKey)
                .toList();
        if (rankPostingIds.isEmpty()) {
            rankPostingIds = group.postingIds();
        }
        int tierIndex = rankPostingIds.stream()
                .map(targetById::get)
                .filter(java.util.Objects::nonNull)
                .mapToInt(target -> targetTierIndex(target, thresholdsByTrack))
                .min()
                .orElse(0);
        int stageOffset = Math.max(
                1,
                Math.min(PROJECT_RANK_OFFSET - 1, stageIndex(group.stage()))
        );
        return tierBaseRank(tierIndex) + stageOffset;
    }

    private int tierBaseRank(int tierIndex) {
        return FIRST_TIER_BASE_RANK + tierIndex * CAREER_TIER_WIDTH;
    }

    private boolean hasEntryTarget(List<TargetRow> targets, String track) {
        return targets.stream()
                .filter(target -> track.equals(target.primaryTrack()))
                .anyMatch(target -> effectiveExperienceMonths(target) == 0);
    }

    private List<CompetencyItem> careerItemsForGate(
            List<RequirementRow> requirements,
            Map<UUID, TargetRow> targetById,
            String track,
            int months
    ) {
        return requirements.stream()
                .filter(requirement ->
                        isCareerGateRequirement(requirement, targetById))
                .filter(requirement -> "REQUIRED".equals(requirement.relation()))
                .filter(requirement -> track.equals(requirement.track()))
                .filter(requirement -> {
                    TargetRow target = targetById.get(requirement.postingId());
                    return target != null
                            && effectiveExperienceMonths(target) == months;
                })
                .collect(Collectors.groupingBy(
                        RequirementRow::competencyId,
                        LinkedHashMap::new,
                        Collectors.toList()
                ))
                .values()
                .stream()
                .map(rows -> {
                    RequirementRow representative = rows.get(0);
                    int requiredLevel = rows.stream()
                            .mapToInt(RequirementRow::requiredLevel)
                            .max()
                            .orElse(representative.requiredLevel());
                    return new CompetencyItem(
                            representative.competencyId(),
                            representative.canonicalKey(),
                            representative.title(),
                            representative.kind(),
                            representative.requiredScope(),
                            requiredLevel,
                            "REQUIRED",
                            representative.progressStatus(),
                            representative.verifiedLevel(),
                            representative.careerNodeId()
                    );
                })
                .sorted(Comparator.comparing(CompetencyItem::title))
                .toList();
    }

    private String experienceTitle(String track, int months) {
        if (months % 12 == 0) {
            return trackLabel(track) + " 실무 경력 " + (months / 12) + "년";
        }
        return trackLabel(track) + " 실무 경력 "
                + (months / 12) + "년 " + (months % 12) + "개월";
    }

    private String trackLabel(String track) {
        return TRACK_LABELS.getOrDefault(track, track);
    }

    private String careerNodeKind(String competencyKind) {
        return switch (competencyKind) {
            case "EXPERIENCE" -> "EXPERIENCE";
            case "CREDENTIAL" -> "CREDENTIAL";
            default -> "SKILL";
        };
    }

    private RoadmapSnapshot foundationOnlySnapshot(JdbcClient jdbc, UUID userId) {
        List<CompetencyRow> foundations = loadFoundations(jdbc, userId);
        List<RoadmapNode> nodes = new ArrayList<>();
        List<RoadmapEdge> edges = new ArrayList<>();
        for (int index = 0; index < foundations.size(); index++) {
            CompetencyRow foundation = foundations.get(index);
            CompetencyItem item = competencyItem(foundation, 1, "REQUIRED", null);
            nodes.add(new RoadmapNode(
                    foundation.canonicalKey(),
                    "MILESTONE",
                    foundation.title(),
                    "공고를 추가하면 이 기반에서 직무 경로가 확장됩니다.",
                    "COMMON",
                    "FOUNDATION",
                    index,
                    false,
                    List.of(),
                    List.of(item),
                    null,
                    null,
                    progressStatus(List.of(item)),
                    foundation.careerNodeId(),
                    Map.of()
            ));
            if (index > 0) {
                edges.add(new RoadmapEdge(
                        nodes.get(index - 1).id(),
                        nodes.get(index).id(),
                        "PREREQUISITE"
                ));
            }
        }
        return new RoadmapSnapshot(
                1,
                "나의 목표 기반 커리어 로드맵",
                nodes,
                edges,
                List.of()
        );
    }

    private RoadmapSnapshot enrichSnapshot(JdbcClient jdbc, RoadmapSnapshot snapshot) {
        Map<UUID, LiveCompetency> live = jdbc.sql("""
                        select distinct on (c.id)
                            c.id,
                            c.progress_status::text,
                            c.verified_level,
                            n.id as career_node_id
                        from user_competencies c
                        left join career_nodes n
                         on n.user_id = c.user_id
                         and n.canonical_key = c.canonical_key
                         and n.archived_at is null
                        order by
                            c.id,
                            (n.detail ->> 'userCompetencyId' = c.id::text) desc nulls last,
                            n.updated_at desc nulls last,
                            n.id
                        """)
                .query((rs, rowNum) -> new LiveCompetency(
                        rs.getObject("id", UUID.class),
                        rs.getString("progress_status"),
                        rs.getInt("verified_level"),
                        rs.getObject("career_node_id", UUID.class)
                ))
                .list()
                .stream()
                .collect(Collectors.toMap(LiveCompetency::id, item -> item));
        List<TargetSummary> liveTargets = refreshTargets(jdbc, snapshot.targets());
        List<RoadmapNode> nodes = snapshot.nodes().stream().map(node -> {
            List<CompetencyItem> competencies = node.competencies().stream()
                    .map(item -> {
                        LiveCompetency value = live.get(item.id());
                        if (value == null) {
                            return item;
                        }
                        return new CompetencyItem(
                                item.id(),
                                item.canonicalKey(),
                                item.title(),
                                item.kind(),
                                item.scopeDefinition(),
                                item.requiredLevel(),
                                item.relation(),
                                value.status(),
                                value.verifiedLevel(),
                                value.careerNodeId()
                        );
                    })
                    .toList();
            String status = switch (node.type()) {
                case "MILESTONE" -> progressStatus(competencies);
                case "PROJECT" -> projectStatus(jdbc, node.postingId());
                case "OPPORTUNITY" -> opportunityStatus(
                        liveTargets,
                        node.postingId(),
                        projectStatus(jdbc, node.postingId())
                );
                default -> node.status();
            };
            return new RoadmapNode(
                    node.id(),
                    node.type(),
                    node.title(),
                    node.subtitle(),
                    node.domain(),
                    node.stage(),
                    node.rank(),
                    node.optional(),
                    node.postingIds(),
                    competencies,
                    node.project(),
                    node.postingId(),
                    status,
                    careerNodeId(jdbc, node.id()),
                    safeRequirementKinds(node)
            );
        }).toList();
        return new RoadmapSnapshot(
                snapshot.version(),
                snapshot.title(),
                nodes,
                snapshot.edges(),
                liveTargets
        );
    }

    private List<TargetSummary> refreshTargets(
            JdbcClient jdbc,
            List<TargetSummary> snapshotTargets
    ) {
        if (snapshotTargets.isEmpty()) {
            return List.of();
        }
        Map<UUID, List<RequirementRow>> requirementsByPosting =
                loadRequirements(jdbc).stream()
                        .collect(Collectors.groupingBy(RequirementRow::postingId));
        Map<UUID, TargetRow> targetsByPosting = loadTargets(jdbc).stream()
                .collect(Collectors.toMap(TargetRow::postingId, item -> item));
        return snapshotTargets.stream().map(target -> {
            List<RequirementRow> requirements = requirementsByPosting
                    .getOrDefault(target.postingId(), List.of());
            int required = (int) requirements.stream()
                    .filter(item -> "REQUIRED".equals(item.relation()))
                    .count();
            int completedRequired = (int) requirements.stream()
                    .filter(item -> "REQUIRED".equals(item.relation()))
                    .filter(this::requirementCompleted)
                    .count();
            int preferred = (int) requirements.stream()
                    .filter(item -> "PREFERRED".equals(item.relation()))
                    .count();
            int completedPreferred = (int) requirements.stream()
                    .filter(item -> "PREFERRED".equals(item.relation()))
                    .filter(this::requirementCompleted)
                    .count();
            TargetRow liveTarget = targetsByPosting.get(target.postingId());
            String lifecycleStatus = liveTarget == null
                    ? target.lifecycleStatus()
                    : liveTarget.lifecycleStatus();
            OffsetDateTime closesAt = liveTarget == null
                    ? target.closesAt()
                    : liveTarget.closesAt();
            return new TargetSummary(
                    target.postingId(),
                    target.companyName(),
                    target.roleTitle(),
                    completedRequired,
                    required,
                    completedPreferred,
                    preferred,
                    opportunityGoalMode(lifecycleStatus, closesAt),
                    effectiveLifecycleStatus(lifecycleStatus, closesAt),
                    closesAt
            );
        }).toList();
    }

    private String opportunityGoalMode(String lifecycleStatus, OffsetDateTime closesAt) {
        String effectiveStatus = effectiveLifecycleStatus(lifecycleStatus, closesAt);
        if ("CLOSED".equals(effectiveStatus) || "EXPIRED".equals(effectiveStatus)) {
            return "REOPENING_PREPARATION";
        }
        if ("ACTIVE".equals(effectiveStatus)) {
            return "ACTIVE_APPLICATION";
        }
        return "REFERENCE_TARGET";
    }

    private String effectiveLifecycleStatus(String lifecycleStatus, OffsetDateTime closesAt) {
        if (closesAt != null && !closesAt.isAfter(OffsetDateTime.now())) {
            return "CLOSED";
        }
        return lifecycleStatus == null || lifecycleStatus.isBlank()
                ? "UNKNOWN"
                : lifecycleStatus;
    }

    private void materializeCareerNodes(
            JdbcClient jdbc,
            UUID userId,
            RoadmapSnapshot snapshot
    ) {
        UUID graphId = jdbc.sql("""
                        select id from career_graphs where user_id = :userId
                        """)
                .param("userId", userId)
                .query(UUID.class)
                .single();
        jdbc.sql("delete from career_edges where graph_id = :graphId")
                .param("graphId", graphId)
                .update();
        jdbc.sql("delete from job_requirements").update();

        Set<UUID> materializedCompetencies = new LinkedHashSet<>();
        Set<UUID> activeNodeIds = new LinkedHashSet<>();
        for (RoadmapNode roadmapNode : snapshot.nodes()) {
            for (CompetencyItem competency : roadmapNode.competencies()) {
                if (!materializedCompetencies.add(competency.id())) {
                    continue;
                }
                if (competency.canonicalKey().startsWith("foundation.")) {
                    UUID foundationNodeId = foundationCareerNodeId(
                            jdbc,
                            graphId,
                            competency.canonicalKey()
                    );
                    if (foundationNodeId == null) {
                        foundationNodeId = upsertCareerNode(
                                jdbc,
                                userId,
                                graphId,
                                competency.canonicalKey(),
                                competency.title(),
                                "직접 완료 표시",
                                "COMMON",
                                "FOUNDATION",
                                competency.scopeDefinition(),
                                1,
                                roadmapNode.rank(),
                                null,
                                Map.of(
                                        "stage", "FOUNDATION",
                                        "userCompetencyId", competency.id().toString()
                                )
                        );
                    }
                    syncNodeProgress(jdbc, userId, foundationNodeId, competency);
                    activeNodeIds.add(foundationNodeId);
                    continue;
                }
                UUID nodeId = upsertCareerNode(
                        jdbc,
                        userId,
                        graphId,
                        competency.canonicalKey(),
                        competency.title(),
                        roadmapNode.subtitle(),
                        roadmapNode.domain(),
                        careerNodeKind(competency.kind()),
                        competency.scopeDefinition(),
                        Math.max(1, competency.requiredLevel()),
                        roadmapNode.rank(),
                        null,
                        Map.of(
                                "stage", roadmapNode.stage(),
                                "userCompetencyId", competency.id().toString()
                        )
                );
                syncNodeProgress(jdbc, userId, nodeId, competency);
                activeNodeIds.add(nodeId);
            }
            if ("PROJECT".equals(roadmapNode.type())) {
                UUID nodeId = upsertCareerNode(
                        jdbc,
                        userId,
                        graphId,
                        roadmapNode.id(),
                        roadmapNode.title(),
                        roadmapNode.subtitle(),
                        roadmapNode.domain(),
                        "PROJECT",
                        roadmapNode.project().objective(),
                        1,
                        roadmapNode.rank(),
                        null,
                        roadmapNode.project()
                );
                ensureNodeProgress(jdbc, userId, nodeId);
                activeNodeIds.add(nodeId);
            } else if ("OPPORTUNITY".equals(roadmapNode.type())) {
                UUID nodeId = upsertCareerNode(
                        jdbc,
                        userId,
                        graphId,
                        roadmapNode.id(),
                        roadmapNode.title(),
                        roadmapNode.subtitle(),
                        roadmapNode.domain(),
                        "OPPORTUNITY",
                        roadmapNode.subtitle(),
                        1,
                        roadmapNode.rank(),
                        roadmapNode.postingId(),
                        Map.of("postingId", roadmapNode.postingId().toString())
                );
                activeNodeIds.add(nodeId);
            }
        }

        jdbc.sql("""
                        update career_nodes
                        set archived_at = now()
                        where graph_id = :graphId
                          and kind <> 'FOUNDATION'
                          and not (id = any(cast(:activeNodeIds as uuid[])))
                        """)
                .param("graphId", graphId)
                .param("activeNodeIds", activeNodeIds.toArray(UUID[]::new))
                .update();

        jdbc.sql("""
                        insert into job_requirements (
                            user_id,
                            posting_id,
                            node_id,
                            requirement,
                            source_text,
                            confidence
                        )
                        select
                            r.user_id,
                            r.posting_id,
                            n.id,
                            cast(r.relation_kind as requirement_kind),
                            r.source_text,
                            r.confidence
                        from posting_competency_requirements r
                        join roadmap_targets t
                          on t.posting_id = r.posting_id
                         and t.active
                        join user_competencies c on c.id = r.competency_id
                        join lateral (
                            select candidate.id
                            from career_nodes candidate
                            where candidate.graph_id = :graphId
                              and candidate.canonical_key = c.canonical_key
                              and candidate.archived_at is null
                            order by
                                (
                                    candidate.detail ->> 'userCompetencyId'
                                    = c.id::text
                                ) desc nulls last,
                                candidate.updated_at desc,
                                candidate.id
                            limit 1
                        ) n on true
                        where r.relation_kind in ('REQUIRED', 'PREFERRED')
                          and r.roadmap_eligible
                        on conflict (posting_id, node_id, requirement)
                        do update set
                            source_text = excluded.source_text,
                            confidence = excluded.confidence
                        """)
                .param("graphId", graphId)
                .update();
    }

    private UUID foundationCareerNodeId(
            JdbcClient jdbc,
            UUID graphId,
            String canonicalKey
    ) {
        return jdbc.sql("""
                        select id
                        from career_nodes
                        where graph_id = :graphId
                          and canonical_key = :canonicalKey
                          and kind = 'FOUNDATION'
                          and archived_at is null
                        order by
                            (competency_id is not null) desc,
                            jsonb_exists(detail, 'selfConfirmable') desc,
                            created_at,
                            id
                        limit 1
                        """)
                .param("graphId", graphId)
                .param("canonicalKey", canonicalKey)
                .query(UUID.class)
                .optional()
                .orElse(null);
    }

    private UUID upsertCareerNode(
            JdbcClient jdbc,
            UUID userId,
            UUID graphId,
            String canonicalKey,
            String title,
            String subtitle,
            String domain,
            String kind,
            String scopeDefinition,
            int level,
            int rank,
            UUID postingId,
            Object detail
    ) {
        return jdbc.sql("""
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
                            rank,
                            archived_at
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
                            :rank,
                            null
                        )
                        on conflict (
                            graph_id,
                            canonical_key,
                            level,
                            scope_fingerprint
                        )
                        where archived_at is null
                        do update set
                            posting_id = excluded.posting_id,
                            kind = excluded.kind,
                            title = excluded.title,
                            subtitle = excluded.subtitle,
                            domain = excluded.domain,
                            scope_definition = excluded.scope_definition,
                            level = excluded.level,
                            detail = excluded.detail,
                            rank = excluded.rank,
                            archived_at = null
                        returning id
                        """)
                .param("userId", userId)
                .param("graphId", graphId)
                .param("postingId", postingId)
                .param("kind", kind)
                .param("canonicalKey", canonicalKey)
                .param("title", title)
                .param("subtitle", subtitle)
                .param("domain", domain)
                .param("scopeDefinition", scopeDefinition)
                .param("level", level)
                .param("detail", writeJson(detail))
                .param("rank", rank)
                .query(UUID.class)
                .single();
    }

    private void syncNodeProgress(
            JdbcClient jdbc,
            UUID userId,
            UUID nodeId,
            CompetencyItem competency
    ) {
        jdbc.sql("""
                        insert into node_progress (
                            user_id,
                            node_id,
                            status,
                            completion_method,
                            completed_at
                        )
                        values (
                            :userId,
                            :nodeId,
                            cast(:status as progress_status),
                            :completionMethod,
                            case when :status = 'COMPLETED' then now() else null end
                        )
                        on conflict (node_id)
                        do update set
                            status = excluded.status,
                            completion_method = coalesce(
                                node_progress.completion_method,
                                excluded.completion_method
                            ),
                            completed_at = case
                                when excluded.status = 'COMPLETED'
                                    then coalesce(node_progress.completed_at, now())
                                else null
                            end
                        """)
                .param("userId", userId)
                .param("nodeId", nodeId)
                .param("status", competency.progressStatus())
                .param("completionMethod", "ROADMAP_COMPETENCY")
                .update();
    }

    private void ensureNodeProgress(JdbcClient jdbc, UUID userId, UUID nodeId) {
        jdbc.sql("""
                        insert into node_progress (user_id, node_id)
                        values (:userId, :nodeId)
                        on conflict (node_id) do nothing
                        """)
                .param("userId", userId)
                .param("nodeId", nodeId)
                .update();
    }

    private List<TargetRow> loadTargets(JdbcClient jdbc) {
        return jdbc.sql("""
                        select
                            t.posting_id,
                            t.analysis_job_id,
                            p.company_name,
                            p.role_title,
                            p.lifecycle_status,
                            p.closes_at,
                            coalesce(
                                profile.primary_track,
                                'BACKEND'
                            ) as primary_track,
                            coalesce(
                                profile.experience_requirement_type,
                                'NONE'
                            ) as experience_requirement_type,
                            coalesce(
                                profile.minimum_experience_months,
                                0
                            ) as minimum_experience_months,
                            profile.maximum_experience_months,
                            coalesce(
                                profile.experience_source_text,
                                p.experience_text,
                                '경력 제한 없음'
                            ) as experience_source_text,
                            b.title as project_title,
                            b.objective as project_objective,
                            b.domain_context,
                            b.required_competency_keys::text,
                            b.optional_competency_keys::text,
                            b.deliverables::text,
                            b.acceptance_criteria::text
                        from roadmap_targets t
                        join job_postings p on p.id = t.posting_id
                        left join posting_path_profiles profile
                          on profile.posting_id = t.posting_id
                        left join posting_target_projects b on b.posting_id = t.posting_id
                        where t.active
                        order by t.added_at, t.posting_id
                        """)
                .query((rs, rowNum) -> new TargetRow(
                        rs.getObject("posting_id", UUID.class),
                        rs.getObject("analysis_job_id", UUID.class),
                        rs.getString("company_name"),
                        rs.getString("role_title"),
                        rs.getString("lifecycle_status"),
                        rs.getObject("closes_at", OffsetDateTime.class),
                        rs.getString("primary_track"),
                        rs.getString("experience_requirement_type"),
                        rs.getInt("minimum_experience_months"),
                        rs.getObject("maximum_experience_months", Integer.class),
                        rs.getString("experience_source_text"),
                        rs.getString("project_title"),
                        rs.getString("project_objective"),
                        rs.getString("domain_context"),
                        rs.getString("required_competency_keys"),
                        rs.getString("optional_competency_keys"),
                        rs.getString("deliverables"),
                        rs.getString("acceptance_criteria")
                ))
                .list();
    }

    private List<RequirementRow> loadRequirements(JdbcClient jdbc) {
        return jdbc.sql("""
                        select
                            r.posting_id,
                            r.competency_id,
                            r.relation_kind,
                            r.required_level,
                            r.required_scope,
                            r.source_text,
                            r.confidence,
                            c.canonical_key,
                            r.competency_title as title,
                            r.competency_kind,
                            r.roadmap_domain as domain,
                            r.roadmap_stage as default_stage,
                            coalesce(
                                profile.primary_track,
                                'BACKEND'
                            ) as placement_track,
                            r.required_scope as scope_definition,
                            c.progress_status::text,
                            c.verified_level,
                            n.id as career_node_id
                        from posting_competency_requirements r
                        join roadmap_targets t
                          on t.posting_id = r.posting_id
                         and t.active
                        join user_competencies c on c.id = r.competency_id
                        left join posting_path_profiles profile
                          on profile.posting_id = r.posting_id
                        left join lateral (
                            select candidate.id
                            from career_nodes candidate
                            where candidate.user_id = c.user_id
                              and candidate.canonical_key = c.canonical_key
                              and candidate.archived_at is null
                            order by
                                (
                                    candidate.detail ->> 'userCompetencyId'
                                    = c.id::text
                                ) desc nulls last,
                                candidate.updated_at desc,
                                candidate.id
                            limit 1
                        ) n on true
                        where r.roadmap_eligible
                        order by r.roadmap_stage, c.canonical_key
                        """)
                .query((rs, rowNum) -> new RequirementRow(
                        rs.getObject("posting_id", UUID.class),
                        rs.getObject("competency_id", UUID.class),
                        rs.getString("relation_kind"),
                        rs.getInt("required_level"),
                        rs.getString("required_scope"),
                        rs.getString("source_text"),
                        rs.getBigDecimal("confidence"),
                        rs.getString("canonical_key"),
                        rs.getString("title"),
                        rs.getString("competency_kind"),
                        rs.getString("domain"),
                        rs.getString("default_stage"),
                        rs.getString("placement_track"),
                        rs.getString("scope_definition"),
                        rs.getString("progress_status"),
                        rs.getInt("verified_level"),
                        rs.getObject("career_node_id", UUID.class)
                ))
                .list();
    }

    private List<CompetencyRow> loadFoundations(JdbcClient jdbc, UUID userId) {
        return jdbc.sql("""
                        select
                            c.id,
                            c.canonical_key,
                            catalog.title,
                            'KNOWLEDGE' as competency_kind,
                            catalog.domain,
                            'FOUNDATION' as default_stage,
                            catalog.scope_definition,
                            c.progress_status::text,
                            c.verified_level,
                            n.id as career_node_id
                        from user_competencies c
                        join competency_catalog catalog
                          on catalog.canonical_key = c.canonical_key
                        left join lateral (
                            select candidate.id
                            from career_nodes candidate
                            where candidate.user_id = c.user_id
                              and candidate.canonical_key = c.canonical_key
                              and candidate.archived_at is null
                            order by
                                (candidate.competency_id = catalog.id) desc,
                                jsonb_exists(
                                    candidate.detail,
                                    'selfConfirmable'
                                ) desc,
                                candidate.created_at,
                                candidate.id
                            limit 1
                        ) n on true
                        where c.user_id = :userId
                          and c.canonical_key in (
                              'foundation.programming',
                              'foundation.git-terminal',
                              'foundation.cs'
                          )
                        order by case c.canonical_key
                            when 'foundation.programming' then 0
                            when 'foundation.git-terminal' then 1
                            else 2
                        end
                        """)
                .param("userId", userId)
                .query((rs, rowNum) -> new CompetencyRow(
                        rs.getObject("id", UUID.class),
                        rs.getString("canonical_key"),
                        rs.getString("title"),
                        rs.getString("competency_kind"),
                        rs.getString("domain"),
                        rs.getString("default_stage"),
                        rs.getString("scope_definition"),
                        rs.getString("progress_status"),
                        rs.getInt("verified_level"),
                        rs.getObject("career_node_id", UUID.class)
                ))
                .list();
    }

    private StoredVersion loadVersion(
            JdbcClient jdbc,
            String status,
            boolean lock
    ) {
        String sql = """
                select
                    id,
                    version_number,
                    snapshot::text,
                    change_summary::text,
                    created_at
                from roadmap_versions
                where status = :status
                order by version_number desc
                limit 1
                """ + (lock ? " for update" : "");
        return jdbc.sql(sql)
                .param("status", status)
                .query((rs, rowNum) -> new StoredVersion(
                        rs.getObject("id", UUID.class),
                        rs.getLong("version_number"),
                        rs.getString("snapshot"),
                        rs.getString("change_summary"),
                        rs.getObject("created_at", OffsetDateTime.class)
                ))
                .optional()
                .orElse(null);
    }

    private ChangeSummary compare(
            RoadmapSnapshot current,
            RoadmapSnapshot draft
    ) {
        Map<String, RoadmapNode> currentNodes = current.nodes().stream()
                .collect(Collectors.toMap(RoadmapNode::id, node -> node));
        Map<String, RoadmapNode> draftNodes = draft.nodes().stream()
                .collect(Collectors.toMap(RoadmapNode::id, node -> node));
        List<String> added = draftNodes.entrySet().stream()
                .filter(entry -> !currentNodes.containsKey(entry.getKey()))
                .map(entry -> entry.getValue().title())
                .toList();
        List<String> removed = currentNodes.entrySet().stream()
                .filter(entry -> !draftNodes.containsKey(entry.getKey()))
                .map(entry -> entry.getValue().title())
                .toList();
        List<String> retained = draftNodes.entrySet().stream()
                .filter(entry -> currentNodes.containsKey(entry.getKey()))
                .map(entry -> entry.getValue().title())
                .toList();
        return new ChangeSummary(added, removed, retained);
    }

    private boolean requirementCompleted(RequirementRow requirement) {
        return "COMPLETED".equals(requirement.progressStatus())
                && requirement.verifiedLevel() >= requirement.requiredLevel();
    }

    private String progressStatus(List<CompetencyItem> competencies) {
        if (competencies.isEmpty()) {
            return "NOT_STARTED";
        }
        long completed = competencies.stream()
                .filter(item -> "COMPLETED".equals(item.progressStatus()))
                .filter(item -> item.verifiedLevel() >= item.requiredLevel())
                .count();
        if (completed == competencies.size()) {
            return "COMPLETED";
        }
        if (completed > 0 || competencies.stream()
                .anyMatch(item -> "IN_PROGRESS".equals(item.progressStatus()))) {
            return "IN_PROGRESS";
        }
        return "NOT_STARTED";
    }

    private String projectStatus(JdbcClient jdbc, UUID postingId) {
        if (postingId == null) {
            return "NOT_STARTED";
        }
        return jdbc.sql("""
                        select coalesce(p.status::text, 'NOT_STARTED')
                        from career_nodes n
                        left join node_progress p on p.node_id = n.id
                        where n.canonical_key = :canonicalKey
                          and n.archived_at is null
                        """)
                .param("canonicalKey", "project:" + postingId)
                .query(String.class)
                .optional()
                .orElse("NOT_STARTED");
    }

    private String opportunityStatus(
            List<TargetSummary> targets,
            UUID postingId,
            String projectStatus
    ) {
        return targets.stream()
                .filter(target -> target.postingId().equals(postingId))
                .findFirst()
                .map(target -> target.completedRequired() == target.required()
                        && "COMPLETED".equals(projectStatus)
                        ? "AVAILABLE"
                        : "LOCKED")
                .orElse("LOCKED");
    }

    private UUID careerNodeId(JdbcClient jdbc, String canonicalKey) {
        if (canonicalKey == null) {
            return null;
        }
        return jdbc.sql("""
                        select id
                        from career_nodes
                        where canonical_key = :canonicalKey
                          and archived_at is null
                        order by updated_at desc, level desc, id
                        limit 1
                        """)
                .param("canonicalKey", canonicalKey)
                .query(UUID.class)
                .optional()
                .orElse(null);
    }

    private CompetencyItem competencyItem(
            CompetencyRow competency,
            int requiredLevel,
            String relation,
            UUID careerNodeId
    ) {
        return new CompetencyItem(
                competency.id(),
                competency.canonicalKey(),
                competency.title(),
                competency.kind(),
                competency.scopeDefinition(),
                requiredLevel,
                relation,
                competency.progressStatus(),
                competency.verifiedLevel(),
                careerNodeId == null ? competency.careerNodeId() : careerNodeId
        );
    }

    private void addEdge(
            List<RoadmapEdge> edges,
            Set<String> edgeKeys,
            String from,
            String to,
            String kind
    ) {
        String key = from + ">" + to + ":" + kind;
        if (!from.equals(to) && edgeKeys.add(key)) {
            edges.add(new RoadmapEdge(from, to, kind));
        }
    }

    private int stageIndex(String stage) {
        int index = STAGE_ORDER.indexOf(stage);
        return index < 0 ? STAGE_ORDER.size() : index;
    }

    private RoadmapSnapshot snapshotWithVersion(
            RoadmapSnapshot snapshot,
            long version
    ) {
        return new RoadmapSnapshot(
                version,
                snapshot.title(),
                snapshot.nodes(),
                snapshot.edges(),
                snapshot.targets()
        );
    }

    private RoadmapSnapshot readSnapshot(String json) {
        try {
            return objectMapper.readValue(json, RoadmapSnapshot.class);
        } catch (RuntimeException exception) {
            throw new IllegalStateException("Stored roadmap snapshot is invalid", exception);
        }
    }

    private ChangeSummary readChangeSummary(String json) {
        try {
            return objectMapper.readValue(json, ChangeSummary.class);
        } catch (RuntimeException exception) {
            throw new IllegalStateException("Stored roadmap change summary is invalid", exception);
        }
    }

    private List<String> readStringList(String json) {
        if (json == null) {
            return List.of();
        }
        try {
            return objectMapper.readValue(
                    json,
                    objectMapper.getTypeFactory()
                            .constructCollectionType(List.class, String.class)
            );
        } catch (RuntimeException exception) {
            throw new IllegalStateException("Stored string list is invalid", exception);
        }
    }

    private String writeJson(Object value) {
        return objectMapper.writeValueAsString(value);
    }

    private String stableId(String value) {
        return UUID.nameUUIDFromBytes(value.getBytes(StandardCharsets.UTF_8)).toString();
    }

    private String defaultText(String value, String fallback) {
        return value == null || value.isBlank() ? fallback : value;
    }

    public record Workspace(
            RoadmapSnapshot current,
            DraftView draft,
            int targetCount
    ) {
    }

    public record DraftView(
            UUID id,
            long version,
            ChangeSummary changes,
            RoadmapSnapshot snapshot,
            OffsetDateTime createdAt
    ) {
    }

    public record DraftResult(
            UUID postingId,
            UUID draftId,
            long draftVersion,
            ChangeSummary changes
    ) {
    }

    public record ApplyResult(UUID roadmapVersionId, long graphVersion) {
    }

    public record DraftDiscardResult(UUID draftId, long draftVersion) {
    }

    public record VersionSummary(
            UUID id,
            long version,
            String status,
            Long baseVersion,
            int targetCount,
            ChangeSummary changes,
            OffsetDateTime createdAt,
            OffsetDateTime publishedAt
    ) {
    }

    public record RoadmapSnapshot(
            long version,
            String title,
            List<RoadmapNode> nodes,
            List<RoadmapEdge> edges,
            List<TargetSummary> targets
    ) {
    }

    public record RoadmapNode(
            String id,
            String type,
            String title,
            String subtitle,
            String domain,
            String stage,
            int rank,
            boolean optional,
            List<UUID> postingIds,
            List<CompetencyItem> competencies,
            ProjectDetail project,
            UUID postingId,
            String status,
            UUID careerNodeId,
            Map<UUID, String> requirementKinds
    ) {
    }

    public record CompetencyItem(
            UUID id,
            String canonicalKey,
            String title,
            String kind,
            String scopeDefinition,
            int requiredLevel,
            String relation,
            String progressStatus,
            int verifiedLevel,
            UUID careerNodeId
    ) {
    }

    public record ProjectDetail(
            String title,
            String objective,
            String domainContext,
            List<String> requiredCompetencyKeys,
            List<String> optionalCompetencyKeys,
            List<String> deliverables,
            List<String> acceptanceCriteria
    ) {
    }

    public record RoadmapEdge(String fromId, String toId, String kind) {
    }

    public record TargetSummary(
            UUID postingId,
            String companyName,
            String roleTitle,
            int completedRequired,
            int required,
            int completedPreferred,
            int preferred,
            String goalMode,
            String lifecycleStatus,
            OffsetDateTime closesAt
    ) {
    }

    public record ChangeSummary(
            List<String> added,
            List<String> removed,
            List<String> retained
    ) {
    }

    private record TargetCandidate(
            UUID postingId,
            String analysisStatus,
            String changeSetStatus,
            String lifecycleStatus,
            OffsetDateTime closesAt
    ) {
    }

    private record DraftVersion(
            UUID id,
            long versionNumber,
            ChangeSummary changeSummary
    ) {
    }

    private record StoredVersion(
            UUID id,
            long versionNumber,
            String snapshotJson,
            String changeSummaryJson,
            OffsetDateTime createdAt
    ) {
    }

    private record TargetRow(
            UUID postingId,
            UUID analysisJobId,
            String companyName,
            String roleTitle,
            String lifecycleStatus,
            OffsetDateTime closesAt,
            String primaryTrack,
            String experienceRequirementType,
            int minimumExperienceMonths,
            Integer maximumExperienceMonths,
            String experienceSourceText,
            String projectTitle,
            String projectObjective,
            String domainContext,
            String requiredKeysJson,
            String optionalKeysJson,
            String deliverablesJson,
            String acceptanceCriteriaJson
    ) {
    }

    private record RequirementRow(
            UUID postingId,
            UUID competencyId,
            String relation,
            int requiredLevel,
            String requiredScope,
            String sourceText,
            BigDecimal confidence,
            String canonicalKey,
            String title,
            String kind,
            String domain,
            String stage,
            String track,
            String scopeDefinition,
            String progressStatus,
            int verifiedLevel,
            UUID careerNodeId
    ) {
    }

    private record CompetencyRow(
            UUID id,
            String canonicalKey,
            String title,
            String kind,
            String domain,
            String stage,
            String scopeDefinition,
            String progressStatus,
            int verifiedLevel,
            UUID careerNodeId
    ) {
    }

    private record GroupBuilder(
            String stage,
            String track,
            List<UUID> postingIds,
            Map<UUID, String> relationByPosting,
            List<CompetencyItem> items
    ) {
    }

    private record LiveCompetency(
            UUID id,
            String status,
            int verifiedLevel,
            UUID careerNodeId
    ) {
    }
}
