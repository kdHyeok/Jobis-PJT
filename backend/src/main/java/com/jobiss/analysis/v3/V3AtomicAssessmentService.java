package com.jobiss.analysis.v3;

import com.jobiss.analysis.AiAnalysisClient;

import com.jobiss.common.ApiException;
import com.jobiss.db.RlsTransactionExecutor;
import com.jobiss.security.SensitiveTextCipher;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

@Service
public class V3AtomicAssessmentService {

    private static final int SESSION_PASS_SCORE = 75;

    private final RlsTransactionExecutor rls;
    private final AiAnalysisClient aiClient;
    private final ObjectMapper objectMapper;
    private final SensitiveTextCipher sensitiveText;

    public V3AtomicAssessmentService(
            RlsTransactionExecutor rls,
            AiAnalysisClient aiClient,
            ObjectMapper objectMapper,
            SensitiveTextCipher sensitiveText
    ) {
        this.rls = rls;
        this.aiClient = aiClient;
        this.objectMapper = objectMapper;
        this.sensitiveText = sensitiveText;
    }

    public AssessmentView latest(UUID userId, String canonicalKey) {
        return rls.read(userId, jdbc -> latest(jdbc, canonicalKey));
    }

    public AssessmentView start(
            UUID userId,
            String canonicalKey,
            TargetContextRequest target
    ) {
        UUID sessionId = rls.write(userId, jdbc -> {
            CapabilityRow capability = capability(jdbc, canonicalKey);
            if ("SELF_CONFIRM".equals(capability.completionPolicy())) {
                throw conflict("이 공통 기초 역량은 문제 풀이 대신 직접 완료 확인을 사용합니다.");
            }
            UUID active = jdbc.sql("""
                            select id
                            from atomic_capability_assessment_sessions
                            where atomic_capability_id = :capabilityId
                              and status = 'IN_PROGRESS'
                            order by created_at desc
                            limit 1
                            """)
                    .param("capabilityId", capability.id())
                    .query(UUID.class)
                    .optional()
                    .orElse(null);
            if (active != null) {
                return active;
            }
            int requiredQuestionCount = requiredQuestionCount(capability.verificationMethods().size());
            JsonNode targetContext = target == null
                    ? objectMapper.createObjectNode()
                    : objectMapper.valueToTree(target);
            return jdbc.sql("""
                            insert into atomic_capability_assessment_sessions (
                                user_id,
                                atomic_capability_id,
                                required_question_count,
                                target_context
                            )
                            values (
                                :userId,
                                :capabilityId,
                                :requiredQuestionCount,
                                cast(:targetContext as jsonb)
                            )
                            returning id
                            """)
                    .param("userId", userId)
                    .param("capabilityId", capability.id())
                    .param("requiredQuestionCount", requiredQuestionCount)
                    .param("targetContext", writeJson(targetContext))
                    .query(UUID.class)
                    .single();
        });
        return ensureNextQuestion(userId, sessionId);
    }

    public JsonNode selfConfirm(UUID userId, String canonicalKey) {
        return rls.write(userId, jdbc -> {
            CapabilityRow capability = capability(jdbc, canonicalKey);
            if (!"SELF_CONFIRM".equals(capability.completionPolicy())) {
                throw conflict("이 원자 역량은 문제 또는 결과물 검증을 통과해야 합니다.");
            }
            String previous = jdbc.sql("""
                            select progress_state
                            from user_atomic_capabilities
                            where id = :capabilityId
                            for update
                            """)
                    .param("capabilityId", capability.id())
                    .query(String.class)
                    .single();
            if (!"VERIFIED".equals(previous)) {
                jdbc.sql("""
                                update user_atomic_capabilities
                                set progress_state = 'VERIFIED', verified_at = now()
                                where id = :capabilityId
                                """)
                        .param("capabilityId", capability.id())
                        .update();
                jdbc.sql("""
                                insert into user_atomic_capability_events (
                                    user_id,
                                    atomic_capability_id,
                                    from_state,
                                    to_state,
                                    event_type,
                                    source_ref
                                )
                                values (
                                    :userId,
                                    :capabilityId,
                                    :fromState,
                                    'VERIFIED',
                                    'USER_CLAIM',
                                    :sourceRef
                                )
                                """)
                        .param("userId", userId)
                        .param("capabilityId", capability.id())
                        .param("fromState", previous)
                        .param("sourceRef", "self-confirm:" + canonicalKey)
                        .update();
            }
            ObjectNode result = objectMapper.createObjectNode();
            result.put("canonicalKey", canonicalKey);
            result.put("progressState", "VERIFIED");
            result.put("completionPolicy", capability.completionPolicy());
            return result;
        });
    }

