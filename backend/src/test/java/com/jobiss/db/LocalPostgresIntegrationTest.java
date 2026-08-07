package com.jobiss.db;

import com.jobiss.common.ApiException;
import com.jobiss.config.JobissProperties;
import com.jobiss.analysis.v3.V3CareerProgressOverlay;
import com.jobiss.analysis.v3.V3ProjectProgressService;
import com.jobiss.analysis.v3.V3ProjectTaskProgressService;
import com.jobiss.security.RefreshTokenService;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@EnabledIfEnvironmentVariable(named = "JOBISS_LOCAL_TEST_DB_URL", matches = ".+")
class LocalPostgresIntegrationTest {

    private static String url;
    private static String migratorPassword;
    private static String appPassword;

    @BeforeAll
    static void migrate() {
        url = System.getenv("JOBISS_LOCAL_TEST_DB_URL");
        migratorPassword = System.getenv("JOBISS_LOCAL_TEST_DB_MIGRATOR_PASSWORD");
        appPassword = System.getenv("JOBISS_LOCAL_TEST_DB_APP_PASSWORD");
        Flyway.configure()
                .dataSource(url, "jobiss_migrator", migratorPassword)
                .locations("classpath:db/migration")
                .load()
                .migrate();
    }

    @Test
    void rotatingRefreshTokenRejectsReuseAndRevokesItsReplacement() throws Exception {
        UUID userId = UUID.randomUUID();
        insertUser(userId, "refresh-local@example.com");
        RefreshTokenService service = refreshTokenService();

        RefreshTokenService.IssuedRefreshToken original = service.issue(userId, false);
        RefreshTokenService.IssuedRefreshToken replacement = service.rotate(original.rawToken());

        assertThatThrownBy(() -> service.rotate(original.rawToken()))
                .isInstanceOfSatisfying(ApiException.class, exception ->
                        assertThat(exception.code()).isEqualTo("REFRESH_TOKEN_REUSE_DETECTED")
                );
        assertThatThrownBy(() -> service.rotate(replacement.rawToken()))
                .isInstanceOfSatisfying(ApiException.class, exception ->
                        assertThat(exception.code()).isEqualTo("REFRESH_TOKEN_REUSE_DETECTED")
                );
    }

    @Test
    void refreshTokensRemainPrivateToTheirRlsOwner() throws Exception {
        UUID alice = UUID.randomUUID();
        UUID bob = UUID.randomUUID();
        insertUser(alice, "refresh-alice@example.com");
        insertUser(bob, "refresh-bob@example.com");
        RefreshTokenService service = refreshTokenService();
        service.issue(alice, false);
        service.issue(bob, false);

        try (Connection connection = DriverManager.getConnection(url, "jobiss_app", appPassword);
             Statement statement = connection.createStatement()) {
            connection.setAutoCommit(false);
            setUser(statement, alice);
            try (ResultSet result = statement.executeQuery("select count(*) from auth_refresh_tokens")) {
                result.next();
                assertThat(result.getInt(1)).isEqualTo(1);
            }
            connection.rollback();
        }
    }

    @Test
    void claimQueueSkipsAUserWhoAlreadyHasTwoRunningAnalyses() throws Exception {
        UUID alice = UUID.randomUUID();
        UUID bob = UUID.randomUUID();
        try (Connection connection = DriverManager.getConnection(url, "jobiss_migrator", migratorPassword);
             Statement statement = connection.createStatement()) {
            UUID alicePosting = insertPosting(statement, alice, "queue-alice@example.com");
            UUID bobPosting = insertPosting(statement, bob, "queue-bob@example.com");
            insertJob(statement, alice, alicePosting, "RUNNING", "-5 minutes");
            insertJob(statement, alice, alicePosting, "RUNNING", "-4 minutes");
            insertJob(statement, alice, alicePosting, "QUEUED", "-3 minutes");
            UUID bobQueued = insertJob(statement, bob, bobPosting, "QUEUED", "-2 minutes");

            try (ResultSet result = statement.executeQuery(
                    "select id, user_id from claim_analysis_job('local-test-worker')"
            )) {
                assertThat(result.next()).isTrue();
                assertThat(result.getObject("id", UUID.class)).isEqualTo(bobQueued);
                assertThat(result.getObject("user_id", UUID.class)).isEqualTo(bob);
            }
        }
    }

