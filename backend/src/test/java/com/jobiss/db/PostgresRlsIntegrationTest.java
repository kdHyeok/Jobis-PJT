package com.jobiss.db;

import com.jobiss.analysis.AiUsageLimitService;
import com.jobiss.analysis.AnalysisJobService;
import com.jobiss.analysis.AnalysisTaskRegistry;
import com.jobiss.analysis.AiAnalysisClient;
import com.jobiss.analysis.v3.V3AtomicAssessmentService;
import com.jobiss.config.DataProtectionProperties;
import com.jobiss.posting.JobPostingService;
import com.jobiss.security.SensitiveTextCipher;
import com.jobiss.roadmap.RoadmapService;
import com.jobiss.config.DataProtectionProperties;
import com.jobiss.security.SensitiveTextCipher;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.postgresql.PostgreSQLContainer;
import tools.jackson.databind.ObjectMapper;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

@Testcontainers(disabledWithoutDocker = true)
class PostgresRlsIntegrationTest {

    private static final String APP_USER = "jobiss_app";
    private static final String APP_PASSWORD = "jobiss_app_test";

    @Container
    static final PostgreSQLContainer postgres =
            new PostgreSQLContainer("postgres:17-alpine")
                    .withDatabaseName("jobiss")
                    .withUsername("jobiss_migrator")
                    .withPassword("jobiss_migrator_test");

    @BeforeAll
    static void migrate() throws Exception {
        try (Connection connection = DriverManager.getConnection(
                postgres.getJdbcUrl(),
                postgres.getUsername(),
                postgres.getPassword()
        ); Statement statement = connection.createStatement()) {
            statement.execute("""
                    create role jobiss_app
                    login password 'jobiss_app_test'
                    nosuperuser nocreatedb nocreaterole noinherit nobypassrls
                    """);
            statement.execute("grant connect on database jobiss to jobiss_app");
        }

        Flyway.configure()
                .dataSource(
                        postgres.getJdbcUrl(),
                        postgres.getUsername(),
                        postgres.getPassword()
                )
                .locations("classpath:db/migration")
                .load()
                .migrate();
    }

    @Test
    void oneUserCannotReadAnotherUsersRow() throws Exception {
        UUID alice = UUID.randomUUID();
        UUID bob = UUID.randomUUID();

        try (Connection connection = DriverManager.getConnection(
                postgres.getJdbcUrl(),
                APP_USER,
                APP_PASSWORD
        ); Statement statement = connection.createStatement()) {
            connection.setAutoCommit(false);
            setUser(statement, alice);
            statement.executeUpdate("""
                    insert into users (id, email, display_name)
                    values ('%s', 'alice@example.com', 'Alice')
                    """.formatted(alice));
            connection.commit();

            setUser(statement, bob);
            try (ResultSet result = statement.executeQuery("select count(*) from users")) {
                result.next();
                assertThat(result.getInt(1)).isZero();
            }
            connection.rollback();

            setUser(statement, alice);
            try (ResultSet result = statement.executeQuery("select count(*) from users")) {
                result.next();
                assertThat(result.getInt(1)).isEqualTo(1);
            }
            connection.rollback();
        }
    }

    @Test
    void logoutRevokesEveryPreviouslyIssuedAccessTokenForTheAuthenticatedUser() throws Exception {
        UUID userId = UUID.randomUUID();
        UUID anotherUserId = UUID.randomUUID();

        try (Connection connection = DriverManager.getConnection(
                postgres.getJdbcUrl(),
                APP_USER,
                APP_PASSWORD
        ); Statement statement = connection.createStatement()) {
            connection.setAutoCommit(false);
            setUser(statement, userId);
            statement.executeUpdate("""
                    insert into users (id, email, display_name)
                    values ('%s', 'logout-owner@example.com', 'Logout owner')
                    """.formatted(userId));
            statement.executeUpdate("""
                    insert into auth_identities (user_id, email, password_hash)
                    values ('%s', 'logout-owner@example.com', 'test-only-hash')
                    """.formatted(userId));

            try (ResultSet before = statement.executeQuery(
                    "select current_auth_version('%s'::uuid)".formatted(userId)
            )) {
                before.next();
                assertThat(before.getLong(1)).isEqualTo(1L);
            }
            try (ResultSet revoked = statement.executeQuery(
                    "select invalidate_current_auth_tokens('%s'::uuid)".formatted(userId)
            )) {
                revoked.next();
                assertThat(revoked.getLong(1)).isEqualTo(2L);
            }
            connection.rollback();

            setUser(statement, anotherUserId);
            assertThatThrownBy(() -> statement.executeQuery(
                    "select invalidate_current_auth_tokens('%s'::uuid)".formatted(userId)
            )).hasMessageContaining("auth identity owner mismatch");
            connection.rollback();
        }
    }

    @Test
    void careerMergeUndoHistoryIsPrivateToItsOwner() throws Exception {
        UUID alice = UUID.randomUUID();
        UUID bob = UUID.randomUUID();
        UUID firstFragment = UUID.randomUUID();
        UUID secondFragment = UUID.randomUUID();

        try (Connection connection = DriverManager.getConnection(
                postgres.getJdbcUrl(),
                APP_USER,
                APP_PASSWORD
        ); Statement statement = connection.createStatement()) {
            connection.setAutoCommit(false);
            setUser(statement, alice);
            statement.executeUpdate("""
                    insert into users (id, email, display_name)
                    values ('%s', 'merge-alice@example.com', 'Merge Alice')
                    """.formatted(alice));
            statement.executeUpdate("""
                    insert into career_fragment_merge_events (
                        user_id, target_fragment_id, fragment_ids, before_snapshot
                    ) values (
                        '%s', '%s', array['%s'::uuid, '%s'::uuid], '[]'::jsonb
                    )
                    """.formatted(alice, firstFragment, firstFragment, secondFragment));
            connection.commit();

            setUser(statement, bob);
            try (ResultSet hidden = statement.executeQuery(
                    "select count(*) from career_fragment_merge_events"
            )) {
                hidden.next();
                assertThat(hidden.getInt(1)).isZero();
            }
            connection.rollback();

            setUser(statement, alice);
            try (ResultSet visible = statement.executeQuery(
                    "select count(*) from career_fragment_merge_events"
            )) {
                visible.next();
                assertThat(visible.getInt(1)).isEqualTo(1);
            }
            connection.rollback();
        }
    }

