package com.jobiss.analysis.v3;

import com.jobiss.common.ApiException;
import com.jobiss.db.RlsTransactionExecutor;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

@Service
public class V3EmploymentService {
    private final RlsTransactionExecutor rls;

    public V3EmploymentService(RlsTransactionExecutor rls) {
        this.rls = rls;
    }

    public List<EmploymentView> list(UUID userId) {
        return rls.read(userId, jdbc -> jdbc.sql("""
                        select id, canonical_role_id, role_family, role_specialization,
                               employer, role_title, started_on, ended_on, evidence_url,
                               description, evidence_state, operator_reason, created_at, reviewed_at
                        from user_employment_records
                        order by started_on desc, created_at desc
                        """).query((rs, rowNum) -> map(rs)).list());
    }

    public EmploymentView submit(UUID userId, Submit command) {
        if (command.endedOn() != null && command.endedOn().isBefore(command.startedOn())) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "EMPLOYMENT_DATES_INVALID", "종료일은 시작일보다 빠를 수 없습니다.");
        }
        if (command.startedOn().isAfter(LocalDate.now())) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "EMPLOYMENT_START_IN_FUTURE", "미래 경력은 증거로 등록할 수 없습니다.");
        }
        return rls.write(userId, jdbc -> {
            UUID id = jdbc.sql("""
                            insert into user_employment_records (
                                user_id, canonical_role_id, role_family, role_specialization,
                                employer, role_title, started_on, ended_on, evidence_url, description
                            ) values (
                                :userId, :canonicalRoleId, :roleFamily, :roleSpecialization,
                                :employer, :roleTitle, :startedOn, :endedOn, :evidenceUrl, :description
                            ) returning id
                            """)
                    .param("userId", userId)
                    .param("canonicalRoleId", blank(command.canonicalRoleId()))
                    .param("roleFamily", required(command.roleFamily()))
                    .param("roleSpecialization", required(command.roleSpecialization()))
                    .param("employer", required(command.employer()))
                    .param("roleTitle", required(command.roleTitle()))
                    .param("startedOn", command.startedOn())
                    .param("endedOn", command.endedOn())
                    .param("evidenceUrl", required(command.evidenceUrl()))
                    .param("description", required(command.description()))
                    .query(UUID.class).single();
            return jdbc.sql("""
                            select id, canonical_role_id, role_family, role_specialization,
                                   employer, role_title, started_on, ended_on, evidence_url,
                                   description, evidence_state, operator_reason, created_at, reviewed_at
                            from user_employment_records where id = :id
                            """).param("id", id).query((rs, rowNum) -> map(rs)).single();
        });
    }

    private static EmploymentView map(java.sql.ResultSet rs) throws java.sql.SQLException {
        return new EmploymentView(
                rs.getObject("id", UUID.class), rs.getString("canonical_role_id"),
                rs.getString("role_family"), rs.getString("role_specialization"),
                rs.getString("employer"), rs.getString("role_title"),
                rs.getObject("started_on", LocalDate.class), rs.getObject("ended_on", LocalDate.class),
                rs.getString("evidence_url"), rs.getString("description"),
                rs.getString("evidence_state"), rs.getString("operator_reason"),
                rs.getObject("created_at", OffsetDateTime.class), rs.getObject("reviewed_at", OffsetDateTime.class)
        );
    }

    private static String required(String value) {
        if (value == null || value.isBlank()) throw new ApiException(HttpStatus.BAD_REQUEST, "EMPLOYMENT_FIELD_REQUIRED", "경력 증거의 필수 항목을 입력해 주세요.");
        return value.trim();
    }
    private static String blank(String value) { return value == null || value.isBlank() ? null : value.trim(); }

    public record Submit(String canonicalRoleId, String roleFamily, String roleSpecialization,
                         String employer, String roleTitle, LocalDate startedOn, LocalDate endedOn,
                         String evidenceUrl, String description) {}
    public record EmploymentView(UUID id, String canonicalRoleId, String roleFamily,
                                 String roleSpecialization, String employer, String roleTitle,
                                 LocalDate startedOn, LocalDate endedOn, String evidenceUrl,
                                 String description, String evidenceState, String operatorReason,
                                 OffsetDateTime createdAt, OffsetDateTime reviewedAt) {}
}