    @Test
    void accountDeletionImmediatelyWithdrawsThenPurgesFromQueue() throws Exception {
        UUID userId = UUID.randomUUID();
        try (Connection connection = DriverManager.getConnection(url, "jobiss_migrator", migratorPassword);
             Statement statement = connection.createStatement()) {
            statement.executeUpdate("""
                    insert into users (id, email, display_name)
                    values ('%s', 'delete-local@example.com', 'Delete user');
                    insert into auth_identities (user_id, email, password_hash)
                    values ('%s', 'delete-local@example.com', 'irreversible-test-hash');
                    """.formatted(userId, userId));
        }
        try (Connection connection = DriverManager.getConnection(url, "jobiss_app", appPassword);
             Statement statement = connection.createStatement()) {
            connection.setAutoCommit(false);
            setUser(statement, userId);
            statement.execute("select delete_current_account('%s')".formatted(userId));
            connection.commit();
        }
        try (Connection connection = DriverManager.getConnection(url, "jobiss_migrator", migratorPassword);
             Statement statement = connection.createStatement()) {
            try (ResultSet result = statement.executeQuery("select status::text from users where id = '%s'".formatted(userId))) {
                assertThat(result.next()).isTrue();
                assertThat(result.getString(1)).isEqualTo("WITHDRAWN");
            }
            statement.executeUpdate("update account_deletion_requests set purge_after = now() - interval '1 second' where user_id = '%s'".formatted(userId));
        }
        try (Connection connection = DriverManager.getConnection(url, "jobiss_app", appPassword);
             Statement statement = connection.createStatement()) {
            statement.execute("select purge_due_withdrawn_accounts(25)");
        }
        try (Connection connection = DriverManager.getConnection(url, "jobiss_migrator", migratorPassword);
             Statement statement = connection.createStatement();
             ResultSet result = statement.executeQuery("select exists(select 1 from users where id = '%s')".formatted(userId))) {
            result.next();
            assertThat(result.getBoolean(1)).isFalse();
        }
    }

    @Test
    void operatorCanVerifyAnotherUsersEmploymentEvidenceThroughRls() throws Exception {
        UUID subjectId = UUID.randomUUID();
        UUID operatorId = UUID.randomUUID();
        UUID employmentId = UUID.randomUUID();
        try (Connection connection = DriverManager.getConnection(url, "jobiss_migrator", migratorPassword);
             Statement statement = connection.createStatement()) {
            statement.executeUpdate("""
                    insert into users (id, email, display_name)
                    values ('%s', 'employment-subject@example.com', 'Employment subject'),
                           ('%s', 'employment-operator@example.com', 'Employment operator');
                    update users set account_role = 'OPERATOR' where id = '%s';
                    """.formatted(subjectId, operatorId, operatorId));
        }
        try (Connection connection = DriverManager.getConnection(url, "jobiss_app", appPassword);
             Statement statement = connection.createStatement()) {
            connection.setAutoCommit(false);
            setUser(statement, subjectId);
            statement.executeUpdate("""
                    insert into user_employment_records (
                        id, user_id, canonical_role_id, role_family, role_specialization,
                        employer, role_title, started_on, ended_on, evidence_url, description
                    ) values (
                        '%s', '%s', 'software.backend', 'SOFTWARE_ENGINEERING', 'BACKEND',
                        'Example', 'Backend developer', '2024-01-01', '2025-12-31',
                        'https://example.invalid/evidence', 'Verified employment test'
                    )
                    """.formatted(employmentId, subjectId));
            connection.commit();
        }
        ObjectMapper objectMapper = new ObjectMapper();
        JsonNode snapshot = objectMapper.readTree("""
                {"roadmapVersion":1,"nodes":[{
                  "nodeId":"experience-backend-24m","nodeKind":"EXPERIENCE_INTERVAL",
                  "progressState":"NOT_STARTED","experienceIntervalSpec":{
                    "canonicalRoleId":"software.backend","roleFamily":"SOFTWARE_ENGINEERING",
                    "roleSpecialization":"BACKEND","minimumMonths":24,"maximumMonths":48
                  }
                }],"relations":[]}
                """);
        V3CareerProgressOverlay overlay = new V3CareerProgressOverlay();
        JsonNode evidenced = rlsExecutor().read(
                subjectId,
                jdbc -> overlay.overlay(jdbc, snapshot)
        );
        assertThat(evidenced.path("nodes").get(0).path("progressState").stringValue())
                .isEqualTo("EVIDENCED");
        assertThat(evidenced.path("nodes").get(0).path("experienceIntervalSpec")
                .path("evidenceMinimumSatisfied").booleanValue()).isTrue();
        assertThat(evidenced.path("nodes").get(0).path("experienceIntervalSpec")
                .path("minimumSatisfied").booleanValue()).isFalse();
        try (Connection connection = DriverManager.getConnection(url, "jobiss_app", appPassword);
             Statement statement = connection.createStatement()) {
            connection.setAutoCommit(false);
            setUser(statement, operatorId);
            assertThat(statement.executeUpdate("""
                    update user_employment_records
                    set evidence_state = 'VERIFIED', operator_user_id = '%s', reviewed_at = now()
                    where id = '%s'
                    """.formatted(operatorId, employmentId))).isEqualTo(1);
            connection.commit();
        }
        JsonNode verified = rlsExecutor().read(
                subjectId,
                jdbc -> overlay.overlay(jdbc, snapshot)
        );
        assertThat(verified.path("nodes").get(0).path("progressState").stringValue())
                .isEqualTo("VERIFIED");
        assertThat(verified.path("nodes").get(0).path("experienceIntervalSpec")
                .path("minimumSatisfied").booleanValue()).isTrue();
        try (Connection connection = DriverManager.getConnection(url, "jobiss_migrator", migratorPassword);
             Statement statement = connection.createStatement();
             ResultSet result = statement.executeQuery("""
                     select evidence_state, operator_user_id
                     from user_employment_records where id = '%s'
                     """.formatted(employmentId))) {
            assertThat(result.next()).isTrue();
            assertThat(result.getString("evidence_state")).isEqualTo("VERIFIED");
            assertThat(result.getObject("operator_user_id", UUID.class)).isEqualTo(operatorId);
        }
    }