    @Test
    void atomicAssessmentRowsAreIsolatedByUser() throws Exception {
        UUID alice = UUID.randomUUID();
        UUID bob = UUID.randomUUID();

        try (Connection connection = DriverManager.getConnection(
                postgres.getJdbcUrl(),
                APP_USER,
                APP_PASSWORD
        ); Statement statement = connection.createStatement()) {
            connection.setAutoCommit(false);

            setUser(statement, alice);
            statement.executeUpdate("""
                    insert into users (id, email, display_name)
                    values ('%s', 'atomic-alice@example.com', 'Atomic Alice')
                    """.formatted(alice));
            statement.executeUpdate("""
                    insert into user_atomic_capabilities (
                        user_id,
                        canonical_key,
                        graph_version,
                        graph_node_version,
                        technology_key,
                        title,
                        scope_definition,
                        objective,
                        verification_methods,
                        completion_policy
                    ) values (
                        '%s',
                        'java.exceptions',
                        '0.1.0-alpha.1',
                        1,
                        'lang.java',
                        '예외 정의와 처리',
                        'checked·unchecked 예외와 throw·catch·finally',
                        '실패를 예외로 표현하고 처리한다.',
                        '["IMPLEMENT", "DEBUG"]',
                        'ASSESSMENT'
                    )
                    """.formatted(alice));
            statement.executeUpdate("""
                    insert into atomic_capability_assessment_sessions (
                        user_id,
                        atomic_capability_id,
                        required_question_count
                    )
                    select user_id, id, 2
                    from user_atomic_capabilities
                    where canonical_key = 'java.exceptions'
                    """);
            connection.commit();

            setUser(statement, bob);
            statement.executeUpdate("""
                    insert into users (id, email, display_name)
                    values ('%s', 'atomic-bob@example.com', 'Atomic Bob')
                    """.formatted(bob));

            try (ResultSet capabilities = statement.executeQuery(
                    "select count(*) from user_atomic_capabilities"
            )) {
                capabilities.next();
                assertThat(capabilities.getInt(1)).isZero();
            }
            try (ResultSet sessions = statement.executeQuery(
                    "select count(*) from atomic_capability_assessment_sessions"
            )) {
                sessions.next();
                assertThat(sessions.getInt(1)).isZero();
            }
            connection.rollback();
        }
    }

    @Test
    void atomicAssessmentPassSelfConfirmAndOperatorReviewChangeOnlyApprovedState() {
        UUID userId = UUID.randomUUID();
        UUID operatorId = UUID.randomUUID();
        DriverManagerDataSource dataSource = new DriverManagerDataSource(
                postgres.getJdbcUrl(),
                APP_USER,
                APP_PASSWORD
        );
        RlsTransactionExecutor rls = new RlsTransactionExecutor(
                JdbcClient.create(dataSource),
                new org.springframework.transaction.support.TransactionTemplate(
                        new DataSourceTransactionManager(dataSource)
                )
        );
        ObjectMapper objectMapper = new ObjectMapper();
        AiAnalysisClient aiClient = mock(AiAnalysisClient.class);
        when(aiClient.createAssessmentQuestion(any())).thenAnswer(invocation -> {
            var request = (tools.jackson.databind.JsonNode) invocation.getArgument(0);
            int ordinal = request.path("ordinal").intValue();
            String sessionId = request.path("sessionId").stringValue();
            return objectMapper.readTree("""
                    {
                      "contractVersion":"jobis.ai.v3alpha1",
                      "questionId":"question:%s:%d",
                      "sessionId":"%s",
                      "capabilityKey":"java.exceptions",
                      "ordinal":%d,
                      "method":"IMPLEMENT",
                      "prompt":"예외 처리 코드를 작성하세요.",
                      "answerInstructions":"코드와 이유를 작성하세요.",
                      "coreCriteria":["실패를 예외로 표현한다.","예외를 삼키지 않는다."],
                      "futureExtensions":[],
                      "audit":{"generatorVersion":"e2e","provider":"fixture","model":"fixture","attempts":1,"durationMs":1}
                    }
                    """.formatted(sessionId, ordinal, sessionId, ordinal));
        });
        when(aiClient.gradeAssessmentAnswer(any())).thenAnswer(invocation -> {
            var request = (tools.jackson.databind.JsonNode) invocation.getArgument(0);
            String questionId = request.path("question").path("questionId").stringValue();
            boolean fail = request.path("answer").stringValue("").contains("검토 필요");
            int score = fail ? 50 : 80;
            return objectMapper.readTree("""
                    {
                      "contractVersion":"jobis.ai.v3alpha1",
                      "questionId":"%s",
                      "criterionGrades":[
                        {"criterionIndex":0,"score":%d,"feedback":"기준 확인"},
                        {"criterionIndex":1,"score":%d,"feedback":"기준 확인"}
                      ],
                      "score":%d,
                      "passed":%s,
                      "strengths":[],
                      "gaps":%s,
                      "feedback":"검증 결과",
                      "scopeViolationDetected":false,
                      "audit":{"generatorVersion":"e2e","provider":"fixture","model":"fixture","attempts":1,"durationMs":1}
                    }
                    """.formatted(
                            questionId,
                            score,
                            score,
                            score,
                            !fail,
                            fail ? "[\"핵심 기준 복습 필요\"]" : "[]"
                    ));
        });
        V3AtomicAssessmentService service = new V3AtomicAssessmentService(
                rls,
                aiClient,
                objectMapper,
                new SensitiveTextCipher(new DataProtectionProperties(
                        "local-test-assessment-encryption-key",
                        "local-test-assessment-fingerprint-key"
                ))
        );

        rls.write(userId, jdbc -> {
            jdbc.sql("""
                            insert into users (id, email, display_name)
                            values (:userId, :email, 'Atomic assessment user')
                            """)
                    .param("userId", userId)
                    .param("email", userId + "@example.com")
                    .update();
            insertAtomicCapability(jdbc, userId, "java.exceptions", "ASSESSMENT");
            insertAtomicCapability(jdbc, userId, "git.commit-history", "SELF_CONFIRM");
            return null;
        });
        rls.write(operatorId, jdbc -> {
            jdbc.sql("""
                            insert into users (id, email, display_name, account_role)
                            values (:operatorId, :email, 'Atomic operator', 'OPERATOR')
                            """)
                    .param("operatorId", operatorId)
                    .param("email", operatorId + "@example.com")
                    .update();
            return null;
        });

        var passing = service.start(userId, "java.exceptions", null);
        assertThat(passing.status()).isEqualTo("IN_PROGRESS");
        passing = service.answer(userId, passing.id(), "정상 답변 1");
        passing = service.answer(userId, passing.id(), "정상 답변 2");
        assertThat(passing.status()).isEqualTo("PASSED");
        assertThat(passing.averageScore()).isEqualTo(80);

        var selfConfirmed = service.selfConfirm(userId, "git.commit-history");
        assertThat(selfConfirmed.path("progressState").stringValue()).isEqualTo("VERIFIED");
        assertThatThrownBy(() -> service.selfConfirm(userId, "java.exceptions"))
                .hasMessageContaining("문제 또는 결과물 검증");

        rls.write(userId, jdbc -> {
            jdbc.sql("""
                            update user_atomic_capabilities
                            set progress_state = 'NOT_STARTED', verified_at = null
                            where canonical_key = 'java.exceptions'
                            """).update();
            return null;
        });
        var failing = service.start(userId, "java.exceptions", null);
        failing = service.answer(userId, failing.id(), "검토 필요 1");
        failing = service.answer(userId, failing.id(), "검토 필요 2");
        assertThat(failing.status()).isEqualTo("NEEDS_STUDY");

        failing = service.requestReview(userId, failing.id(), "원자 범위 채점을 확인해 주세요.");
        assertThat(failing.status()).isEqualTo("REVIEW_REQUESTED");
        assertThat(service.operatorReviews(operatorId, "PENDING"))
                .extracting(V3AtomicAssessmentService.AssessmentReviewView::sessionId)
                .contains(failing.id());

        service.resolveReview(operatorId, failing.id(), true, "범위 내 답변으로 확인했습니다.");
        assertThat(service.latest(userId, "java.exceptions").status()).isEqualTo("PASSED");
        rls.read(userId, jdbc -> {
            assertThat(jdbc.sql("""
                            select progress_state
                            from user_atomic_capabilities
                            where canonical_key = 'java.exceptions'
                            """)
                    .query(String.class)
                    .single()).isEqualTo("VERIFIED");
            assertThat(jdbc.sql("""
                            select count(*)
                            from user_atomic_capability_events
                            where event_type in ('ASSESSMENT', 'OPERATOR_REVIEW', 'USER_CLAIM')
                            """)
                    .query(Integer.class)
                    .single()).isEqualTo(3);
            return null;
        });
    }