    public AssessmentView answer(UUID userId, UUID sessionId, String answer) {
        if (answer == null || answer.isBlank()) {
            throw invalid("답변을 입력해 주세요.");
        }
        GradeContext context = rls.read(userId, jdbc -> gradeContext(jdbc, sessionId));
        JsonNode request = objectMapper.createObjectNode()
                .set("capability", context.capability());
        ((ObjectNode) request).set("target", context.target());
        ((ObjectNode) request).set("question", context.question());
        ((ObjectNode) request).put("answer", answer.trim());
        JsonNode grade = aiClient.gradeAssessmentAnswer(request);

        AssessmentView view = rls.write(userId, jdbc -> {
            SessionLock locked = lockSession(jdbc, sessionId);
            if (!"IN_PROGRESS".equals(locked.status())) {
                return view(jdbc, sessionId);
            }
            int updated = jdbc.sql("""
                            update atomic_capability_assessment_turns
                            set
                                answer_text = :answer,
                                grade = cast(:grade as jsonb),
                                score = :score,
                                passed = :passed,
                                answered_at = now()
                            where id = :turnId
                              and answer_text is null
                            """)
                    .param("answer", sensitiveText.encrypt(answer.trim()))
                    .param("grade", writeJson(grade))
                    .param("score", grade.path("score").intValue())
                    .param("passed", grade.path("passed").booleanValue())
                    .param("turnId", context.turnId())
                    .update();
            if (updated != 1) {
                return view(jdbc, sessionId);
            }

            ScoreSummary score = scoreSummary(jdbc, sessionId);
            if (score.answered() >= locked.requiredQuestionCount()) {
                boolean passed = sessionPasses(score.average(), score.allPassed());
                String status = passed ? "PASSED" : "NEEDS_STUDY";
                jdbc.sql("""
                                update atomic_capability_assessment_sessions
                                set
                                    status = :status,
                                    answered_question_count = :answered,
                                    average_score = :average,
                                    completed_at = now()
                                where id = :sessionId
                                """)
                        .param("status", status)
                        .param("answered", score.answered())
                        .param("average", score.average())
                        .param("sessionId", sessionId)
                        .update();
                if (passed) {
                    verifyCapability(jdbc, userId, locked.capabilityId(), sessionId);
                }
            } else {
                jdbc.sql("""
                                update atomic_capability_assessment_sessions
                                set
                                    answered_question_count = :answered,
                                    average_score = :average
                                where id = :sessionId
                                """)
                        .param("answered", score.answered())
                        .param("average", score.average())
                        .param("sessionId", sessionId)
                        .update();
            }
            return view(jdbc, sessionId);
        });
        if ("IN_PROGRESS".equals(view.status())) {
            return ensureNextQuestion(userId, sessionId);
        }
        return view;
    }

    public AssessmentView abandon(UUID userId, UUID sessionId) {
        return rls.write(userId, jdbc -> {
            int updated = jdbc.sql("""
                            update atomic_capability_assessment_sessions
                            set status = 'ABANDONED', completed_at = now()
                            where id = :sessionId
                              and status = 'IN_PROGRESS'
                            """)
                    .param("sessionId", sessionId)
                    .update();
            if (updated == 0) {
                AssessmentView existing = view(jdbc, sessionId);
                if (!"ABANDONED".equals(existing.status())) {
                    throw conflict("진행 중인 검증만 중단할 수 있습니다.");
                }
            }
            return view(jdbc, sessionId);
        });
    }