    @Test
    void analysisProviderConstraintUsesUnifiedRuntimeValue() throws Exception {
        try (Connection connection = DriverManager.getConnection(url, "jobiss_migrator", migratorPassword);
             Statement statement = connection.createStatement();
             ResultSet result = statement.executeQuery("""
                     select pg_get_constraintdef(oid)
                     from pg_constraint
                     where conrelid = 'analysis_jobs'::regclass
                       and conname = 'analysis_jobs_provider_check'
                     """)) {
            assertThat(result.next()).isTrue();
            String definition = result.getString(1);
            assertThat(definition).contains("UNIFIED");
            assertThat(definition).doesNotContain("'V3'");
        }
    }

    @Test
    void projectTasksAreSynchronizedAndRemainPrivateToTheirRlsOwner() throws Exception {
        UUID ownerId = UUID.randomUUID();
        UUID otherId = UUID.randomUUID();
        insertUser(ownerId, "project-task-owner@example.com");
        insertUser(otherId, "project-task-other@example.com");
        try (Connection connection = DriverManager.getConnection(url, "jobiss_migrator", migratorPassword);
             Statement statement = connection.createStatement()) {
            statement.executeUpdate("""
                    insert into career_graphs (user_id) values ('%s'), ('%s')
                    """.formatted(ownerId, otherId));
        }

        ObjectMapper objectMapper = new ObjectMapper();
        V3ProjectTaskProgressService taskService = new V3ProjectTaskProgressService(
                rlsExecutor(), objectMapper
        );
        V3ProjectProgressService projectService = new V3ProjectProgressService(
                objectMapper, taskService
        );
        JsonNode snapshot = objectMapper.readTree("""
                {"roadmapVersion":1,"nodes":[{
                  "nodeId":"project:estgames-backend","nodeKind":"TARGET_PROJECT",
                  "targetRef":"estgames-backend","title":"게임 구매 API 프로젝트",
                  "sectionKey":"BACKEND","displayRank":10,"projectSpec":{
                    "objective":"구매 정합성을 구현하고 검증한다.",
                    "requiredCapabilityKeys":[],
                    "tasks":[
                      {"taskKey":"task.domain-model","necessity":"REQUIRED",
                       "title":"구매 상태 모델링","objective":"상태 전이를 정의한다.",
                       "acceptanceCriteria":["허용 전이를 문서화한다.","잘못된 전이를 테스트한다."],
                       "capabilityKeys":["backend.state-transition"],"dependsOnTaskKeys":[]},
                      {"taskKey":"task.purchase-api","necessity":"REQUIRED",
                       "title":"구매 API 구현","objective":"원자적인 구매를 구현한다.",
                       "acceptanceCriteria":["원자성 테스트가 통과한다.","중복 요청 테스트가 통과한다."],
                       "capabilityKeys":["backend.transaction-atomicity"],
                       "dependsOnTaskKeys":["task.domain-model"]}
                    ]
                  }
                }],"relations":[]}
                """);

        JsonNode overlaid = rlsExecutor().write(
                ownerId,
                jdbc -> projectService.synchronizeAndOverlay(jdbc, ownerId, snapshot)
        );
        UUID projectNodeId = UUID.fromString(
                overlaid.path("nodes").get(0).path("careerNodeId").stringValue()
        );

        assertThat(taskService.tasks(ownerId, projectNodeId))
                .extracting(V3ProjectTaskProgressService.TaskView::taskKey)
                .containsExactly("task.domain-model", "task.purchase-api");
        assertThat(taskService.tasks(ownerId, projectNodeId).get(1).dependsOnTaskKeys().get(0).stringValue())
                .isEqualTo("task.domain-model");
        assertThat(taskService.tasks(otherId, projectNodeId)).isEmpty();
    }