    @Test
    void v3ContractIdsAreScopedPerUserAndRowsRemainPrivate() throws Exception {
        UUID alice = UUID.randomUUID();
        UUID bob = UUID.randomUUID();
        String sharedContractId = "source-contract-shared";

        try (Connection connection = DriverManager.getConnection(
                postgres.getJdbcUrl(),
                APP_USER,
                APP_PASSWORD
        ); Statement statement = connection.createStatement()) {
            connection.setAutoCommit(false);

            setUser(statement, alice);
            statement.executeUpdate("""
                    insert into users (id, email, display_name)
                    values ('%s', '%s@example.com', 'Alice v3')
                    """.formatted(alice, alice));
            insertV3Source(statement, alice, sharedContractId, "Alice document");
            connection.commit();

            setUser(statement, bob);
            statement.executeUpdate("""
                    insert into users (id, email, display_name)
                    values ('%s', '%s@example.com', 'Bob v3')
                    """.formatted(bob, bob));
            insertV3Source(statement, bob, sharedContractId, "Bob document");
            connection.commit();

            setUser(statement, alice);
            try (ResultSet result = statement.executeQuery("""
                    select count(*), min(document ->> 'owner')
                    from ai_v3_source_documents
                    where source_document_id = 'source-contract-shared'
                    """)) {
                result.next();
                assertThat(result.getInt(1)).isEqualTo(1);
                assertThat(result.getString(2)).isEqualTo("Alice document");
            }
            connection.rollback();

            setUser(statement, bob);
            try (ResultSet result = statement.executeQuery("""
                    select count(*), min(document ->> 'owner')
                    from ai_v3_source_documents
                    where source_document_id = 'source-contract-shared'
                    """)) {
                result.next();
                assertThat(result.getInt(1)).isEqualTo(1);
                assertThat(result.getString(2)).isEqualTo("Bob document");
            }
            connection.rollback();
        }
    }

    @Test
    void autoAgentModeCanQueueAChatReplyJob() throws Exception {
        UUID userId = UUID.randomUUID();

        try (Connection connection = DriverManager.getConnection(
                postgres.getJdbcUrl(),
                APP_USER,
                APP_PASSWORD
        ); Statement statement = connection.createStatement()) {
            connection.setAutoCommit(false);
            setUser(statement, userId);
            statement.executeUpdate("""
                    insert into users (id, email, display_name)
                    values ('%s', '%s@example.com', 'AUTO mode tester')
                    """.formatted(userId, userId));

            UUID conversationId;
            try (ResultSet result = statement.executeQuery("""
                    insert into conversations (user_id)
                    values ('%s')
                    returning id
                    """.formatted(userId))) {
                result.next();
                conversationId = result.getObject(1, UUID.class);
            }

            UUID messageId;
            try (ResultSet result = statement.executeQuery("""
                    insert into conversation_messages (
                        user_id,
                        conversation_id,
                        role,
                        kind,
                        content
                    )
                    values ('%s', '%s', 'USER', 'TEXT', '백엔드 진로를 알려주세요.')
                    returning id
                    """.formatted(userId, conversationId))) {
                result.next();
                messageId = result.getObject(1, UUID.class);
            }

            int inserted = statement.executeUpdate("""
                    insert into chat_reply_jobs (
                        user_id,
                        conversation_id,
                        trigger_message_id,
                        request_context
                    )
                    values (
                        '%s',
                        '%s',
                        '%s',
                        '{"mode":"AUTO","postingIds":[],"careerSourceIds":[]}'::jsonb
                    )
                    """.formatted(userId, conversationId, messageId));

            assertThat(inserted).isEqualTo(1);
            connection.rollback();
        }
    }

    @Test
    void competencyCatalogIsSharedWhileAssessmentSessionsRemainPrivate()
            throws Exception {
        UUID alice = UUID.randomUUID();
        UUID bob = UUID.randomUUID();

        try (Connection connection = DriverManager.getConnection(
                postgres.getJdbcUrl(),
                APP_USER,
                APP_PASSWORD
        ); Statement statement = connection.createStatement()) {
            connection.setAutoCommit(false);
            setUser(statement, alice);
            statement.executeUpdate("""
                    insert into users (id, email, display_name)
                    values ('%s', '%s@example.com', 'Alice')
                    """.formatted(alice, alice));

            UUID catalogId;
            try (ResultSet result = statement.executeQuery("""
                    select upsert_competency_catalog(
                        'messaging.kafka',
                        'Kafka',
                        'BACKEND',
                        '이벤트를 발행하고 중복 소비와 재시도를 처리하는 범위'
                    )
                    """)) {
                result.next();
                catalogId = result.getObject(1, UUID.class);
            }

            UUID competencyId;
            try (ResultSet result = statement.executeQuery("""
                    insert into user_competencies (
                        user_id,
                        catalog_competency_id,
                        canonical_key,
                        title,
                        competency_kind,
                        domain,
                        default_stage,
                        scope_definition
                    )
                    values (
                        '%s',
                        '%s',
                        'messaging.kafka',
                        'Kafka',
                        'TECHNOLOGY',
                        'BACKEND',
                        'SCALE',
                        '이벤트를 발행하고 중복 소비와 재시도를 처리하는 범위'
                    )
                    returning id
                    """.formatted(alice, catalogId))) {
                result.next();
                competencyId = result.getObject(1, UUID.class);
            }

            statement.executeUpdate("""
                    insert into competency_assessment_sessions (
                        user_id,
                        competency_id,
                        required_level,
                        status
                    )
                    values ('%s', '%s', 2, 'IN_PROGRESS')
                    """.formatted(alice, competencyId));
            connection.commit();

            setUser(statement, bob);
            statement.executeUpdate("""
                    insert into users (id, email, display_name)
                    values ('%s', '%s@example.com', 'Bob')
                    """.formatted(bob, bob));
            try (ResultSet result = statement.executeQuery(
                    "select count(*) from competency_assessment_sessions"
            )) {
                result.next();
                assertThat(result.getInt(1)).isZero();
            }
            try (ResultSet result = statement.executeQuery("""
                    select count(*)
                    from competency_catalog
                    where canonical_key = 'messaging.kafka'
                    """)) {
                result.next();
                assertThat(result.getInt(1)).isEqualTo(1);
            }
            connection.rollback();
        }
    }

