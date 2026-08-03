package com.jobiss.auth;

import com.jobiss.common.ApiException;
import com.jobiss.db.RlsTransactionExecutor;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;

import java.time.OffsetDateTime;
import java.util.Optional;
import java.util.UUID;

@Service
public class AuthService {

    private final JdbcClient jdbcClient;
    private final RlsTransactionExecutor rls;
    private final PasswordEncoder passwordEncoder;

    public AuthService(
            JdbcClient jdbcClient,
            RlsTransactionExecutor rls,
            PasswordEncoder passwordEncoder
    ) {
        this.jdbcClient = jdbcClient;
        this.rls = rls;
        this.passwordEncoder = passwordEncoder;
    }

    public UserView register(String email, String password, String displayName) {
        UUID userId = UUID.randomUUID();
        String normalizedEmail = email.trim().toLowerCase();
        String passwordHash = passwordEncoder.encode(password);
        try {
            return rls.write(userId, jdbc -> {
                jdbc.sql("""
                                insert into users (id, email, display_name)
                                values (:id, :email, :displayName)
                                """)
                        .param("id", userId)
                        .param("email", normalizedEmail)
                        .param("displayName", displayName.trim())
                        .update();

                jdbc.sql("""
                                select create_auth_identity(
                                    :id,
                                    cast(:email as citext),
                                    cast(:passwordHash as text)
                                )
                                """)
                        .param("id", userId)
                        .param("email", normalizedEmail)
                        .param("passwordHash", passwordHash)
                        .query(Object.class)
                        .optional();

                UUID graphId = jdbc.sql("""
                                insert into career_graphs (user_id)
                                values (:userId)
                                returning id
                                """)
                        .param("userId", userId)
                        .query(UUID.class)
                        .single();

                jdbc.sql("""
                                insert into career_nodes (
                                    user_id,
                                    graph_id,
                                    competency_id,
                                    kind,
                                    canonical_key,
                                    title,
                                    subtitle,
                                    domain,
                                    scope_definition,
                                    level,
                                    detail,
                                    rank
                                )
                                select
                                    :userId,
                                    :graphId,
                                    c.id,
                                    'FOUNDATION',
                                    c.canonical_key,
                                    c.title,
                                    '직접 완료 표시',
                                    c.domain,
                                    c.scope_definition,
                                    1,
                                    jsonb_build_object(
                                        'selfConfirmable',
                                        c.self_confirmable,
                                        'why',
                                        case c.canonical_key
                                            when 'foundation.programming'
                                                then '모든 개발 분야에서 코드를 읽고 작은 문제를 해결하기 위한 공통 출발점입니다.'
                                            when 'foundation.git-terminal'
                                                then '프로젝트 실행과 협업 기록을 남기기 위한 모든 개발 직무의 공통 도구입니다.'
                                            else '기술 이름을 외우는 대신 프로그램이 동작하는 이유를 설명하기 위한 기반입니다.'
                                        end,
                                        'estimatedDuration',
                                        case c.canonical_key
                                            when 'foundation.programming' then '1~2일'
                                            when 'foundation.git-terminal' then '1일'
                                            else '2~3일'
                                        end,
                                        'quests',
                                        case c.canonical_key
                                            when 'foundation.programming' then cast(
                                                '[{"title":"기초 문법 점검","description":"변수·조건·반복 예제를 작성합니다.","doneCriteria":"각 문법이 언제 필요한지 설명한다"},{"title":"함수로 문제 나누기","description":"작은 프로그램을 여러 함수로 분리합니다.","doneCriteria":"입력·처리·출력을 함수로 구분한다"},{"title":"작은 문제 해결","description":"자료구조 하나를 사용한 문제를 해결합니다.","doneCriteria":"실행 결과와 선택 이유를 설명한다"}]'
                                                as jsonb
                                            )
                                            when 'foundation.git-terminal' then cast(
                                                '[{"title":"터미널로 프로젝트 실행","description":"이동·확인·실행 명령을 사용합니다.","doneCriteria":"README만 보고 프로젝트를 실행한다"},{"title":"브랜치 작업","description":"기능 브랜치와 의미 있는 커밋을 남깁니다.","doneCriteria":"브랜치와 커밋 기록을 확인한다"},{"title":"실행 방법 기록","description":"다른 사람이 따를 실행 문서를 씁니다.","doneCriteria":"새 환경에서 문서대로 실행된다"}]'
                                                as jsonb
                                            )
                                            else cast(
                                                '[{"title":"프로세스와 메모리 설명","description":"실행 흐름을 자신의 말로 정리합니다.","doneCriteria":"예시로 핵심 개념을 설명한다"},{"title":"자료구조 비교","description":"배열·리스트·맵의 선택 기준을 비교합니다.","doneCriteria":"조회·삽입 특성에 따라 선택한다"},{"title":"복잡도 점검","description":"코드의 반복 횟수와 복잡도를 계산합니다.","doneCriteria":"간단한 코드의 Big-O를 설명한다"}]'
                                                as jsonb
                                            )
                                        end
                                    ),
                                    case c.canonical_key
                                        when 'foundation.programming' then 0
                                        when 'foundation.git-terminal' then 1
                                        else 2
                                    end
                                from competency_catalog c
                                where c.canonical_key in (
                                    'foundation.programming',
                                    'foundation.git-terminal',
                                    'foundation.cs'
                                )
                                """)
                        .param("userId", userId)
                        .param("graphId", graphId)
                        .update();

                jdbc.sql("""
                                insert into node_progress (user_id, node_id)
                                select :userId, n.id
                                from career_nodes n
                                where n.graph_id = :graphId
                                """)
                        .param("userId", userId)
                        .param("graphId", graphId)
                        .update();

                jdbc.sql("""
                                insert into user_competencies (
                                    user_id,
                                    catalog_competency_id,
                                    canonical_key,
                                    title,
                                    competency_kind,
                                    domain,
                                    default_stage,
                                    scope_definition,
                                    progress_status,
                                    verified_level
                                )
                                select
                                    :userId,
                                    c.id,
                                    c.canonical_key,
                                    c.title,
                                    'KNOWLEDGE',
                                    c.domain,
                                    'FOUNDATION',
                                    c.scope_definition,
                                    'NOT_STARTED',
                                    0
                                from competency_catalog c
                                where c.canonical_key in (
                                    'foundation.programming',
                                    'foundation.git-terminal',
                                    'foundation.cs'
                                )
                                on conflict (user_id, canonical_key) do nothing
                                """)
                        .param("userId", userId)
                        .update();

                return findCurrentUser(jdbc, userId);
            });
        } catch (DataIntegrityViolationException exception) {
            throw new ApiException(
                    HttpStatus.CONFLICT,
                    "EMAIL_ALREADY_EXISTS",
                    "이미 가입된 이메일입니다."
            );
        }
    }

