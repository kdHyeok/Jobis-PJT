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

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.OffsetDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Collectors;

@Service
public class CompetencyAssessmentService {

    private static final int MINIMUM_QUESTIONS = 3;
    private static final int MAXIMUM_QUESTIONS = 5;
    private static final int PASS_SCORE = 75;
    private static final int MINIMUM_QUESTION_SCORE = 60;
    private static final List<String> REQUIRED_KIND_ORDER =
            List.of("CONCEPT", "CODE", "SCENARIO");
    private static final Set<String> REQUIRED_KINDS =
            Set.copyOf(REQUIRED_KIND_ORDER);

    private final RlsTransactionExecutor rls;
    private final AiUsageLimitService usageLimit;
    private final AiAnalysisClient aiClient;
    private final ObjectMapper objectMapper;

    public CompetencyAssessmentService(
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

    public AssessmentView latest(UUID userId, UUID nodeId) {
        return rls.read(userId, jdbc -> {
            UUID sessionId = jdbc.sql("""
                            select session.id
                            from career_nodes node
                            join user_competencies competency
                              on competency.user_id = node.user_id
                             and competency.canonical_key = node.canonical_key
                            join competency_assessment_sessions session
                              on session.competency_id = competency.id
                            where node.id = :nodeId
                            order by session.created_at desc
                            limit 1
                            """)
                    .param("nodeId", nodeId)
                    .query(UUID.class)
                    .optional()
                    .orElse(null);
            return sessionId == null ? null : loadView(jdbc, sessionId);
        });
    }

    public AssessmentView start(UUID userId, UUID nodeId, UUID targetPostingId) {
        AssessmentContext context = rls.read(
                userId,
                jdbc -> loadContext(jdbc, nodeId, targetPostingId)
        );
        AssessmentView active = rls.read(userId, jdbc -> jdbc.sql("""
                        select id
                        from competency_assessment_sessions
                        where competency_id = :competencyId
                          and status = 'IN_PROGRESS'
                        limit 1
                        """)
                .param("competencyId", context.competencyId())
                .query(UUID.class)
                .optional()
                .map(id -> loadView(jdbc, id))
                .orElse(null));
        if (active != null) {
            return active;
        }

        Map<String, Integer> retainedScores = rls.read(
                userId,
                jdbc -> loadRetainedScores(
                        jdbc,
                        context.competencyId(),
                        context.requiredLevel()
                )
        );
        String firstQuestionKind = firstQuestionKind(retainedScores);
        usageLimit.consume(userId, AiUsageLimitService.Kind.ASSESSMENT);
        UUID sessionId = UUID.randomUUID();
        AiContracts.CompetencyAssessmentResponse aiResponse =
                aiClient.assessCompetency(new AiContracts.CompetencyAssessmentRequest(
                        sessionId,
                        context.competencyContract(),
                        context.targetContract(),
                        List.of(),
                        retainedScores,
                        firstQuestionKind
                ));
        AiContracts.AssessmentQuestion question =
                requireQuestion(aiResponse, firstQuestionKind);

        return rls.write(userId, jdbc -> {
            jdbc.sql("""
                            insert into competency_assessment_sessions (
                                id,
                                user_id,
                                competency_id,
                                target_posting_id,
                                required_level,
                                status,
                                retained_scores,
                                summary,
                                strengths,
                                gaps,
                                next_actions
                            )
                            values (
                                :id,
                                :userId,
                                :competencyId,
                                :targetPostingId,
                                :requiredLevel,
                                'IN_PROGRESS',
                                cast(:retainedScores as jsonb),
                                :summary,
                                cast(:strengths as jsonb),
                                cast(:gaps as jsonb),
                                cast(:nextActions as jsonb)
                            )
                            """)
                    .param("id", sessionId)
                    .param("userId", userId)
                    .param("competencyId", context.competencyId())
                    .param("targetPostingId", targetPostingId)
                    .param("requiredLevel", context.requiredLevel())
                    .param("retainedScores", writeJson(retainedScores))
                    .param("summary", aiResponse.sessionSummary())
                    .param("strengths", writeJson(safeList(aiResponse.strengths())))
                    .param("gaps", writeJson(safeList(aiResponse.gaps())))
                    .param("nextActions", writeJson(safeList(aiResponse.nextActions())))
                    .update();
            insertQuestion(jdbc, userId, sessionId, 1, question);
            return loadView(jdbc, sessionId);
        });
    }

    public AssessmentView answer(UUID userId, UUID sessionId, String answer) {
        SessionContext session = rls.read(
                userId,
                jdbc -> loadSessionContext(jdbc, sessionId)
        );
        if (!"IN_PROGRESS".equals(session.status())) {
            throw new ApiException(
                    HttpStatus.CONFLICT,
                    "ASSESSMENT_ALREADY_FINISHED",
                    "이미 종료된 검증입니다. 새로운 검증을 시작해 주세요."
            );
        }
        AssessmentTurnRow pending = session.turns().stream()
                .filter(turn -> turn.answerText() == null)
                .findFirst()
                .orElseThrow(() -> new ApiException(
                        HttpStatus.CONFLICT,
                        "ASSESSMENT_QUESTION_NOT_FOUND",
                        "답변할 검증 문제가 없습니다."
                ));
        List<AiContracts.AssessmentTurn> aiTurns = session.turns().stream()
                .map(turn -> new AiContracts.AssessmentTurn(
                        turn.ordinal(),
                        turn.questionKind(),
                        turn.prompt(),
                        turn.codeSnippet(),
                        turn.id().equals(pending.id())
                                ? answer.trim()
                                : turn.answerText(),
                        turn.score(),
                        turn.feedback()
                ))
                .toList();

        usageLimit.consume(userId, AiUsageLimitService.Kind.ASSESSMENT);
        AiContracts.CompetencyAssessmentResponse aiResponse =
                aiClient.assessCompetency(new AiContracts.CompetencyAssessmentRequest(
                        sessionId,
                        session.context().competencyContract(),
                        session.context().targetContract(),
                        aiTurns,
                        session.retainedScores(),
                        null
                ));
        AiContracts.AssessmentAnswerEvaluation evaluation =
                requireEvaluation(aiResponse);

        return rls.write(userId, jdbc -> {
            int updated = jdbc.sql("""
                            update competency_assessment_turns
                            set
                                answer_text = :answer,
                                score = :score,
                                verdict = :verdict,
                                feedback = :feedback,
                                covered_criteria = cast(:coveredCriteria as jsonb),
                                gaps = cast(:gaps as jsonb),
                                future_extensions = cast(:futureExtensions as jsonb),
                                answered_at = now()
                            where id = :turnId
                              and session_id = :sessionId
                              and answer_text is null
                            """)
                    .param("answer", answer.trim())
                    .param("score", evaluation.score())
                    .param("verdict", normalizeVerdict(evaluation.verdict()))
                    .param("feedback", evaluation.feedback())
                    .param(
                            "coveredCriteria",
                            writeJson(safeList(evaluation.coveredCriteria()))
                    )
                    .param("gaps", writeJson(safeList(evaluation.gaps())))
                    .param(
                            "futureExtensions",
                            writeJson(safeList(evaluation.futureExtensions()))
                    )
                    .param("turnId", pending.id())
                    .param("sessionId", sessionId)
                    .update();
            if (updated == 0) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "ASSESSMENT_ANSWER_CONFLICT",
                        "이미 처리된 답변입니다."
                );
            }

            ScoreSummary score = scoreSummary(
                    jdbc,
                    sessionId,
                    session.retainedScores()
            );
            boolean passed = score.kinds().size() >= MINIMUM_QUESTIONS
                    && score.average() >= PASS_SCORE
                    && score.minimum() >= MINIMUM_QUESTION_SCORE
                    && score.kinds().containsAll(REQUIRED_KINDS);
            boolean needsStudy = !passed
                    && score.attemptCount() >= MAXIMUM_QUESTIONS;

            if (passed || needsStudy) {
                finishSession(
                        jdbc,
                        userId,
                        sessionId,
                        session.context(),
                        score,
                        passed,
                        aiResponse
                );
            } else {
                String requiredNextKind =
                        nextQuestionKind(score.bestScores());
                AiContracts.AssessmentQuestion next =
                        requireQuestion(aiResponse, requiredNextKind);
                insertQuestion(
                        jdbc,
                        userId,
                        sessionId,
                        score.attemptCount() + 1,
                        next
                );
                updateSessionSummary(jdbc, sessionId, score, aiResponse);
            }
            return loadView(jdbc, sessionId);
        });
    }

    public AssessmentView requestReview(
            UUID userId,
            UUID sessionId,
            String appealText
    ) {
        return rls.write(userId, jdbc -> {
            int updated = jdbc.sql("""
                            update competency_assessment_sessions
                            set
                                review_status = 'REQUESTED',
                                appeal_text = :appealText,
                                reviewed_by = null,
                                reviewed_at = null
                            where id = :sessionId
                              and status = 'NEEDS_STUDY'
                              and review_status in ('NONE', 'REJECTED')
                            """)
                    .param("appealText", appealText.trim())
                    .param("sessionId", sessionId)
                    .update();
            if (updated == 0) {
                throw new ApiException(
                        HttpStatus.CONFLICT,
                        "ASSESSMENT_REVIEW_NOT_AVAILABLE",
                        "현재 상태에서는 운영자 검토를 요청할 수 없습니다."
                );
            }
            jdbc.sql("""
                            insert into assessment_review_actions (
                                user_id,
                                session_id,
                                action,
                                comment
                            )
                            values (
                                :userId,
                                :sessionId,
                                'REQUESTED',
                                :appealText
                            )
                            """)
                    .param("userId", userId)
                    .param("sessionId", sessionId)
                    .param("appealText", appealText.trim())
                    .update();
            return loadView(jdbc, sessionId);
        });
    }

    public List<AssessmentReviewView> operatorReviews(
            UUID operatorId,
            String status
    ) {
        return rls.read(operatorId, jdbc -> {
            ensureOperator(jdbc);
            String normalized = status == null || status.isBlank()
                    ? "REQUESTED"
                    : status.trim().toUpperCase();
            return jdbc.sql("""
                            select
                                session.id,
                                session.user_id,
                                concat(
                                    '사용자 ',
                                    left(session.user_id::text, 8)
                                ) as user_label,
                                competency.title,
                                session.required_level,
                                session.status,
                                session.review_status,
                                session.appeal_text,
                                session.average_score,
                                session.summary,
                                session.created_at
                            from competency_assessment_sessions session
                            join user_competencies competency
                              on competency.id = session.competency_id
                            where session.review_status = :status
                            order by session.updated_at
                            limit 200
                            """)
                    .param("status", normalized)
                    .query((rs, rowNum) -> new AssessmentReviewView(
                            rs.getObject("id", UUID.class),
                            rs.getObject("user_id", UUID.class),
                            rs.getString("user_label"),
                            rs.getString("title"),
                            rs.getInt("required_level"),
                            rs.getString("status"),
                            rs.getString("review_status"),
                            rs.getString("appeal_text"),
                            rs.getBigDecimal("average_score"),
                            rs.getString("summary"),
                            rs.getObject("created_at", OffsetDateTime.class)
                    ))
                    .list();
        });
    }

    public void resolveReview(
            UUID operatorId,
            UUID sessionId,
            boolean approved,
            String comment
    ) {
        rls.write(operatorId, jdbc -> {
            ensureOperator(jdbc);
            ReviewTarget target = jdbc.sql("""
                            select user_id, competency_id, required_level
                            from competency_assessment_sessions
                            where id = :sessionId
                              and review_status = 'REQUESTED'
                            for update
                            """)
                    .param("sessionId", sessionId)
                    .query((rs, rowNum) -> new ReviewTarget(
                            rs.getObject("user_id", UUID.class),
                            rs.getObject("competency_id", UUID.class),
                            rs.getInt("required_level")
                    ))
                    .optional()
                    .orElseThrow(() -> new ApiException(
                            HttpStatus.NOT_FOUND,
                            "ASSESSMENT_REVIEW_NOT_FOUND",
                            "대기 중인 검토 요청을 찾을 수 없습니다."
                    ));
            String reviewStatus = approved ? "APPROVED" : "REJECTED";
            jdbc.sql("""
                            update competency_assessment_sessions
                            set
                                review_status = :reviewStatus,
                                reviewed_by = :operatorId,
                                reviewed_at = now(),
                                status = case
                                    when :approved then 'PASSED'
                                    else status
                                end,
                                achieved_level = case
                                    when :approved then required_level
                                    else achieved_level
                                end,
                                completed_at = case
                                    when :approved then coalesce(completed_at, now())
                                    else completed_at
                                end
                            where id = :sessionId
                            """)
                    .param("reviewStatus", reviewStatus)
                    .param("operatorId", operatorId)
                    .param("approved", approved)
                    .param("sessionId", sessionId)
                    .update();
            if (approved) {
                jdbc.sql("""
                                update user_competencies
                                set
                                    progress_status = 'COMPLETED',
                                    verified_level = greatest(
                                        verified_level,
                                        :requiredLevel
                                    ),
                                    completion_method = 'OPERATOR_REVIEW',
                                    completed_at = coalesce(completed_at, now())
                                where id = :competencyId
                                """)
                        .param("requiredLevel", target.requiredLevel())
                        .param("competencyId", target.competencyId())
                        .update();
                jdbc.sql("""
                                update node_progress progress
                                set
                                    status = 'COMPLETED',
                                    completed_at = coalesce(completed_at, now())
                                from career_nodes node
                                join user_competencies competency
                                  on competency.user_id = node.user_id
                                 and competency.canonical_key = node.canonical_key
                                where competency.id = :competencyId
                                  and progress.node_id = node.id
                                """)
                        .param("competencyId", target.competencyId())
                        .update();
            }
            jdbc.sql("""
                            insert into assessment_review_actions (
                                user_id,
                                session_id,
                                operator_user_id,
                                action,
                                comment
                            )
                            values (
                                :userId,
                                :sessionId,
                                :operatorId,
                                :action,
                                :comment
                            )
                            """)
                    .param("userId", target.userId())
                    .param("sessionId", sessionId)
                    .param("operatorId", operatorId)
                    .param("action", reviewStatus)
                    .param("comment", comment)
                    .update();
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
                                'ASSESSMENT_REVIEW_RESOLVED',
                                :title,
                                :body,
                                jsonb_build_object(
                                    'assessmentSessionId',
                                    cast(:sessionId as text),
                                    'reviewStatus',
                                    :reviewStatus
                                )
                            )
                            """)
                    .param("userId", target.userId())
                    .param("title", approved
                            ? "역량 검토가 승인됐어요"
                            : "역량 검토 결과를 확인해 주세요")
                    .param("body", comment == null || comment.isBlank()
                            ? (approved
                            ? "운영자 검토를 통해 해당 역량이 완료 처리됐습니다."
                            : "운영자 검토가 반려됐습니다. 보완 후 다시 도전해 주세요.")
                            : comment.trim())
                    .param("sessionId", sessionId)
                    .param("reviewStatus", reviewStatus)
                    .update();
            return null;
        });
    }

    private AssessmentContext loadContext(
            JdbcClient jdbc,
            UUID nodeId,
            UUID targetPostingId
    ) {
        CompetencyRow competency = jdbc.sql("""
                        select
                            node.id as node_id,
                            competency.id as competency_id,
                            competency.canonical_key,
                            competency.title,
                            competency.domain,
                            competency.scope_definition,
                            greatest(node.level, 1) as required_level,
                            competency.verified_level,
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
                              'FOUNDATION',
                              'PROJECT',
                              'OPPORTUNITY',
                              'OPPORTUNITY_CLUSTER'
                          )
                          and competency.roadmap_eligible
                        """)
                .param("nodeId", nodeId)
                .query((rs, rowNum) -> new CompetencyRow(
                        rs.getObject("node_id", UUID.class),
                        rs.getObject("competency_id", UUID.class),
                        rs.getString("canonical_key"),
                        rs.getString("title"),
                        rs.getString("domain"),
                        rs.getString("scope_definition"),
                        rs.getInt("required_level"),
                        rs.getInt("verified_level"),
                        readJson(rs.getString("level_definition")),
                        readJson(rs.getString("assessment_blueprint"))
                ))
                .optional()
                .orElseThrow(() -> new ApiException(
                        HttpStatus.BAD_REQUEST,
                        "NODE_NOT_AI_ASSESSABLE",
                        "AI 문제로 검증할 수 없는 단계입니다."
                ));

        TargetRow target = targetPostingId == null
                ? TargetRow.empty()
                : jdbc.sql("""
                                select
                                    posting.company_name,
                                    posting.role_title,
                                    profile.primary_track,
                                    project.domain_context,
                                    (
                                        select string_agg(
                                            requirement.source_text,
                                            E'\n'
                                            order by requirement.relation_kind
                                        )
                                        from posting_competency_requirements requirement
                                        join user_competencies target_competency
                                          on target_competency.id =
                                             requirement.competency_id
                                        where requirement.posting_id = posting.id
                                          and target_competency.canonical_key =
                                              :canonicalKey
                                    ) as requirement_source
                                from job_postings posting
                                left join posting_path_profiles profile
                                  on profile.posting_id = posting.id
                                left join posting_target_projects project
                                  on project.posting_id = posting.id
                                where posting.id = :postingId
                                  and posting.archived_at is null
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
                                "ASSESSMENT_TARGET_NOT_FOUND",
                                "검증에 사용할 목표 공고를 찾을 수 없습니다."
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
        return new AssessmentContext(competency, target, goals);
    }

    private SessionContext loadSessionContext(JdbcClient jdbc, UUID sessionId) {
        SessionHeader header = jdbc.sql("""
                        select
                            session.status,
                            node.id as node_id,
                            session.target_posting_id,
                            session.retained_scores::text
                        from competency_assessment_sessions session
                        join user_competencies competency
                          on competency.id = session.competency_id
                        join career_nodes node
                          on node.user_id = competency.user_id
                         and node.canonical_key = competency.canonical_key
                         and node.archived_at is null
                        where session.id = :sessionId
                        order by node.updated_at desc
                        limit 1
                        """)
                .param("sessionId", sessionId)
                .query((rs, rowNum) -> new SessionHeader(
                        rs.getString("status"),
                        rs.getObject("node_id", UUID.class),
                        rs.getObject("target_posting_id", UUID.class),
                        readScoreMap(rs.getString("retained_scores"))
                ))
                .optional()
                .orElseThrow(() -> new ApiException(
                        HttpStatus.NOT_FOUND,
                        "ASSESSMENT_NOT_FOUND",
                        "역량 검증을 찾을 수 없습니다."
                ));
        AssessmentContext context =
                loadContext(jdbc, header.nodeId(), header.targetPostingId());
        List<AssessmentTurnRow> turns = loadTurnRows(jdbc, sessionId);
        return new SessionContext(
                header.status(),
                context,
                turns,
                header.retainedScores()
        );
    }

    private Map<String, Integer> loadRetainedScores(
            JdbcClient jdbc,
            UUID competencyId,
            int requiredLevel
    ) {
        Map<String, Integer> retained = new LinkedHashMap<>();
        jdbc.sql("""
                        select
                            turn.question_kind,
                            max(turn.score) as best_score
                        from competency_assessment_sessions session
                        join competency_assessment_turns turn
                          on turn.session_id = session.id
                        where session.competency_id = :competencyId
                          and session.required_level = :requiredLevel
                          and session.status in ('PASSED', 'NEEDS_STUDY')
                          and session.completed_at >= now() - interval '30 days'
                          and turn.question_kind in (
                              'CONCEPT',
                              'CODE',
                              'SCENARIO'
                          )
                          and turn.score >= :minimumScore
                        group by turn.question_kind
                        """)
                .param("competencyId", competencyId)
                .param("requiredLevel", requiredLevel)
                .param("minimumScore", MINIMUM_QUESTION_SCORE)
                .query((rs, rowNum) -> new ScoredTurn(
                        rs.getString("question_kind"),
                        rs.getInt("best_score")
                ))
                .list()
                .forEach(turn -> retained.put(turn.kind(), turn.score()));
        return Map.copyOf(retained);
    }

    private List<AssessmentTurnRow> loadTurnRows(JdbcClient jdbc, UUID sessionId) {
        return jdbc.sql("""
                        select
                            id,
                            ordinal,
                            question_kind,
                            prompt,
                            code_snippet,
                            answer_text,
                            score,
                            verdict,
                            feedback,
                            covered_criteria::text,
                            gaps::text,
                            core_criteria::text,
                            future_extensions::text,
                            answered_at
                        from competency_assessment_turns
                        where session_id = :sessionId
                        order by ordinal
                        """)
                .param("sessionId", sessionId)
                .query((rs, rowNum) -> new AssessmentTurnRow(
                        rs.getObject("id", UUID.class),
                        rs.getInt("ordinal"),
                        rs.getString("question_kind"),
                        rs.getString("prompt"),
                        rs.getString("code_snippet"),
                        rs.getString("answer_text"),
                        (Integer) rs.getObject("score"),
                        rs.getString("verdict"),
                        rs.getString("feedback"),
                        readJson(rs.getString("covered_criteria")),
                        readJson(rs.getString("gaps")),
                        readJson(rs.getString("core_criteria")),
                        readJson(rs.getString("future_extensions")),
                        rs.getObject("answered_at", OffsetDateTime.class)
                ))
                .list();
    }

    private void insertQuestion(
            JdbcClient jdbc,
            UUID userId,
            UUID sessionId,
            int ordinal,
            AiContracts.AssessmentQuestion question
    ) {
        jdbc.sql("""
                        insert into competency_assessment_turns (
                            user_id,
                            session_id,
                            ordinal,
                            question_kind,
                            prompt,
                            code_snippet,
                            core_criteria,
                            future_extensions
                        )
                        values (
                            :userId,
                            :sessionId,
                            :ordinal,
                            :kind,
                            :prompt,
                            :codeSnippet,
                            cast(:coreCriteria as jsonb),
                            cast(:futureExtensions as jsonb)
                        )
                        """)
                .param("userId", userId)
                .param("sessionId", sessionId)
                .param("ordinal", ordinal)
                .param("kind", question.kind())
                .param("prompt", question.prompt())
                .param("codeSnippet", question.codeSnippet())
                .param("coreCriteria", writeJson(safeList(question.coreCriteria())))
                .param(
                        "futureExtensions",
                        writeJson(safeList(question.futureExtensions()))
                )
                .update();
        jdbc.sql("""
                        update competency_assessment_sessions
                        set question_count = :questionCount
                        where id = :sessionId
                        """)
                .param("questionCount", ordinal)
                .param("sessionId", sessionId)
                .update();
    }

    private void finishSession(
            JdbcClient jdbc,
            UUID userId,
            UUID sessionId,
            AssessmentContext context,
            ScoreSummary score,
            boolean passed,
            AiContracts.CompetencyAssessmentResponse response
    ) {
        int achievedLevel = passed ? context.requiredLevel() : 0;
        jdbc.sql("""
                        update competency_assessment_sessions
                        set
                            status = :status,
                            average_score = :averageScore,
                            achieved_level = :achievedLevel,
                            confidence = :confidence,
                            summary = :summary,
                            strengths = cast(:strengths as jsonb),
                            gaps = cast(:gaps as jsonb),
                            next_actions = cast(:nextActions as jsonb),
                            completed_at = now()
                        where id = :sessionId
                        """)
                .param("status", passed ? "PASSED" : "NEEDS_STUDY")
                .param("averageScore", score.average())
                .param("achievedLevel", achievedLevel)
                .param(
                        "confidence",
                        BigDecimal.valueOf(score.average() / 100.0)
                                .setScale(3, RoundingMode.HALF_UP)
                )
                .param("summary", response.sessionSummary())
                .param("strengths", writeJson(safeList(response.strengths())))
                .param("gaps", writeJson(safeList(response.gaps())))
                .param("nextActions", writeJson(safeList(response.nextActions())))
                .param("sessionId", sessionId)
                .update();

        if (passed) {
            jdbc.sql("""
                            update user_competencies
                            set
                                progress_status = 'COMPLETED',
                                verified_level = greatest(
                                    verified_level,
                                    :requiredLevel
                                ),
                                completion_method = 'AI_ASSESSMENT',
                                completed_at = now()
                            where id = :competencyId
                            """)
                    .param("requiredLevel", context.requiredLevel())
                    .param("competencyId", context.competencyId())
                    .update();
            jdbc.sql("""
                            update node_progress progress
                            set
                                status = 'COMPLETED',
                                completion_method = 'AI_ASSESSMENT',
                                completed_at = now()
                            from career_nodes node
                            where progress.node_id = node.id
                              and node.user_id = :userId
                              and node.canonical_key = :canonicalKey
                            """)
                    .param("userId", userId)
                    .param("canonicalKey", context.canonicalKey())
                    .update();
        }

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
                            'COMPETENCY_ASSESSMENT_COMPLETED',
                            :title,
                            :body,
                            jsonb_build_object(
                                'assessmentSessionId',
                                cast(:sessionId as text),
                                'competencyId',
                                cast(:competencyId as text),
                                'status',
                                :status
                            )
                        )
                        """)
                .param("userId", userId)
                .param("title", passed
                        ? context.title() + " 검증을 통과했어요"
                        : context.title() + " 보완 항목을 확인해 주세요")
                .param("body", response.sessionSummary())
                .param("sessionId", sessionId)
                .param("competencyId", context.competencyId())
                .param("status", passed ? "PASSED" : "NEEDS_STUDY")
                .update();
    }

    private void updateSessionSummary(
            JdbcClient jdbc,
            UUID sessionId,
            ScoreSummary score,
            AiContracts.CompetencyAssessmentResponse response
    ) {
        jdbc.sql("""
                        update competency_assessment_sessions
                        set
                            average_score = :averageScore,
                            summary = :summary,
                            strengths = cast(:strengths as jsonb),
                            gaps = cast(:gaps as jsonb),
                            next_actions = cast(:nextActions as jsonb)
                        where id = :sessionId
                        """)
                .param("averageScore", score.average())
                .param("summary", response.sessionSummary())
                .param("strengths", writeJson(safeList(response.strengths())))
                .param("gaps", writeJson(safeList(response.gaps())))
                .param("nextActions", writeJson(safeList(response.nextActions())))
                .param("sessionId", sessionId)
                .update();
    }

    private ScoreSummary scoreSummary(
            JdbcClient jdbc,
            UUID sessionId,
            Map<String, Integer> retainedScores
    ) {
        List<ScoredTurn> turns = jdbc.sql("""
                        select question_kind, score
                        from competency_assessment_turns
                        where session_id = :sessionId
                          and answer_text is not null
                        order by ordinal
                        """)
                .param("sessionId", sessionId)
                .query((rs, rowNum) -> new ScoredTurn(
                        rs.getString("question_kind"),
                        rs.getInt("score")
                ))
                .list();
        Map<String, Integer> bestScores = new LinkedHashMap<>();
        retainedScores.forEach((kind, score) -> {
            if (REQUIRED_KINDS.contains(kind)) {
                bestScores.put(kind, score);
            }
        });
        turns.stream()
                .filter(turn -> REQUIRED_KINDS.contains(turn.kind()))
                .forEach(turn -> bestScores.merge(
                        turn.kind(),
                        turn.score(),
                        Math::max
                ));
        double average = bestScores.values().stream()
                .mapToInt(Integer::intValue)
                .average()
                .orElse(0);
        int minimum = REQUIRED_KIND_ORDER.stream()
                .mapToInt(kind -> bestScores.getOrDefault(kind, 0))
                .min()
                .orElse(0);
        Set<String> kinds = bestScores.entrySet().stream()
                .filter(entry -> entry.getValue() >= MINIMUM_QUESTION_SCORE)
                .map(Map.Entry::getKey)
                .collect(Collectors.toSet());
        return new ScoreSummary(
                turns.size(),
                average,
                minimum,
                kinds,
                Map.copyOf(bestScores)
        );
    }

    private AssessmentView loadView(JdbcClient jdbc, UUID sessionId) {
        AssessmentHeader header = jdbc.sql("""
                        select
                            session.id,
                            session.competency_id,
                            competency.title,
                            competency.canonical_key,
                            session.target_posting_id,
                            posting.company_name,
                            posting.role_title,
                            session.required_level,
                            session.status,
                            session.question_count,
                            session.retained_scores::text,
                            session.average_score,
                            session.achieved_level,
                            session.confidence,
                            session.summary,
                            session.strengths::text,
                            session.gaps::text,
                            session.next_actions::text,
                            session.review_status,
                            session.appeal_text,
                            session.created_at,
                            session.completed_at
                        from competency_assessment_sessions session
                        join user_competencies competency
                          on competency.id = session.competency_id
                        left join job_postings posting
                          on posting.id = session.target_posting_id
                        where session.id = :sessionId
                        """)
                .param("sessionId", sessionId)
                .query((rs, rowNum) -> new AssessmentHeader(
                        rs.getObject("id", UUID.class),
                        rs.getObject("competency_id", UUID.class),
                        rs.getString("title"),
                        rs.getString("canonical_key"),
                        rs.getObject("target_posting_id", UUID.class),
                        rs.getString("company_name"),
                        rs.getString("role_title"),
                        rs.getInt("required_level"),
                        rs.getString("status"),
                        rs.getInt("question_count"),
                        readScoreMap(rs.getString("retained_scores")),
                        rs.getObject("average_score") == null
                                ? null
                                : rs.getBigDecimal("average_score"),
                        rs.getInt("achieved_level"),
                        rs.getObject("confidence") == null
                                ? null
                                : rs.getBigDecimal("confidence"),
                        rs.getString("summary"),
                        readJson(rs.getString("strengths")),
                        readJson(rs.getString("gaps")),
                        readJson(rs.getString("next_actions")),
                        rs.getString("review_status"),
                        rs.getString("appeal_text"),
                        rs.getObject("created_at", OffsetDateTime.class),
                        rs.getObject("completed_at", OffsetDateTime.class)
                ))
                .optional()
                .orElseThrow(() -> new ApiException(
                        HttpStatus.NOT_FOUND,
                        "ASSESSMENT_NOT_FOUND",
                        "역량 검증을 찾을 수 없습니다."
                ));
        List<TurnView> turns = loadTurnRows(jdbc, sessionId).stream()
                .map(turn -> new TurnView(
                        turn.id(),
                        turn.ordinal(),
                        turn.questionKind(),
                        turn.prompt(),
                        turn.codeSnippet(),
                        turn.answerText(),
                        turn.score(),
                        turn.verdict(),
                        turn.feedback(),
                        turn.coveredCriteria(),
                        turn.gaps(),
                        turn.coreCriteria(),
                        turn.futureExtensions(),
                        turn.answeredAt()
                ))
                .toList();
        return new AssessmentView(
                header.id(),
                header.competencyId(),
                header.title(),
                header.canonicalKey(),
                header.targetPostingId(),
                header.companyName(),
                header.roleTitle(),
                header.requiredLevel(),
                header.status(),
                header.questionCount(),
                header.retainedScores(),
                header.averageScore(),
                header.achievedLevel(),
                header.confidence(),
                header.summary(),
                header.strengths(),
                header.gaps(),
                header.nextActions(),
                header.reviewStatus(),
                header.appealText(),
                turns,
                header.createdAt(),
                header.completedAt()
        );
    }

    private AiContracts.AssessmentQuestion requireQuestion(
            AiContracts.CompetencyAssessmentResponse response,
            String expectedKind
    ) {
        if (response == null
                || response.nextQuestion() == null
                || response.nextQuestion().prompt() == null
                || response.nextQuestion().prompt().isBlank()
                || !expectedKind.equals(response.nextQuestion().kind())) {
            throw new IllegalStateException(
                    "AI response did not include the required assessment question"
            );
        }
        return response.nextQuestion();
    }

    private AiContracts.AssessmentAnswerEvaluation requireEvaluation(
            AiContracts.CompetencyAssessmentResponse response
    ) {
        if (response == null
                || response.answerEvaluation() == null
                || response.answerEvaluation().feedback() == null
                || response.answerEvaluation().feedback().isBlank()) {
            throw new IllegalStateException(
                    "AI response did not include an answer evaluation"
            );
        }
        return response.answerEvaluation();
    }

    static String firstQuestionKind(Map<String, Integer> retainedScores) {
        String next = nextQuestionKind(retainedScores);
        if (next != null) {
            return next;
        }
        return REQUIRED_KIND_ORDER.stream()
                .min((left, right) -> Integer.compare(
                        retainedScores.getOrDefault(left, 0),
                        retainedScores.getOrDefault(right, 0)
                ))
                .orElse("CONCEPT");
    }

    static String nextQuestionKind(Map<String, Integer> bestScores) {
        for (String kind : REQUIRED_KIND_ORDER) {
            if (bestScores.getOrDefault(kind, 0) < MINIMUM_QUESTION_SCORE) {
                return kind;
            }
        }
        double average = REQUIRED_KIND_ORDER.stream()
                .mapToInt(kind -> bestScores.getOrDefault(kind, 0))
                .average()
                .orElse(0);
        if (average >= PASS_SCORE) {
            return null;
        }
        return REQUIRED_KIND_ORDER.stream()
                .min((left, right) -> Integer.compare(
                        bestScores.getOrDefault(left, 0),
                        bestScores.getOrDefault(right, 0)
                ))
                .orElse("CONCEPT");
    }

    private String normalizeVerdict(String verdict) {
        return switch (verdict) {
            case "PASS", "PARTIAL", "FAIL" -> verdict;
            default -> "FAIL";
        };
    }

    private String writeJson(Object value) {
        return objectMapper.writeValueAsString(value);
    }

    private JsonNode readJson(String value) {
        return value == null
                ? objectMapper.createArrayNode()
                : objectMapper.readTree(value);
    }

    private Map<String, Integer> readScoreMap(String value) {
        JsonNode root = value == null
                ? objectMapper.createObjectNode()
                : objectMapper.readTree(value);
        Map<String, Integer> scores = new LinkedHashMap<>();
        for (String kind : REQUIRED_KIND_ORDER) {
            JsonNode score = root.path(kind);
            if (score.isInt()) {
                scores.put(kind, score.intValue());
            }
        }
        return Map.copyOf(scores);
    }

    private <T> List<T> safeList(List<T> value) {
        return value == null ? List.of() : value;
    }

    private void ensureOperator(JdbcClient jdbc) {
        boolean operator = jdbc.sql("""
                        select exists (
                            select 1
                            from users
                            where id = app_current_user_id()
                              and account_role = 'OPERATOR'
                        )
                        """)
                .query(Boolean.class)
                .single();
        if (!operator) {
            throw new ApiException(
                    HttpStatus.FORBIDDEN,
                    "OPERATOR_REQUIRED",
                    "운영자 권한이 필요합니다."
            );
        }
    }

    public record AssessmentView(
            UUID id,
            UUID competencyId,
            String competencyTitle,
            String canonicalKey,
            UUID targetPostingId,
            String companyName,
            String roleTitle,
            int requiredLevel,
            String status,
            int questionCount,
            Map<String, Integer> retainedScores,
            BigDecimal averageScore,
            int achievedLevel,
            BigDecimal confidence,
            String summary,
            JsonNode strengths,
            JsonNode gaps,
            JsonNode nextActions,
            String reviewStatus,
            String appealText,
            List<TurnView> turns,
            OffsetDateTime createdAt,
            OffsetDateTime completedAt
    ) {
    }

    public record AssessmentReviewView(
            UUID sessionId,
            UUID userId,
            String userEmail,
            String competencyTitle,
            int requiredLevel,
            String status,
            String reviewStatus,
            String appealText,
            BigDecimal averageScore,
            String summary,
            OffsetDateTime createdAt
    ) {
    }

    public record TurnView(
            UUID id,
            int ordinal,
            String questionKind,
            String prompt,
            String codeSnippet,
            String answerText,
            Integer score,
            String verdict,
            String feedback,
            JsonNode coveredCriteria,
            JsonNode gaps,
            JsonNode coreCriteria,
            JsonNode futureExtensions,
            OffsetDateTime answeredAt
    ) {
    }

    private record CompetencyRow(
            UUID nodeId,
            UUID competencyId,
            String canonicalKey,
            String title,
            String domain,
            String scopeDefinition,
            int requiredLevel,
            int verifiedLevel,
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
            String currentCompanyName,
            String currentRoleTitle,
            String finalGoal
    ) {
        static GoalRow empty() {
            return new GoalRow(null, null, null);
        }

        String currentGoal() {
            if (currentCompanyName == null && currentRoleTitle == null) {
                return null;
            }
            return String.join(
                    " · ",
                    List.of(
                            currentCompanyName == null ? "회사 미정" : currentCompanyName,
                            currentRoleTitle == null ? "직무 미정" : currentRoleTitle
                    )
            );
        }
    }

    private record AssessmentContext(
            CompetencyRow competency,
            TargetRow target,
            GoalRow goals
    ) {
        UUID competencyId() {
            return competency.competencyId();
        }

        int requiredLevel() {
            return competency.requiredLevel();
        }

        String canonicalKey() {
            return competency.canonicalKey();
        }

        String title() {
            return competency.title();
        }

        AiContracts.AssessmentCompetency competencyContract() {
            return new AiContracts.AssessmentCompetency(
                    competency.canonicalKey(),
                    competency.title(),
                    competency.domain(),
                    competency.scopeDefinition(),
                    competency.requiredLevel(),
                    competency.levelDefinition(),
                    competency.assessmentBlueprint()
            );
        }

        AiContracts.AssessmentTargetContext targetContract() {
            return new AiContracts.AssessmentTargetContext(
                    target.companyName(),
                    target.roleTitle(),
                    target.primaryTrack(),
                    target.domainContext(),
                    target.requirementSource(),
                    goals.currentGoal(),
                    goals.finalGoal()
            );
        }
    }

    private record AssessmentTurnRow(
            UUID id,
            int ordinal,
            String questionKind,
            String prompt,
            String codeSnippet,
            String answerText,
            Integer score,
            String verdict,
            String feedback,
            JsonNode coveredCriteria,
            JsonNode gaps,
            JsonNode coreCriteria,
            JsonNode futureExtensions,
            OffsetDateTime answeredAt
    ) {
    }

    private record SessionHeader(
            String status,
            UUID nodeId,
            UUID targetPostingId,
            Map<String, Integer> retainedScores
    ) {
    }

    private record SessionContext(
            String status,
            AssessmentContext context,
            List<AssessmentTurnRow> turns,
            Map<String, Integer> retainedScores
    ) {
    }

    private record ScoredTurn(String kind, int score) {
    }

    private record ScoreSummary(
            int attemptCount,
            double average,
            int minimum,
            Set<String> kinds,
            Map<String, Integer> bestScores
    ) {
    }

    private record AssessmentHeader(
            UUID id,
            UUID competencyId,
            String title,
            String canonicalKey,
            UUID targetPostingId,
            String companyName,
            String roleTitle,
            int requiredLevel,
            String status,
            int questionCount,
            Map<String, Integer> retainedScores,
            BigDecimal averageScore,
            int achievedLevel,
            BigDecimal confidence,
            String summary,
            JsonNode strengths,
            JsonNode gaps,
            JsonNode nextActions,
            String reviewStatus,
            String appealText,
            OffsetDateTime createdAt,
            OffsetDateTime completedAt
    ) {
    }

    private record ReviewTarget(
            UUID userId,
            UUID competencyId,
            int requiredLevel
    ) {
    }
}
