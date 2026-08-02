package com.jobiss.db;

import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.postgresql.PostgreSQLContainer;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

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

    private static void setUser(Statement statement, UUID userId) throws Exception {
        statement.execute(
                "select set_config('app.current_user_id', '%s', true)".formatted(userId)
        );
    }
}