    public UserView login(String email, String password) {
        Optional<UserAccount> account = jdbcClient.sql("""
                        select id, email, password_hash, status
                        from auth_lookup_user(cast(:email as citext))
                        """)
                .param("email", email.trim().toLowerCase())
                .query((rs, rowNum) -> new UserAccount(
                        rs.getObject("id", UUID.class),
                        rs.getString("email"),
                        rs.getString("password_hash"),
                        rs.getString("status")
                ))
                .optional();

        UserAccount user = account
                .filter(value -> passwordEncoder.matches(password, value.passwordHash()))
                .orElseThrow(() -> new ApiException(
                        HttpStatus.UNAUTHORIZED,
                        "INVALID_CREDENTIALS",
                        "이메일 또는 비밀번호가 올바르지 않습니다."
                ));

        if (!"ACTIVE".equals(user.status())) {
            throw new ApiException(
                    HttpStatus.FORBIDDEN,
                    "ACCOUNT_NOT_ACTIVE",
                    "현재 사용할 수 없는 계정입니다."
            );
        }
        return rls.read(user.id(), jdbc -> findCurrentUser(jdbc, user.id()));
    }

    public UserView me(UUID userId) {
        return rls.read(userId, jdbc -> findCurrentUser(jdbc, userId));
    }

    private UserView findCurrentUser(JdbcClient jdbc, UUID userId) {
        return jdbc.sql("""
                        select id, email, display_name, status, account_role, created_at
                        from users
                        where id = :id
                        """)
                .param("id", userId)
                .query((rs, rowNum) -> new UserView(
                        rs.getObject("id", UUID.class),
                        rs.getString("email"),
                        rs.getString("display_name"),
                        rs.getString("status"),
                        rs.getString("account_role"),
                        rs.getObject("created_at", OffsetDateTime.class)
                ))
                .optional()
                .orElseThrow(() -> new ApiException(
                        HttpStatus.NOT_FOUND,
                        "USER_NOT_FOUND",
                        "사용자를 찾을 수 없습니다."
                ));
    }

    private record UserAccount(
            UUID id,
            String email,
            String passwordHash,
            String status
    ) {
    }

    public record UserView(
            UUID id,
            String email,
            String displayName,
            String status,
            String accountRole,
            OffsetDateTime createdAt
    ) {
    }
}