    @Test
    void careerRepositoryRowsAreIsolatedByRls() throws Exception {
        UUID alice = UUID.randomUUID();
        UUID bob = UUID.randomUUID();

        try (Connection connection = DriverManager.getConnection(
                postgres.getJdbcUrl(),
                APP_USER,
                APP_PASSWORD
        ); Statement statement = connection.createStatement()) {
            connection.setAutoCommit(false);

            setUser(statement, alice);
            statement.executeUpdate("""
                    insert into users (id, email, display_name)
                    values ('%s', '%s@example.com', 'Alice')
                    """.formatted(alice, alice));
            statement.executeUpdate("""
                    insert into career_sources (
                        user_id, source_type, title, raw_text
                    )
                    values (
                        '%s', 'TEXT', 'Alice project',
                        'Spring Boot로 게시판 API를 개발한 프로젝트 경험입니다.'
                    )
                    """.formatted(alice));
            connection.commit();

            setUser(statement, bob);
            statement.executeUpdate("""
                    insert into users (id, email, display_name)
                    values ('%s', '%s@example.com', 'Bob')
                    """.formatted(bob, bob));
            try (ResultSet result = statement.executeQuery(
                    "select count(*) from career_sources"
            )) {
                result.next();
                assertThat(result.getInt(1)).isZero();
            }
            connection.rollback();

            setUser(statement, alice);
            try (ResultSet result = statement.executeQuery(
                    "select count(*) from career_sources"
            )) {
                result.next();
                assertThat(result.getInt(1)).isEqualTo(1);
            }
            connection.rollback();
        }
    }

    @Test
    void textPostingQueuesAnalysisAndRollsBackUsageWhenCreationFails() {
        UUID userId = UUID.randomUUID();
        DriverManagerDataSource dataSource = new DriverManagerDataSource(
                postgres.getJdbcUrl(),
                APP_USER,
                APP_PASSWORD
        );
        RlsTransactionExecutor rls = new RlsTransactionExecutor(
                JdbcClient.create(dataSource),
                new org.springframework.transaction.support.TransactionTemplate(
                        new DataSourceTransactionManager(dataSource)
                )
        );
        AiUsageLimitService usageLimit = new AiUsageLimitService(rls);
        JobPostingService service = new JobPostingService(
                rls,
                usageLimit,
                new SensitiveTextCipher(new DataProtectionProperties(
                        "local-test-sensitive-encryption-key",
                        "local-test-sensitive-fingerprint-key"
                ))
        );

        rls.write(userId, jdbc -> {
            jdbc.sql("""
                            insert into users (id, email, display_name)
                            values (:userId, :email, 'Posting test user')
                            """)
                    .param("userId", userId)
                    .param("email", userId + "@example.com")
                    .update();
            return null;
        });

        JobPostingService.CreatedPosting created = service.create(
                userId,
                new JobPostingService.CreatePosting(
                        "TEXT",
                        null,
                        "Java Spring backend engineer posting",
                        null
                )
        );

        assertThat(created.status()).isEqualTo("QUEUED");
        assertThat(analysisUsageCount(rls, userId)).isEqualTo(1);

        JobPostingService.CreatedPosting duplicate = service.create(
                userId,
                new JobPostingService.CreatePosting(
                        "TEXT",
                        null,
                        "Java Spring backend engineer posting",
                        null
                )
        );
        assertThat(duplicate.postingId()).isEqualTo(created.postingId());
        assertThat(duplicate.analysisJobId()).isEqualTo(created.analysisJobId());
        assertThat(duplicate.reusedAnalysis()).isTrue();
        assertThat(analysisUsageCount(rls, userId)).isEqualTo(1);

        assertThatThrownBy(() -> service.create(
                userId,
                new JobPostingService.CreatePosting(
                        "INVALID",
                        null,
                        "Invalid posting source type",
                        null
                )
        )).isInstanceOf(RuntimeException.class);
        assertThat(analysisUsageCount(rls, userId)).isEqualTo(1);
    }

