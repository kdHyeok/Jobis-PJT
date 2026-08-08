package com.jobiss.operator;

import com.jobiss.common.ApiException;
import com.jobiss.db.RlsTransactionExecutor;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDate;
import java.util.List;
import java.util.UUID;

@RestController
@RequestMapping("/api/operator/employment-reviews")
public class OperatorEmploymentController {
    private final RlsTransactionExecutor rls;
    public OperatorEmploymentController(RlsTransactionExecutor rls) { this.rls = rls; }

    @GetMapping
    List<ReviewView> list(@AuthenticationPrincipal UUID operatorId) {
        return rls.read(operatorId, jdbc -> {
            ensureOperator(jdbc);
            return jdbc.sql("""
                            select id, user_id, role_family, role_specialization, employer,
                                   role_title, started_on, ended_on, evidence_url, description
                            from user_employment_records
                            where evidence_state = 'EVIDENCED'
                            order by created_at limit 250
                            """).query((rs, rowNum) -> new ReviewView(
                    rs.getObject("id", UUID.class), rs.getObject("user_id", UUID.class),
                    rs.getString("role_family"), rs.getString("role_specialization"),
                    rs.getString("employer"), rs.getString("role_title"),
                    rs.getObject("started_on", LocalDate.class), rs.getObject("ended_on", LocalDate.class),
                    rs.getString("evidence_url"), rs.getString("description")
            )).list();
        });
    }

    @PostMapping("/{id}/resolve")
    void resolve(@AuthenticationPrincipal UUID operatorId, @PathVariable UUID id,
                 @Valid @RequestBody ResolveRequest request) {
        rls.write(operatorId, jdbc -> {
            ensureOperator(jdbc);
            int updated = jdbc.sql("""
                            update user_employment_records
                            set evidence_state = :state, operator_user_id = :operatorId,
                                operator_reason = :reason, reviewed_at = now()
                            where id = :id and evidence_state = 'EVIDENCED'
                            """)
                    .param("state", request.action()).param("operatorId", operatorId)
                    .param("reason", request.reason().trim()).param("id", id).update();
            if (updated != 1) throw new ApiException(HttpStatus.CONFLICT, "EMPLOYMENT_REVIEW_STALE", "이미 처리되었거나 찾을 수 없는 경력 증거입니다.");
            return null;
        });
    }

    private void ensureOperator(org.springframework.jdbc.core.simple.JdbcClient jdbc) {
        boolean operator = jdbc.sql("select exists(select 1 from users where id = app_current_user_id() and account_role = 'OPERATOR')")
                .query(Boolean.class).single();
        if (!operator) throw new ApiException(HttpStatus.FORBIDDEN, "OPERATOR_REQUIRED", "운영자 권한이 필요합니다.");
    }

    record ResolveRequest(@NotBlank @Pattern(regexp = "VERIFIED|REJECTED") String action,
                          @NotBlank @Size(max = 4000) String reason) {}
    record ReviewView(UUID id, UUID userId, String roleFamily, String roleSpecialization,
                      String employer, String roleTitle, LocalDate startedOn, LocalDate endedOn,
                      String evidenceUrl, String description) {}
}
