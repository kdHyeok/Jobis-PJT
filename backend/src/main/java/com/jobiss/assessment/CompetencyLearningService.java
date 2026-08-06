package com.jobiss.assessment;

import com.jobiss.analysis.AiAnalysisClient;
import com.jobiss.analysis.AiContracts;
import com.jobiss.analysis.AiUsageLimitService;
import com.jobiss.common.ApiException;
import com.jobiss.db.RlsTransactionExecutor;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.UUID;

@Service
public class CompetencyLearningService {

    private static final String LEARNING_CONTRACT_VERSION = "scope-contract-v2";

    private final RlsTransactionExecutor rls;
    private final AiUsageLimitService usageLimit;
    private final AiAnalysisClient aiClient;
    private final ObjectMapper objectMapper;

    public CompetencyLearningService(
            RlsTransactionExecutor rls,
            AiUsageLimitService usageLimit,
            AiAnalysisClient aiClient,
            ObjectMapper objectMapper
    ) {
        this.rls = rls;
        this.usageLimit = usageLimit;
        this.aiClient = aiClient;
        this.objectMapper = objectMapper;
    }

    public AiContracts.CompetencyLearningResponse latest(
            UUID userId,
            UUID nodeId,
            UUID targetPostingId
    ) {
        LearningContext context = rls.read(
                userId,
                jdbc -> loadContext(jdbc, nodeId, targetPostingId)
        );
        return rls.read(userId, jdbc -> loadCached(jdbc, context, targetPostingId));
    }

    public AiContracts.CompetencyLearningResponse generate(
            UUID userId,
            UUID nodeId,
            UUID targetPostingId,
            boolean refresh
    ) {
        LearningContext context = rls.read(
                userId,
                jdbc -> loadContext(jdbc, nodeId, targetPostingId)
        );
        if (!refresh) {
            AiContracts.CompetencyLearningResponse cached = rls.read(
                    userId,
                    jdbc -> loadCached(jdbc, context, targetPostingId)
            );
            if (cached != null) {
                return cached;
            }
        }

        usageLimit.consume(userId, AiUsageLimitService.Kind.LEARNING);
        AiContracts.CompetencyLearningResponse generated = aiClient.competencyLearning(
                new AiContracts.CompetencyLearningRequest(
                        context.competency(),
                        context.target()
                )
        );
        String content = objectMapper.writeValueAsString(generated);
        rls.write(userId, jdbc -> {
            jdbc.sql("""
                            insert into competency_learning_contents (
                                user_id, competency_id, target_posting_id,
                                context_fingerprint, content
                            ) values (
                                :userId, :competencyId, :targetPostingId,
                                :fingerprint, cast(:content as jsonb)
                            )
                            on conflict (user_id, competency_id, context_fingerprint)
                            do update set
                                target_posting_id = excluded.target_posting_id,
                                content = excluded.content,
                                updated_at = now()
                            """)
                    .param("userId", userId)
                    .param("competencyId", context.competencyId())
                    .param("targetPostingId", targetPostingId)
                    .param("fingerprint", context.fingerprint())
                    .param("content", content)
                    .update();
            return null;
        });
        return generated;
    }

    private AiContracts.CompetencyLearningResponse loadCached(
            JdbcClient jdbc,
            LearningContext context,
            UUID targetPostingId
    ) {
        return jdbc.sql("""
                        select content::text
                        from competency_learning_contents
                        where competency_id = :competencyId
                          and context_fingerprint = :fingerprint
                          and target_posting_id is not distinct from :targetPostingId
                        order by updated_at desc
                        limit 1
                        """)
                .param("competencyId", context.competencyId())
                .param("fingerprint", context.fingerprint())
                .param("targetPostingId", targetPostingId)
                .query(String.class)
                .optional()
                .map(value -> objectMapper.readValue(
                        value,
                        AiContracts.CompetencyLearningResponse.class
                ))
                .orElse(null);
    }