    @Test
    void aSecondPostingCreatesANewDraftWithoutDuplicatingFoundations() throws Exception {
        UUID userId = UUID.randomUUID();
        UUID graphId = UUID.randomUUID();
        UUID competencyId = UUID.randomUUID();
        UUID mixedRelationCompetencyId = UUID.randomUUID();
        UUID experienceCompetencyId = UUID.randomUUID();
        UUID firstPostingId = UUID.randomUUID();
        UUID secondPostingId = UUID.randomUUID();
        UUID firstJobId = UUID.randomUUID();
        UUID secondJobId = UUID.randomUUID();

        try (Connection connection = DriverManager.getConnection(
                postgres.getJdbcUrl(),
                postgres.getUsername(),
                postgres.getPassword()
        ); Statement statement = connection.createStatement()) {
            statement.executeUpdate("""
                    insert into users (id, email, display_name)
                    values ('%s', '%s@example.com', 'Roadmap tester')
                    """.formatted(userId, userId));
            statement.executeUpdate("""
                    insert into career_graphs (id, user_id)
                    values ('%s', '%s')
                    """.formatted(graphId, userId));
            statement.executeUpdate("""
                    insert into user_competencies (
                        user_id,
                        catalog_competency_id,
                        canonical_key,
                        title,
                        competency_kind,
                        domain,
                        default_stage,
                        scope_definition,
                        roadmap_eligible,
                        verification_method
                    )
                    select
                        '%s',
                        id,
                        canonical_key,
                        title,
                        'KNOWLEDGE',
                        domain,
                        'FOUNDATION',
                        scope_definition,
                        true,
                        '사용자가 기초 퀘스트 완료를 직접 확인'
                    from competency_catalog
                    where canonical_key in (
                        'foundation.programming',
                        'foundation.git-terminal',
                        'foundation.cs'
                    )
                    """.formatted(userId));
            statement.executeUpdate("""
                    insert into career_nodes (
                        user_id,
                        graph_id,
                        competency_id,
                        kind,
                        canonical_key,
                        title,
                        domain,
                        scope_definition,
                        detail,
                        rank
                    )
                    select
                        '%s',
                        '%s',
                        id,
                        'FOUNDATION',
                        canonical_key,
                        title,
                        domain,
                        scope_definition,
                        jsonb_build_object('selfConfirmable', true),
                        case canonical_key
                            when 'foundation.programming' then 0
                            when 'foundation.git-terminal' then 1
                            else 2
                        end
                    from competency_catalog
                    where canonical_key in (
                        'foundation.programming',
                        'foundation.git-terminal',
                        'foundation.cs'
                    )
                    """.formatted(userId, graphId));
            statement.executeUpdate("""
                    insert into node_progress (user_id, node_id)
                    select '%s', id
                    from career_nodes
                    where graph_id = '%s'
                    """.formatted(userId, graphId));
            statement.executeUpdate("""
                    insert into user_competencies (
                        id,
                        user_id,
                        canonical_key,
                        title,
                        competency_kind,
                        domain,
                        default_stage,
                        scope_definition,
                        roadmap_eligible,
                        verification_method
                    )
                    values (
                        '%s',
                        '%s',
                        'language.java',
                        'Java',
                        'TECHNOLOGY',
                        'BACKEND',
                        'LANGUAGE',
                        'Java로 서버 로직을 구현하는 범위',
                        true,
                        '실행 가능한 Java 코드와 테스트로 확인'
                    )
                    """.formatted(competencyId, userId));
            insertPostingAnalysis(
                    statement,
                    userId,
                    firstPostingId,
                    firstJobId,
                    competencyId,
                    "First company"
            );
            statement.executeUpdate("""
                    update job_postings
                    set lifecycle_status = 'CLOSED',
                        closes_at = now() - interval '1 day'
                    where id = '%s'
                    """.formatted(firstPostingId));
            insertPostingAnalysis(
                    statement,
                    userId,
                    secondPostingId,
                    secondJobId,
                    competencyId,
                    "Second company"
            );
            statement.executeUpdate("""
                    insert into posting_path_profiles (
                        posting_id,
                        user_id,
                        analysis_job_id,
                        primary_track,
                        experience_requirement_type,
                        minimum_experience_months,
                        maximum_experience_months,
                        experience_source_text
                    )
                    values
                        (
                            '%s', '%s', '%s', 'BACKEND',
                            'NONE', 0, null, '신입'
                        ),
                        (
                            '%s', '%s', '%s', 'BACKEND',
                            'REQUIRED', 24, null, '백엔드 경력 2년 이상'
                        )
                    """.formatted(
                    firstPostingId,
                    userId,
                    firstJobId,
                    secondPostingId,
                    userId,
                    secondJobId
            ));
            statement.executeUpdate("""
                    insert into user_competencies (
                        id,
                        user_id,
                        canonical_key,
                        title,
                        competency_kind,
                        domain,
                        default_stage,
                        scope_definition,
                        roadmap_eligible,
                        verification_method
                    )
                    values (
                        '%s',
                        '%s',
                        'experience.backend-2y',
                        '백엔드 실무 경력 2년',
                        'EXPERIENCE',
                        'CAREER',
                        'EXPERIENCE',
                        '백엔드 직무에서 24개월 이상 근무한 범위',
                        true,
                        '경력 자료와 재직 기간으로 확인'
                    )
                    """.formatted(experienceCompetencyId, userId));
            statement.executeUpdate("""
                    insert into user_competencies (
                        id,
                        user_id,
                        canonical_key,
                        title,
                        competency_kind,
                        domain,
                        default_stage,
                        scope_definition,
                        roadmap_eligible,
                        verification_method
                    )
                    values (
                        '%s',
                        '%s',
                        'messaging.redis',
                        'Redis',
                        'TECHNOLOGY',
                        'DEVOPS',
                        'SCALE',
                        'Redis를 이용해 캐시를 구현하는 범위',
                        true,
                        '실행 가능한 코드와 테스트로 확인'
                    )
                    """.formatted(mixedRelationCompetencyId, userId));
            statement.executeUpdate("""
                    insert into posting_competency_requirements (
                        user_id,
                        posting_id,
                        analysis_job_id,
                        competency_id,
                        relation_kind,
                        required_scope,
                        required_level,
                        source_text,
                        confidence,
                        competency_title,
                        competency_kind,
                        roadmap_domain,
                        roadmap_stage,
                        roadmap_eligible,
                        verification_method
                    )
                    values
                        (
                            '%s', '%s', '%s', '%s', 'PREFERRED',
                            'Redis를 이용해 캐시를 구현하는 범위',
                            2, 'Redis 경험 우대', 0.95, 'Redis',
                            'TECHNOLOGY', 'DEVOPS', 'SCALE', true,
                            '실행 가능한 코드와 테스트로 확인'
                        ),
                        (
                            '%s', '%s', '%s', '%s', 'REQUIRED',
                            'Redis를 이용해 캐시를 구현하는 범위',
                            2, 'Redis 경험 필수', 0.95, 'Redis',
                            'TECHNOLOGY', 'DEVOPS', 'SCALE', true,
                            '실행 가능한 코드와 테스트로 확인'
                        )
                    """.formatted(
                    userId,
                    firstPostingId,
                    firstJobId,
                    mixedRelationCompetencyId,
                    userId,
                    secondPostingId,
                    secondJobId,
                    mixedRelationCompetencyId
            ));
            statement.executeUpdate("""
                    insert into posting_competency_requirements (
                        user_id,
                        posting_id,
                        analysis_job_id,
                        competency_id,
                        relation_kind,
                        required_scope,
                        required_level,
                        source_text,
                        confidence,
                        competency_title,
                        competency_kind,
                        roadmap_domain,
                        roadmap_stage,
                        roadmap_eligible,
                        verification_method
                    )
                    values (
                        '%s',
                        '%s',
                        '%s',
                        '%s',
                        'REQUIRED',
                        '백엔드 직무에서 24개월 이상 근무한 범위',
                        2,
                        '백엔드 경력 2년 이상',
                        0.99,
                        '백엔드 실무 경력 2년',
                        'EXPERIENCE',
                        'CAREER',
                        'EXPERIENCE',
                        true,
                        '경력 자료와 재직 기간으로 확인'
                    )
                    """.formatted(
                    userId,
                    secondPostingId,
                    secondJobId,
                    experienceCompetencyId
            ));
        }

        DriverManagerDataSource dataSource = new DriverManagerDataSource(
                postgres.getJdbcUrl(),
                APP_USER,
                APP_PASSWORD
        );
        RoadmapService service = new RoadmapService(
                new RlsTransactionExecutor(
                        JdbcClient.create(dataSource),
                        new org.springframework.transaction.support.TransactionTemplate(
                                new DataSourceTransactionManager(dataSource)
                        )
                ),
                new ObjectMapper()
        );

        RoadmapService.DraftResult firstDraft = service.addTarget(userId, firstJobId);
        service.applyDraft(
                userId,
                firstDraft.draftId(),
                firstDraft.draftVersion()
        );
        RoadmapService.DraftResult secondDraft = service.addTarget(userId, secondJobId);

        assertThat(secondDraft.draftVersion())
                .isGreaterThan(firstDraft.draftVersion());
        RoadmapService.Workspace workspace = service.get(userId);
        assertThat(workspace.targetCount()).isEqualTo(2);
        assertThat(workspace.draft()).isNotNull();
        assertThat(workspace.draft().snapshot().targets())
                .anySatisfy(target -> {
                    assertThat(target.postingId()).isEqualTo(firstPostingId);
                    assertThat(target.goalMode()).isEqualTo("REOPENING_PREPARATION");
                    assertThat(target.lifecycleStatus()).isEqualTo("CLOSED");
                });
        List<RoadmapService.RoadmapNode> draftNodes =
                workspace.draft().snapshot().nodes();
        RoadmapService.RoadmapNode firstOpportunity = draftNodes.stream()
                .filter(node -> node.id().equals("opportunity:" + firstPostingId))
                .findFirst()
                .orElseThrow();
        RoadmapService.RoadmapNode employment = draftNodes.stream()
                .filter(node -> "EMPLOYMENT".equals(node.stage()))
                .findFirst()
                .orElseThrow();
        RoadmapService.RoadmapNode experience = draftNodes.stream()
                .filter(node -> node.id().endsWith(":experience:24"))
                .findFirst()
                .orElseThrow();
        RoadmapService.RoadmapNode secondOpportunity = draftNodes.stream()
                .filter(node -> node.id().equals("opportunity:" + secondPostingId))
                .findFirst()
                .orElseThrow();
        RoadmapService.RoadmapNode redis = draftNodes.stream()
                .filter(node -> node.competencies().stream()
                        .anyMatch(item -> "messaging.redis".equals(
                                item.canonicalKey()
                        )))
                .findFirst()
                .orElseThrow();
        assertThat(firstOpportunity.rank()).isLessThan(employment.rank());
        assertThat(employment.rank()).isLessThan(experience.rank());
        assertThat(experience.rank()).isLessThan(redis.rank());
        assertThat(experience.rank()).isLessThan(secondOpportunity.rank());
        assertThat(redis.requirementKinds())
                .containsEntry(firstPostingId, "PREFERRED")
                .containsEntry(secondPostingId, "REQUIRED");
        assertThat(draftNodes.stream()
                .filter(node -> node.competencies().stream()
                        .anyMatch(item -> "messaging.redis".equals(
                                item.canonicalKey()
                        )))
                .count()).isEqualTo(1);
        assertThat(draftNodes)
                .filteredOn(node -> !"COMMON".equals(node.domain()))
                .allMatch(node -> "BACKEND".equals(node.domain()));

        assertThatThrownBy(() -> service.applyDraft(
                userId,
                UUID.randomUUID(),
                secondDraft.draftVersion()
        )).hasMessageContaining("최신 초안");

        service.applyDraft(
                userId,
                secondDraft.draftId(),
                secondDraft.draftVersion()
        );
        RoadmapService.DraftResult resetDraft = service.resetTargets(userId);
        RoadmapService.Workspace resetWorkspace = service.get(userId);
        assertThat(resetWorkspace.targetCount()).isZero();
        assertThat(resetWorkspace.draft().snapshot().targets()).isEmpty();
        assertThat(resetWorkspace.draft().snapshot().nodes())
                .isNotEmpty()
                .allMatch(node -> "COMMON".equals(node.domain()));
        service.applyDraft(
                userId,
                resetDraft.draftId(),
                resetDraft.draftVersion()
        );
        assertThat(service.get(userId).current().targets()).isEmpty();

        long publishedVersion = service.get(userId).current().version();
        RoadmapService.DraftResult disposableDraft = service.regenerate(userId);
        service.discardDraft(
                userId,
                disposableDraft.draftId(),
                disposableDraft.draftVersion()
        );
        RoadmapService.Workspace afterDiscard = service.get(userId);
        assertThat(afterDiscard.draft()).isNull();
        assertThat(afterDiscard.current().version()).isEqualTo(publishedVersion);

        try (Connection connection = DriverManager.getConnection(
                postgres.getJdbcUrl(),
                APP_USER,
                APP_PASSWORD
        ); Statement statement = connection.createStatement()) {
            connection.setAutoCommit(false);
            setUser(statement, userId);
            try (ResultSet result = statement.executeQuery("""
                    select count(*)
                    from (
                        select canonical_key
                        from career_nodes
                        where kind = 'FOUNDATION'
                          and archived_at is null
                        group by canonical_key
                        having count(*) > 1
                    ) duplicates
                    """)) {
                result.next();
                assertThat(result.getInt(1)).isZero();
            }
            connection.rollback();
        }
    }