    public AssessmentView requestReview(UUID userId, UUID sessionId, String reason) {
        if (reason == null || reason.isBlank()) {
            throw invalid("검토가 필요한 이유를 입력해 주세요.");
        }
        return rls.write(userId, jdbc -> {
            SessionLock session = lockSession(jdbc, sessionId);
            if ("PASSED".equals(session.status()) || "ABANDONED".equals(session.status())) {
                throw conflict("이 검증 상태에서는 검토를 요청할 수 없습니다.");
            }
            jdbc.sql("""
                            insert into atomic_capability_assessment_reviews (
                                user_id,
                                session_id,
                                reason
                            )
                            values (:userId, :sessionId, :reason)
                            on conflict (user_id, session_id) do update
                            set reason = excluded.reason
                            where atomic_capability_assessment_reviews.status = 'PENDING'
                            """)
                    .param("userId", userId)
                    .param("sessionId", sessionId)
                    .param("reason", reason.trim())
                    .update();
            jdbc.sql("""
                            update atomic_capability_assessment_sessions
                            set status = 'REVIEW_REQUESTED', completed_at = coalesce(completed_at, now())
                            where id = :sessionId
                            """)
                    .param("sessionId", sessionId)
                    .update();
            return view(jdbc, sessionId);
        });
    }

    public List<AssessmentReviewView> operatorReviews(UUID operatorId, String status) {
        return rls.read(operatorId, jdbc -> {
            ensureOperator(jdbc);
            String normalized = status == null || status.isBlank()
                    ? "PENDING"
                    : status.trim().toUpperCase();
            return jdbc.sql("""
                            select
                                review.id,
                                review.session_id,
                                review.user_id,
                                concat('사용자 ', left(review.user_id::text, 8)) as user_label,
                                capability.canonical_key,
                                capability.title,
                                session.average_score,
                                review.status,
                                review.reason,
                                review.requested_at
                            from atomic_capability_assessment_reviews review
                            join atomic_capability_assessment_sessions session
                              on session.id = review.session_id
                            join user_atomic_capabilities capability
                              on capability.id = session.atomic_capability_id
                            where review.status = :status
                            order by review.requested_at
                            limit 200
                            """)
                    .param("status", normalized)
                    .query((rs, rowNum) -> new AssessmentReviewView(
                            rs.getObject("id", UUID.class),
                            rs.getObject("session_id", UUID.class),
                            rs.getObject("user_id", UUID.class),
                            rs.getString("user_label"),
                            rs.getString("canonical_key"),
                            rs.getString("title"),
                            rs.getObject("average_score", Integer.class),
                            rs.getString("status"),
                            rs.getString("reason"),
                            rs.getObject("requested_at", OffsetDateTime.class)
                    ))
                    .list();
        });
    }

    public AssessmentView operatorReview(UUID operatorId, UUID sessionId) {
        return rls.read(operatorId, jdbc -> {
            ensureOperator(jdbc);
            return view(jdbc, sessionId);
        });
    }