    private LearningContext loadContext(
            JdbcClient jdbc,
            UUID nodeId,
            UUID targetPostingId
    ) {
        CompetencyRow competency = jdbc.sql("""
                        select
                            competency.id,
                            competency.canonical_key,
                            competency.title,
                            competency.domain,
                            competency.scope_definition,
                            greatest(node.level, 1) as required_level,
                            catalog.level_definition::text,
                            catalog.assessment_blueprint::text
                        from career_nodes node
                        join user_competencies competency
                          on competency.user_id = node.user_id
                         and competency.canonical_key = node.canonical_key
                        join competency_catalog catalog
                          on catalog.id = competency.catalog_competency_id
                        where node.id = :nodeId
                          and node.archived_at is null
                          and node.kind not in (
                              'FOUNDATION', 'PROJECT', 'OPPORTUNITY',
                              'OPPORTUNITY_CLUSTER'
                          )
                          and competency.roadmap_eligible
                        """)
                .param("nodeId", nodeId)
                .query((rs, rowNum) -> new CompetencyRow(
                        rs.getObject("id", UUID.class),
                        rs.getString("canonical_key"),
                        rs.getString("title"),
                        rs.getString("domain"),
                        rs.getString("scope_definition"),
                        rs.getInt("required_level"),
                        readJson(rs.getString("level_definition")),
                        readJson(rs.getString("assessment_blueprint"))
                ))
                .optional()
                .orElseThrow(() -> new ApiException(
                        HttpStatus.BAD_REQUEST,
                        "NODE_NOT_AI_LEARNABLE",
                        "AI 학습 가이드를 만들 수 없는 단계입니다."
                ));

        TargetRow target = targetPostingId == null
                ? TargetRow.empty()
                : jdbc.sql("""
                                select
                                    posting.company_name,
                                    posting.role_title,
                                    profile.primary_track,
                                    project.domain_context,
                                    string_agg(
                                        requirement.source_text,
                                        E'\n' order by requirement.relation_kind
                                    ) filter (
                                        where required_competency.id is not null
                                    ) as requirement_source
                                from job_postings posting
                                left join posting_path_profiles profile
                                  on profile.posting_id = posting.id
                                left join posting_target_projects project
                                  on project.posting_id = posting.id
                                left join posting_competency_requirements requirement
                                  on requirement.posting_id = posting.id
                                left join user_competencies required_competency
                                  on required_competency.id = requirement.competency_id
                                 and required_competency.canonical_key = :canonicalKey
                                where posting.id = :postingId
                                  and posting.archived_at is null
                                group by posting.id, profile.primary_track,
                                         project.domain_context
                                """)
                        .param("canonicalKey", competency.canonicalKey())
                        .param("postingId", targetPostingId)
                        .query((rs, rowNum) -> new TargetRow(
                                rs.getString("company_name"),
                                rs.getString("role_title"),
                                rs.getString("primary_track"),
                                rs.getString("domain_context"),
                                rs.getString("requirement_source")
                        ))
                        .optional()
                        .orElseThrow(() -> new ApiException(
                                HttpStatus.NOT_FOUND,
                                "LEARNING_TARGET_NOT_FOUND",
                                "학습 가이드에 사용할 목표 공고를 찾을 수 없습니다."
                        ));
        GoalRow goals = jdbc.sql("""
                        select
                            posting.company_name,
                            posting.role_title,
                            goal.final_goal_text
                        from user_goal_profiles goal
                        left join job_postings posting
                          on posting.id = goal.current_goal_posting_id
                        where goal.user_id = app_current_user_id()
                        """)
                .query((rs, rowNum) -> new GoalRow(
                        rs.getString("company_name"),
                        rs.getString("role_title"),
                        rs.getString("final_goal_text")
                ))
                .optional()
                .orElse(GoalRow.empty());

        AiContracts.AssessmentCompetency competencyContract =
                new AiContracts.AssessmentCompetency(
                        competency.canonicalKey(),
                        competency.title(),
                        competency.domain(),
                        competency.scopeDefinition(),
                        competency.requiredLevel(),
                        competency.levelDefinition(),
                        competency.assessmentBlueprint()
                );
        AiContracts.AssessmentTargetContext targetContract =
                new AiContracts.AssessmentTargetContext(
                        target.companyName(),
                        target.roleTitle(),
                        target.primaryTrack(),
                        target.domainContext(),
                        target.requirementSource(),
                        goals.currentGoal(),
                        goals.finalGoal()
                );
        String fingerprint = sha256(
                LEARNING_CONTRACT_VERSION + ":" + objectMapper.writeValueAsString(
                        new AiContracts.CompetencyLearningRequest(
                                competencyContract,
                                targetContract
                        )
                )
        );
        return new LearningContext(
                competency.id(), competencyContract, targetContract, fingerprint
        );
    }

    private JsonNode readJson(String value) {
        return value == null || value.isBlank()
                ? objectMapper.createObjectNode()
                : objectMapper.readTree(value);
    }

    private String sha256(String value) {
        try {
            return HexFormat.of().formatHex(
                    MessageDigest.getInstance("SHA-256")
                            .digest(value.getBytes(StandardCharsets.UTF_8))
            );
        } catch (Exception exception) {
            throw new IllegalStateException("학습 맥락 해시를 만들지 못했습니다.", exception);
        }
    }

    private record CompetencyRow(
            UUID id,
            String canonicalKey,
            String title,
            String domain,
            String scopeDefinition,
            int requiredLevel,
            JsonNode levelDefinition,
            JsonNode assessmentBlueprint
    ) {
    }

    private record TargetRow(
            String companyName,
            String roleTitle,
            String primaryTrack,
            String domainContext,
            String requirementSource
    ) {
        static TargetRow empty() {
            return new TargetRow(null, null, null, null, null);
        }
    }

    private record GoalRow(
            String companyName,
            String roleTitle,
            String finalGoal
    ) {
        static GoalRow empty() {
            return new GoalRow(null, null, null);
        }

        String currentGoal() {
            if (companyName == null && roleTitle == null) {
                return null;
            }
            return (companyName == null ? "회사 미정" : companyName)
                    + " · "
                    + (roleTitle == null ? "직무 미정" : roleTitle);
        }
    }

    private record LearningContext(
            UUID competencyId,
            AiContracts.AssessmentCompetency competency,
            AiContracts.AssessmentTargetContext target,
            String fingerprint
    ) {
    }
}