    @Test
    void clarificationQuestionsEnforceTheirDeclaredInputType() throws Exception {
        UUID userId = UUID.randomUUID();
        UUID postingId = UUID.randomUUID();
        UUID jobId = UUID.randomUUID();

        try (Connection connection = DriverManager.getConnection(
                postgres.getJdbcUrl(),
                APP_USER,
                APP_PASSWORD
        ); Statement statement = connection.createStatement()) {
            connection.setAutoCommit(false);
            setUser(statement, userId);
            statement.executeUpdate("""
                    insert into users (id, email, display_name)
                    values ('%s', '%s@example.com', 'Question Test')
                    """.formatted(userId, userId));
            statement.executeUpdate("""
                    insert into job_postings (id, user_id, source_type, raw_text)
                    values ('%s', '%s', 'TEXT', 'Backend posting')
                    """.formatted(postingId, userId));
            statement.executeUpdate("""
                    insert into analysis_jobs (
                        id, user_id, posting_id, status, stage, stage_message
                    )
                    values (
                        '%s', '%s', '%s', 'RUNNING', 'CLARIFICATION', '기준 확인'
                    )
                    """.formatted(jobId, userId, postingId));

            int inserted = statement.executeUpdate("""
                    insert into analysis_questions (
                        user_id, analysis_job_id, question_key, question_text,
                        reason, input_type, options, ordinal
                    )
                    values (
                        '%s', '%s', 'project_evidence', '프로젝트 경험을 알려주세요.',
                        '경험 범위를 확인합니다.', 'TEXT', '[]', 1
                    )
                    """.formatted(userId, jobId));
            assertThat(inserted).isEqualTo(1);

            int confirmedAbsence = statement.executeUpdate("""
                    insert into analysis_questions (
                        user_id, analysis_job_id, question_key, question_text,
                        reason, input_type, options, related_requirement_ids,
                        absence_scope, status, answer_value, answer_status, ordinal
                    )
                    values (
                        '%s', '%s', 'database_evidence', 'DB 경험이 있나요?',
                        '요구조건을 확인합니다.', 'TEXT', '[]', '["req-db"]',
                        'REQUIREMENTS', 'ANSWERED', '없습니다.',
                        'CONFIRMED_ABSENT', 2
                    )
                    """.formatted(userId, jobId));
            assertThat(confirmedAbsence).isEqualTo(1);

            assertThatThrownBy(() -> statement.executeUpdate("""
                    insert into analysis_questions (
                        user_id, analysis_job_id, question_key, question_text,
                        reason, input_type, options, absence_scope,
                        status, answer_value, answer_status, ordinal
                    )
                    values (
                        '%s', '%s', 'invalid_absence', '경험이 있나요?',
                        '확인합니다.', 'TEXT', '[]', 'NONE',
                        'ANSWERED', '없습니다.', 'CONFIRMED_ABSENT', 3
                    )
                    """.formatted(userId, jobId)))
                    .hasMessageContaining("analysis_question_confirmed_absence_scope_check");

            assertThatThrownBy(() -> statement.executeUpdate("""
                    insert into analysis_questions (
                        user_id, analysis_job_id, question_key, question_text,
                        reason, input_type, options, ordinal
                    )
                    values (
                        '%s', '%s', 'invalid_choice', '직무를 선택해 주세요.',
                        '지원 직무를 확인합니다.', 'CHOICE', '[]', 4
                    )
                    """.formatted(userId, jobId)))
                    .hasMessageContaining("analysis_question_options_check");
            connection.rollback();
        }
    }