    private static RefreshTokenService refreshTokenService() {
        RlsTransactionExecutor rls = rlsExecutor();
        JobissProperties properties = new JobissProperties(
                new JobissProperties.Auth(
                        "local-test-jwt-secret-with-at-least-32-bytes",
                        7200,
                        1209600,
                        2592000,
                        false
                ),
                new JobissProperties.Ai(
                        "http://localhost:8000",
                        "local-test-ai-secret",
                        false,
                        1000,
                        10,
                        2
                )
        );
        return new RefreshTokenService(rls, properties);
    }

    private static RlsTransactionExecutor rlsExecutor() {
        DriverManagerDataSource dataSource = new DriverManagerDataSource(
                url,
                "jobiss_app",
                appPassword
        );
        return new RlsTransactionExecutor(
                JdbcClient.create(dataSource),
                new TransactionTemplate(new DataSourceTransactionManager(dataSource))
        );
    }

    private static void insertUser(UUID userId, String email) throws Exception {
        try (Connection connection = DriverManager.getConnection(url, "jobiss_migrator", migratorPassword);
             Statement statement = connection.createStatement()) {
            statement.executeUpdate("""
                    insert into users (id, email, display_name)
                    values ('%s', '%s', 'Local integration user');
                    insert into auth_identities (user_id, email, password_hash)
                    values ('%s', '%s', 'irreversible-test-hash');
                    """.formatted(userId, email, userId, email));
        }
    }

    private static UUID insertPosting(Statement statement, UUID userId, String email) throws Exception {
        statement.executeUpdate("""
                insert into users (id, email, display_name)
                values ('%s', '%s', 'Queue user')
                """.formatted(userId, email));
        UUID postingId = UUID.randomUUID();
        statement.executeUpdate("""
                insert into job_postings (
                    id, user_id, source_type, raw_text, content_fingerprint
                ) values (
                    '%s', '%s', 'TEXT', 'queue integration posting',
                    encode(digest('%s', 'sha256'), 'hex')
                )
                """.formatted(postingId, userId, postingId));
        return postingId;
    }

    private static UUID insertJob(
            Statement statement,
            UUID userId,
            UUID postingId,
            String status,
            String createdOffset
    ) throws Exception {
        UUID jobId = UUID.randomUUID();
        statement.executeUpdate("""
                insert into analysis_jobs (
                    id, user_id, posting_id, status, worker_id, locked_until, created_at
                ) values (
                    '%s', '%s', '%s', '%s', %s, %s, now() + interval '%s'
                )
                """.formatted(
                jobId,
                userId,
                postingId,
                status,
                "RUNNING".equals(status) ? "'existing-worker'" : "null",
                "RUNNING".equals(status) ? "now() + interval '10 minutes'" : "null",
                createdOffset
        ));
        return jobId;
    }

    private static void setUser(Statement statement, UUID userId) throws Exception {
        statement.execute("select set_config('app.current_user_id', '%s', true)".formatted(userId));
    }
}