    public void resolveReview(
            UUID operatorId,
            UUID sessionId,
            boolean approved,
            String operatorNote
    ) {
        rls.write(operatorId, jdbc -> {
            ensureOperator(jdbc);
            ReviewTarget target = jdbc.sql("""
                            select
                                review.id,
                                review.user_id,
                                session.atomic_capability_id
                            from atomic_capability_assessment_reviews review
                            join atomic_capability_assessment_sessions session
                              on session.id = review.session_id
                            where review.session_id = :sessionId
                              and review.status = 'PENDING'
                            for update of review
                            """)
                    .param("sessionId", sessionId)
                    .query((rs, rowNum) -> new ReviewTarget(
                            rs.getObject("id", UUID.class),
                            rs.getObject("user_id", UUID.class),
                            rs.getObject("atomic_capability_id", UUID.class)
                    ))
                    .optional()
                    .orElseThrow(() -> notFound("대기 중인 원자 역량 검토 요청을 찾을 수 없습니다."));
            String reviewStatus = approved ? "APPROVED" : "REJECTED";
            jdbc.sql("""
                            update atomic_capability_assessment_reviews
                            set
                                status = :status,
                                operator_note = :operatorNote,
                                resolved_at = now(),
                                resolved_by = :operatorId
                            where id = :reviewId
                            """)
                    .param("status", reviewStatus)
                    .param("operatorNote", operatorNote)
                    .param("operatorId", operatorId)
                    .param("reviewId", target.reviewId())
                    .update();
            jdbc.sql("""
                            update atomic_capability_assessment_sessions
                            set status = :status, completed_at = coalesce(completed_at, now())
                            where id = :sessionId
                            """)
                    .param("status", approved ? "PASSED" : "NEEDS_STUDY")
                    .param("sessionId", sessionId)
                    .update();
            if (approved) {
                String previous = jdbc.sql("""
                                select progress_state
                                from user_atomic_capabilities
                                where id = :capabilityId
                                for update
                                """)
                        .param("capabilityId", target.capabilityId())
                        .query(String.class)
                        .single();
                jdbc.sql("""
                                update user_atomic_capabilities
                                set progress_state = 'VERIFIED', verified_at = coalesce(verified_at, now())
                                where id = :capabilityId
                                """)
                        .param("capabilityId", target.capabilityId())
                        .update();
                if (!"VERIFIED".equals(previous)) {
                    jdbc.sql("""
                                    insert into user_atomic_capability_events (
                                        user_id,
                                        atomic_capability_id,
                                        from_state,
                                        to_state,
                                        event_type,
                                        source_ref
                                    )
                                    values (
                                        :userId,
                                        :capabilityId,
                                        :fromState,
                                        'VERIFIED',
                                        'OPERATOR_REVIEW',
                                        :sourceRef
                                    )
                                    """)
                            .param("userId", target.userId())
                            .param("capabilityId", target.capabilityId())
                            .param("fromState", previous)
                            .param("sourceRef", "assessment-review:" + target.reviewId())
                            .update();
                }
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
                                'ASSESSMENT_REVIEW_RESOLVED',
                                :title,
                                :body,
                                jsonb_build_object(
                                    'referenceType', 'ATOMIC_ASSESSMENT',
                                    'referenceId', :referenceId
                                )
                            )
                            """)
                    .param("userId", target.userId())
                    .param("title", approved ? "원자 역량 검토가 승인되었습니다." : "원자 역량 검토 결과를 확인해 주세요.")
                    .param("body", operatorNote == null || operatorNote.isBlank()
                            ? (approved ? "운영자 검토로 역량이 인증되었습니다." : "학습 후 새 문제로 다시 도전해 주세요.")
                            : operatorNote.trim())
                    .param("referenceId", sessionId)
                    .update();
            return null;
        });
    }

    private AssessmentView ensureNextQuestion(UUID userId, UUID sessionId) {
        QuestionContext context = rls.read(userId, jdbc -> questionContext(jdbc, sessionId));
        if (!"IN_PROGRESS".equals(context.status()) || context.hasOpenQuestion()) {
            return rls.read(userId, jdbc -> view(jdbc, sessionId));
        }
        if (context.completedTurns().size() >= context.requiredQuestionCount()) {
            return rls.read(userId, jdbc -> view(jdbc, sessionId));
        }

        ObjectNode request = objectMapper.createObjectNode();
        request.put("sessionId", sessionId.toString());
        request.set("capability", context.capability());
        request.set("target", context.target());
        request.set("completedTurns", context.completedTurns());
        request.put("ordinal", context.completedTurns().size() + 1);
        JsonNode question = aiClient.createAssessmentQuestion(request);

        return rls.write(userId, jdbc -> {
            SessionLock locked = lockSession(jdbc, sessionId);
            if (!"IN_PROGRESS".equals(locked.status())) {
                return view(jdbc, sessionId);
            }
            jdbc.sql("""
                            insert into atomic_capability_assessment_turns (
                                user_id,
                                session_id,
                                ordinal,
                                question_id,
                                method,
                                question
                            )
                            values (
                                :userId,
                                :sessionId,
                                :ordinal,
                                :questionId,
                                :method,
                                cast(:question as jsonb)
                            )
                            on conflict (user_id, session_id, ordinal) do nothing
                            """)
                    .param("userId", userId)
                    .param("sessionId", sessionId)
                    .param("ordinal", question.path("ordinal").intValue())
                    .param("questionId", question.path("questionId").stringValue())
                    .param("method", question.path("method").stringValue())
                    .param("question", writeJson(question))
                    .update();
            return view(jdbc, sessionId);
        });
    }

    private CapabilityRow capability(JdbcClient jdbc, String canonicalKey) {
        return jdbc.sql("""
                        select
                            id,
                            canonical_key,
                            technology_key,
                            title,
                            coalesce(objective, scope_definition) as objective,
                            scope_definition,
                            excluded_scope::text,
                            verification_methods::text,
                            graph_version,
                            graph_node_version,
                            completion_policy
                        from user_atomic_capabilities
                        where canonical_key = :canonicalKey
                        """)
                .param("canonicalKey", canonicalKey)
                .query((rs, rowNum) -> new CapabilityRow(
                        rs.getObject("id", UUID.class),
                        rs.getString("canonical_key"),
                        rs.getString("technology_key"),
                        rs.getString("title"),
                        rs.getString("objective"),
                        rs.getString("scope_definition"),
                        readJson(rs.getString("excluded_scope")),
                        readJson(rs.getString("verification_methods")),
                        rs.getString("graph_version"),
                        rs.getInt("graph_node_version"),
                        rs.getString("completion_policy")
                ))
                .optional()
                .orElseThrow(() -> new ApiException(
                        HttpStatus.NOT_FOUND,
                        "ATOMIC_CAPABILITY_NOT_FOUND",
                        "적용된 로드맵에서 해당 원자 역량을 찾을 수 없습니다."
                ));
    }

    private ObjectNode capabilityJson(CapabilityRow row) {
        ObjectNode result = objectMapper.createObjectNode();
        result.put("canonicalKey", row.canonicalKey());
        result.put("technologyKey", row.technologyKey());
        result.put("displayName", row.title());
        result.put("objective", row.objective());
        result.put("scopeDefinition", row.scopeDefinition());
        result.set("excludedScope", row.excludedScope());
        result.set("verificationMethods", row.verificationMethods());
        result.put("graphVersion", row.graphVersion());
        result.put("graphNodeVersion", row.graphNodeVersion());
        return result;
    }

    private QuestionContext questionContext(JdbcClient jdbc, UUID sessionId) {
        SessionContext session = sessionContext(jdbc, sessionId);
        ArrayNode turns = objectMapper.createArrayNode();
        boolean[] hasOpen = {false};
        jdbc.sql("""
                        select ordinal, question_id, method, question::text, answer_text, score, passed, grade::text
                        from atomic_capability_assessment_turns
                        where session_id = :sessionId
                        order by ordinal
                        """)
                .param("sessionId", sessionId)
                .query((rs, rowNum) -> {
                    if (rs.getString("answer_text") == null) {
                        hasOpen[0] = true;
                        return null;
                    }
                    ObjectNode turn = objectMapper.createObjectNode();
                    turn.put("questionId", rs.getString("question_id"));
                    turn.put("ordinal", rs.getInt("ordinal"));
                    turn.put("method", rs.getString("method"));
                    turn.put("prompt", readJson(rs.getString("question")).path("prompt").stringValue());
                    turn.put("answer", sensitiveText.decrypt(rs.getString("answer_text")));
                    turn.put("score", rs.getInt("score"));
                    turn.put("passed", rs.getBoolean("passed"));
                    JsonNode grade = readJson(rs.getString("grade"));
                    turn.set("gaps", grade.path("gaps").isArray()
                            ? grade.path("gaps")
                            : objectMapper.createArrayNode());
                    return turn;
                })
                .list()
                .stream()
                .filter(item -> item != null)
                .forEach(turns::add);
        return new QuestionContext(
                session.status(),
                session.requiredQuestionCount(),
                capabilityJson(session.capability()),
                session.target(),
                turns,
                hasOpen[0]
        );
    }

    private GradeContext gradeContext(JdbcClient jdbc, UUID sessionId) {
        SessionContext session = sessionContext(jdbc, sessionId);
        if (!"IN_PROGRESS".equals(session.status())) {
            throw conflict("진행 중인 검증이 아닙니다.");
        }
        return jdbc.sql("""
                        select id, question::text
                        from atomic_capability_assessment_turns
                        where session_id = :sessionId
                          and answer_text is null
                        order by ordinal
                        limit 1
                        """)
                .param("sessionId", sessionId)
                .query((rs, rowNum) -> new GradeContext(
                        rs.getObject("id", UUID.class),
                        capabilityJson(session.capability()),
                        session.target(),
                        readJson(rs.getString("question"))
                ))
                .optional()
                .orElseThrow(() -> conflict("답변할 검증 문제가 없습니다."));
    }

    private SessionContext sessionContext(JdbcClient jdbc, UUID sessionId) {
        return jdbc.sql("""
                        select
                            session.status,
                            session.required_question_count,
                            session.target_context::text,
                            capability.id,
                            capability.canonical_key,
                            capability.technology_key,
                            capability.title,
                            coalesce(capability.objective, capability.scope_definition) as objective,
                            capability.scope_definition,
                            capability.excluded_scope::text,
                            capability.verification_methods::text,
                            capability.graph_version,
                            capability.graph_node_version,
                            capability.completion_policy
                        from atomic_capability_assessment_sessions session
                        join user_atomic_capabilities capability
                          on capability.id = session.atomic_capability_id
                        where session.id = :sessionId
                        """)
                .param("sessionId", sessionId)
                .query((rs, rowNum) -> new SessionContext(
                        rs.getString("status"),
                        rs.getInt("required_question_count"),
                        readJson(rs.getString("target_context")),
                        new CapabilityRow(
                                rs.getObject("id", UUID.class),
                                rs.getString("canonical_key"),
                                rs.getString("technology_key"),
                                rs.getString("title"),
                                rs.getString("objective"),
                                rs.getString("scope_definition"),
                                readJson(rs.getString("excluded_scope")),
                                readJson(rs.getString("verification_methods")),
                                rs.getString("graph_version"),
                                rs.getInt("graph_node_version"),
                                rs.getString("completion_policy")
                        )
                ))
                .optional()
                .orElseThrow(() -> notFound("검증 세션을 찾을 수 없습니다."));
    }

    private SessionLock lockSession(JdbcClient jdbc, UUID sessionId) {
        return jdbc.sql("""
                        select status, required_question_count, atomic_capability_id
                        from atomic_capability_assessment_sessions
                        where id = :sessionId
                        for update
                        """)
                .param("sessionId", sessionId)
                .query((rs, rowNum) -> new SessionLock(
                        rs.getString("status"),
                        rs.getInt("required_question_count"),
                        rs.getObject("atomic_capability_id", UUID.class)
                ))
                .optional()
                .orElseThrow(() -> notFound("검증 세션을 찾을 수 없습니다."));
    }

    private ScoreSummary scoreSummary(JdbcClient jdbc, UUID sessionId) {
        return jdbc.sql("""
                        select
                            count(*)::integer as answered,
                            coalesce(round(avg(score)), 0)::integer as average,
                            coalesce(bool_and(passed), false) as all_passed
                        from atomic_capability_assessment_turns
                        where session_id = :sessionId
                          and answer_text is not null
                        """)
                .param("sessionId", sessionId)
                .query((rs, rowNum) -> new ScoreSummary(
                        rs.getInt("answered"),
                        rs.getInt("average"),
                        rs.getBoolean("all_passed")
                ))
                .single();
    }

    private void verifyCapability(
            JdbcClient jdbc,
            UUID userId,
            UUID capabilityId,
            UUID sessionId
    ) {
        String previous = jdbc.sql("""
                        select progress_state
                        from user_atomic_capabilities
                        where id = :capabilityId
                        for update
                        """)
                .param("capabilityId", capabilityId)
                .query(String.class)
                .single();
        jdbc.sql("""
                        update user_atomic_capabilities
                        set progress_state = 'VERIFIED', verified_at = coalesce(verified_at, now())
                        where id = :capabilityId
                        """)
                .param("capabilityId", capabilityId)
                .update();
        if (!"VERIFIED".equals(previous)) {
            jdbc.sql("""
                            insert into user_atomic_capability_events (
                                user_id,
                                atomic_capability_id,
                                from_state,
                                to_state,
                                event_type,
                                source_ref
                            )
                            values (
                                :userId,
                                :capabilityId,
                                :fromState,
                                'VERIFIED',
                                'ASSESSMENT',
                                :sourceRef
                            )
                            """)
                    .param("userId", userId)
                    .param("capabilityId", capabilityId)
                    .param("fromState", previous)
                    .param("sourceRef", "assessment:" + sessionId)
                    .update();
        }
    }

    private AssessmentView latest(JdbcClient jdbc, String canonicalKey) {
        UUID sessionId = jdbc.sql("""
                        select session.id
                        from atomic_capability_assessment_sessions session
                        join user_atomic_capabilities capability
                          on capability.id = session.atomic_capability_id
                        where capability.canonical_key = :canonicalKey
                        order by session.created_at desc
                        limit 1
                        """)
                .param("canonicalKey", canonicalKey)
                .query(UUID.class)
                .optional()
                .orElse(null);
        return sessionId == null ? null : view(jdbc, sessionId);
    }

    private AssessmentView view(JdbcClient jdbc, UUID sessionId) {
        AssessmentHead head = jdbc.sql("""
                        select
                            session.id,
                            capability.canonical_key,
                            capability.title,
                            capability.scope_definition,
                            capability.verification_methods::text,
                            session.status,
                            session.required_question_count,
                            session.answered_question_count,
                            session.average_score,
                            session.target_context::text,
                            session.created_at,
                            session.completed_at,
                            exists (
                                select 1
                                from atomic_capability_assessment_reviews review
                                where review.session_id = session.id
                                  and review.status = 'PENDING'
                            ) as review_pending
                        from atomic_capability_assessment_sessions session
                        join user_atomic_capabilities capability
                          on capability.id = session.atomic_capability_id
                        where session.id = :sessionId
                        """)
                .param("sessionId", sessionId)
                .query((rs, rowNum) -> new AssessmentHead(
                        rs.getObject("id", UUID.class),
                        rs.getString("canonical_key"),
                        rs.getString("title"),
                        rs.getString("scope_definition"),
                        strings(readJson(rs.getString("verification_methods"))),
                        rs.getString("status"),
                        rs.getInt("required_question_count"),
                        rs.getInt("answered_question_count"),
                        rs.getObject("average_score", Integer.class),
                        readJson(rs.getString("target_context")),
                        rs.getObject("created_at", OffsetDateTime.class),
                        rs.getObject("completed_at", OffsetDateTime.class),
                        rs.getBoolean("review_pending")
                ))
                .optional()
                .orElseThrow(() -> notFound("검증 세션을 찾을 수 없습니다."));
        List<TurnView> turns = jdbc.sql("""
                        select
                            id,
                            ordinal,
                            method,
                            question::text,
                            answer_text,
                            grade::text,
                            score,
                            passed,
                            created_at,
                            answered_at
                        from atomic_capability_assessment_turns
                        where session_id = :sessionId
                        order by ordinal
                        """)
                .param("sessionId", sessionId)
                .query((rs, rowNum) -> new TurnView(
                        rs.getObject("id", UUID.class),
                        rs.getInt("ordinal"),
                        rs.getString("method"),
                        readJson(rs.getString("question")),
                        sensitiveText.decrypt(rs.getString("answer_text")),
                        readJson(rs.getString("grade")),
                        rs.getObject("score", Integer.class),
                        rs.getObject("passed", Boolean.class),
                        rs.getObject("created_at", OffsetDateTime.class),
                        rs.getObject("answered_at", OffsetDateTime.class)
                ))
                .list();
        return new AssessmentView(
                head.id(),
                head.canonicalKey(),
                head.title(),
                head.scopeDefinition(),
                head.verificationMethods(),
                head.status(),
                head.requiredQuestionCount(),
                head.answeredQuestionCount(),
                head.averageScore(),
                head.targetContext(),
                turns,
                head.reviewPending(),
                head.createdAt(),
                head.completedAt()
        );
    }

    private List<String> strings(JsonNode values) {
        if (values == null || !values.isArray()) {
            return List.of();
        }
        return values.valueStream().map(item -> item.stringValue("")).toList();
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

    private JsonNode readJson(String value) {
        if (value == null || value.isBlank()) {
            return objectMapper.createObjectNode();
        }
        return objectMapper.readTree(value);
    }

    private String writeJson(JsonNode value) {
        return objectMapper.writeValueAsString(value);
    }

    private ApiException invalid(String message) {
        return new ApiException(HttpStatus.BAD_REQUEST, "INVALID_ATOMIC_ASSESSMENT", message);
    }

    private ApiException conflict(String message) {
        return new ApiException(HttpStatus.CONFLICT, "ATOMIC_ASSESSMENT_STATE_CONFLICT", message);
    }

    private ApiException notFound(String message) {
        return new ApiException(HttpStatus.NOT_FOUND, "ATOMIC_ASSESSMENT_NOT_FOUND", message);
    }

    static int requiredQuestionCount(int verificationMethodCount) {
        return Math.min(3, Math.max(2, verificationMethodCount));
    }

    static boolean sessionPasses(int averageScore, boolean everyQuestionPassed) {
        return everyQuestionPassed && averageScore >= SESSION_PASS_SCORE;
    }

    public record TargetContextRequest(
            String companyName,
            String roleTitle,
            String projectTaskTitle,
            String projectTaskObjective,
            String currentGoal,
            String finalGoal
    ) {
    }

    public record AssessmentView(
            UUID id,
            String capabilityKey,
            String title,
            String scopeDefinition,
            List<String> verificationMethods,
            String status,
            int requiredQuestionCount,
            int answeredQuestionCount,
            Integer averageScore,
            JsonNode targetContext,
            List<TurnView> turns,
            boolean reviewPending,
            OffsetDateTime createdAt,
            OffsetDateTime completedAt
    ) {
    }

    public record TurnView(
            UUID id,
            int ordinal,
            String method,
            JsonNode question,
            String answerText,
            JsonNode grade,
            Integer score,
            Boolean passed,
            OffsetDateTime createdAt,
            OffsetDateTime answeredAt
    ) {
    }

    public record AssessmentReviewView(
            UUID id,
            UUID sessionId,
            UUID userId,
            String userLabel,
            String capabilityKey,
            String title,
            Integer averageScore,
            String status,
            String reason,
            OffsetDateTime requestedAt
    ) {
    }

    private record CapabilityRow(
            UUID id,
            String canonicalKey,
            String technologyKey,
            String title,
            String objective,
            String scopeDefinition,
            JsonNode excludedScope,
            JsonNode verificationMethods,
            String graphVersion,
            int graphNodeVersion,
            String completionPolicy
    ) {
    }

    private record SessionContext(
            String status,
            int requiredQuestionCount,
            JsonNode target,
            CapabilityRow capability
    ) {
    }

    private record QuestionContext(
            String status,
            int requiredQuestionCount,
            JsonNode capability,
            JsonNode target,
            ArrayNode completedTurns,
            boolean hasOpenQuestion
    ) {
    }

    private record GradeContext(
            UUID turnId,
            JsonNode capability,
            JsonNode target,
            JsonNode question
    ) {
    }

    private record SessionLock(String status, int requiredQuestionCount, UUID capabilityId) {
    }

    private record ScoreSummary(int answered, int average, boolean allPassed) {
    }

    private record AssessmentHead(
            UUID id,
            String canonicalKey,
            String title,
            String scopeDefinition,
            List<String> verificationMethods,
            String status,
            int requiredQuestionCount,
            int answeredQuestionCount,
            Integer averageScore,
            JsonNode targetContext,
            OffsetDateTime createdAt,
            OffsetDateTime completedAt,
            boolean reviewPending
    ) {
    }

    private record ReviewTarget(UUID reviewId, UUID userId, UUID capabilityId) {
    }
}