    @Test
    void cancellingAnAnalysisClearsItsQueueAndAllowsRetry() throws Exception {
        UUID userId = UUID.randomUUID();
        UUID postingId = UUID.randomUUID();
        UUID jobId = UUID.randomUUID();
        DriverManagerDataSource dataSource = new DriverManagerDataSource(
                postgres.getJdbcUrl(),
                APP_USER,
                APP_PASSWORD
        );
        RlsTransactionExecutor rls = new RlsTransactionExecutor(
                JdbcClient.create(dataSource),
                new org.springframework.transaction.support.TransactionTemplate(
                        new DataSourceTransactionManager(dataSource)
                )
        );
        AiUsageLimitService usageLimit = new AiUsageLimitService(rls);
        AnalysisJobService service = new AnalysisJobService(
                rls,
                new ObjectMapper(),
                usageLimit,
                new AnalysisTaskRegistry(),
                mock(AiAnalysisClient.class)
        );

        rls.write(userId, jdbc -> {
            jdbc.sql("""
                            insert into users (id, email, display_name)
                            values (:userId, :email, 'Cancellation tester')
                            """)
                    .param("userId", userId)
                    .param("email", userId + "@example.com")
                    .update();
            jdbc.sql("""
                            insert into job_postings (
                                id, user_id, source_type, raw_text
                            )
                            values (
                                :postingId, :userId, 'TEXT',
                                'Java Spring backend cancellation test posting'
                            )
                            """)
                    .param("postingId", postingId)
                    .param("userId", userId)
                    .update();
            jdbc.sql("""
                            insert into analysis_jobs (
                                id, user_id, posting_id, status, stage,
                                stage_message, worker_id, locked_until
                            )
                            values (
                                :jobId, :userId, :postingId, 'RUNNING',
                                'AI_ANALYSIS', '분석 중', 'worker-test',
                                now() + interval '15 minutes'
                            )
                            """)
                    .param("jobId", jobId)
                    .param("userId", userId)
                    .param("postingId", postingId)
                    .update();
            return null;
        });

        service.cancel(userId, jobId);

        rls.read(userId, jdbc -> {
            assertThat(jdbc.sql("""
                            select status::text
                            from analysis_jobs
                            where id = :jobId
                            """)
                    .param("jobId", jobId)
                    .query(String.class)
                    .single()).isEqualTo("CANCELLED");
            assertThat(jdbc.sql("""
                            select count(*)
                            from analysis_job_queue
                            where analysis_job_id = :jobId
                            """)
                    .param("jobId", jobId)
                    .query(Integer.class)
                    .single()).isZero();
            return null;
        });

        service.retry(userId, jobId);
        rls.read(userId, jdbc -> {
            assertThat(jdbc.sql("""
                            select status::text
                            from analysis_jobs
                            where id = :jobId
                            """)
                    .param("jobId", jobId)
                    .query(String.class)
                    .single()).isEqualTo("QUEUED");
            assertThat(jdbc.sql("""
                            select count(*)
                            from analysis_job_queue
                            where analysis_job_id = :jobId
                            """)
                    .param("jobId", jobId)
                    .query(Integer.class)
                    .single()).isEqualTo(1);
            return null;
        });
    }

    @Test
    void cancellingAV3PostingReviewQuestionFinishesWithoutRequeueing() {
        UUID userId = UUID.randomUUID();
        UUID postingId = UUID.randomUUID();
        UUID jobId = UUID.randomUUID();
        UUID questionId = UUID.randomUUID();
        DriverManagerDataSource dataSource = new DriverManagerDataSource(
                postgres.getJdbcUrl(),
                APP_USER,
                APP_PASSWORD
        );
        RlsTransactionExecutor rls = new RlsTransactionExecutor(
                JdbcClient.create(dataSource),
                new org.springframework.transaction.support.TransactionTemplate(
                        new DataSourceTransactionManager(dataSource)
                )
        );
        AnalysisJobService service = new AnalysisJobService(
                rls,
                new ObjectMapper(),
                new AiUsageLimitService(rls),
                new AnalysisTaskRegistry(),
                mock(AiAnalysisClient.class)
        );

        rls.write(userId, jdbc -> {
            jdbc.sql("""
                            insert into users (id, email, display_name)
                            values (:userId, :email, 'Posting review cancellation tester')
                            """)
                    .param("userId", userId)
                    .param("email", userId + "@example.com")
                    .update();
            jdbc.sql("""
                            insert into job_postings (
                                id, user_id, source_type, raw_text
                            )
                            values (
                                :postingId, :userId, 'TEXT',
                                'Java Spring backend posting review test'
                            )
                            """)
                    .param("postingId", postingId)
                    .param("userId", userId)
                    .update();
            jdbc.sql("""
                            insert into analysis_jobs (
                                id, user_id, posting_id, status, stage,
                                stage_message, question_count, analysis_provider
                            )
                            values (
                                :jobId, :userId, :postingId, 'WAITING_FOR_INPUT',
                                'AWAITING_POSTING_CONFIRMATION',
                                '정리한 공고를 확인해 주세요', 1, 'UNIFIED'
                            )
                            """)
                    .param("jobId", jobId)
                    .param("userId", userId)
                    .param("postingId", postingId)
                    .update();
            jdbc.sql("""
                            insert into analysis_questions (
                                id, user_id, analysis_job_id, question_key,
                                question_text, reason, input_type, options, ordinal
                            )
                            values (
                                :questionId, :userId, :jobId,
                                'posting-review-test',
                                '이 내용으로 회사 맞춤 프로젝트와 로드맵을 만들까요?',
                                '선택한 공고 범위를 확인합니다.',
                                'CHOICE',
                                cast(:options as jsonb),
                                1
                            )
                            """)
                    .param("questionId", questionId)
                    .param("userId", userId)
                    .param("jobId", jobId)
                    .param(
                            "options",
                            """
                            [
                              {"value":"CONFIRM","label":"이 내용으로 계속"},
                              {"value":"CANCEL","label":"분석 취소"}
                            ]
                            """
                    )
                    .update();
            return null;
        });

        service.answerQuestion(userId, jobId, questionId, "CANCEL", null);

        rls.read(userId, jdbc -> {
            assertThat(jdbc.sql("""
                            select status::text
                            from analysis_jobs
                            where id = :jobId
                            """)
                    .param("jobId", jobId)
                    .query(String.class)
                    .single()).isEqualTo("CANCELLED");
            assertThat(jdbc.sql("""
                            select answer_value
                            from analysis_questions
                            where id = :questionId
                            """)
                    .param("questionId", questionId)
                    .query(String.class)
                    .single()).isEqualTo("CANCEL");
            assertThat(jdbc.sql("""
                            select count(*)
                            from analysis_job_queue
                            where analysis_job_id = :jobId
                            """)
                    .param("jobId", jobId)
                    .query(Integer.class)
                    .single()).isZero();
            return null;
        });
    }

