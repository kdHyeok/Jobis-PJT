package com.jobiss.db;

import com.jobiss.analysis.AiUsageLimitService;
import com.jobiss.posting.JobPostingService;
import com.jobiss.roadmap.RoadmapService;
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
        JobPostingService service = new JobPostingService(rls, usageLimit);

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
        service.applyDraft(userId);
        RoadmapService.DraftResult secondDraft = service.addTarget(userId, secondJobId);

        assertThat(secondDraft.draftVersion())
                .isGreaterThan(firstDraft.draftVersion());
        RoadmapService.Workspace workspace = service.get(userId);
        assertThat(workspace.targetCount()).isEqualTo(2);
        assertThat(workspace.draft()).isNotNull();
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

    private static void setUser(Statement statement, UUID userId) throws Exception {
        statement.execute(
                "select set_config('app.current_user_id', '%s', true)".formatted(userId)
        );
    }
}