    private static void insertPostingAnalysis(
            Statement statement,
            UUID userId,
            UUID postingId,
            UUID jobId,
            UUID competencyId,
            String companyName
    ) throws Exception {
        statement.executeUpdate("""
                insert into job_postings (
                    id,
                    user_id,
                    source_type,
                    raw_text,
                    company_name,
                    role_title,
                    parsed_data
                )
                values (
                    '%s',
                    '%s',
                    'TEXT',
                    'Java backend posting',
                    '%s',
                    'Backend developer',
                    '{"domain":"BACKEND"}'
                )
                """.formatted(postingId, userId, companyName));
        statement.executeUpdate("""
                insert into analysis_jobs (
                    id,
                    user_id,
                    posting_id,
                    status,
                    stage,
                    stage_message,
                    result_data,
                    completed_at
                )
                values (
                    '%s',
                    '%s',
                    '%s',
                    'SUCCEEDED',
                    'COMPLETED',
                    '분석 완료',
                    '{}',
                    now()
                )
                """.formatted(jobId, userId, postingId));
        statement.executeUpdate("""
                insert into graph_change_sets (
                    user_id,
                    analysis_job_id,
                    status,
                    proposal
                )
                values ('%s', '%s', 'PROPOSED', '{}')
                """.formatted(userId, jobId));
        statement.executeUpdate("""
                insert into posting_competency_requirements (
                    user_id,
                    posting_id,
                    analysis_job_id,
                    competency_id,
                    relation_kind,
                    required_scope,
                    required_level,
                    source_text,
                    confidence,
                    competency_title,
                    competency_kind,
                    roadmap_domain,
                    roadmap_stage,
                    roadmap_eligible,
                    verification_method
                )
                values (
                    '%s',
                    '%s',
                    '%s',
                    '%s',
                    'REQUIRED',
                    'Java로 서버 로직을 구현하는 범위',
                    2,
                    'Java 개발 경험',
                    0.95,
                    'Java',
                    'TECHNOLOGY',
                    'BACKEND',
                    'LANGUAGE',
                    true,
                    '실행 가능한 Java 코드와 테스트로 확인'
                )
                """.formatted(userId, postingId, jobId, competencyId));
        statement.executeUpdate("""
                insert into posting_target_projects (
                    posting_id,
                    user_id,
                    analysis_job_id,
                    title,
                    objective,
                    domain_context,
                    required_competency_keys,
                    optional_competency_keys,
                    deliverables,
                    acceptance_criteria
                )
                values (
                    '%s',
                    '%s',
                    '%s',
                    '%s backend project',
                    'Java API를 구현합니다.',
                    '백엔드 서비스',
                    '["language.java"]',
                    '[]',
                    '["실행 가능한 저장소"]',
                    '["API가 동작한다"]'
                )
                """.formatted(postingId, userId, jobId, companyName));
    }

    private static int analysisUsageCount(
            RlsTransactionExecutor rls,
            UUID userId
    ) {
        return rls.read(userId, jdbc -> jdbc.sql("""
                        select coalesce(sum(usage_count), 0)
                        from ai_usage_hourly
                        where usage_kind = 'ANALYSIS'
                        """)
                .query(Integer.class)
                .single());
    }

    private static void insertV3Source(
            Statement statement,
            UUID userId,
            String sourceDocumentId,
            String owner
    ) throws Exception {
        statement.executeUpdate("""
                insert into ai_v3_source_documents (
                    user_id,
                    source_document_id,
                    entry_point,
                    input_type,
                    extraction_revision,
                    status,
                    canonical_input_hash,
                    content_hash,
                    document
                )
                values (
                    '%s',
                    '%s',
                    'POSTINGS_PAGE',
                    'TEXT',
                    1,
                    'EXTRACTED',
                    'sha256:canonical',
                    'sha256:content',
                    jsonb_build_object('owner', '%s')
                )
                """.formatted(userId, sourceDocumentId, owner));
    }

    private static void insertAtomicCapability(
            JdbcClient jdbc,
            UUID userId,
            String canonicalKey,
            String completionPolicy
    ) {
        jdbc.sql("""
                        insert into user_atomic_capabilities (
                            user_id,
                            canonical_key,
                            graph_version,
                            graph_node_version,
                            technology_key,
                            title,
                            scope_definition,
                            objective,
                            excluded_scope,
                            verification_methods,
                            completion_policy
                        ) values (
                            :userId,
                            :canonicalKey,
                            '0.1.0-alpha.1',
                            1,
                            :technologyKey,
                            :title,
                            :scope,
                            :objective,
                            '[]',
                            '["IMPLEMENT", "DEBUG"]',
                            :completionPolicy
                        )
                        """)
                .param("userId", userId)
                .param("canonicalKey", canonicalKey)
                .param("technologyKey", canonicalKey.substring(0, canonicalKey.indexOf('.')))
                .param("title", canonicalKey)
                .param("scope", canonicalKey + " 원자 범위")
                .param("objective", canonicalKey + " 목표")
                .param("completionPolicy", completionPolicy)
                .update();
    }

    private static void setUser(Statement statement, UUID userId) throws Exception {
        statement.execute(
                "select set_config('app.current_user_id', '%s', true)".formatted(userId)
        );
    }
}
