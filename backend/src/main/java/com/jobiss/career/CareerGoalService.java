package com.jobiss.career;

import com.jobiss.common.ApiException;
import com.jobiss.db.RlsTransactionExecutor;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

import java.util.UUID;

@Service
public class CareerGoalService {

    private final RlsTransactionExecutor rls;

    public CareerGoalService(RlsTransactionExecutor rls) {
        this.rls = rls;
    }

    public CareerGoals get(UUID userId) {
        return rls.read(userId, jdbc -> jdbc.sql("""
                        select goals.current_posting_id,
                               current_posting.company_name as current_company_name,
                               current_posting.role_title as current_role_title,
                               goals.final_posting_id,
                               final_posting.company_name as final_company_name,
                               final_posting.role_title as final_role_title,
                               goals.final_goal_text
                        from user_career_goals goals
                        left join job_postings current_posting
                          on current_posting.id = goals.current_posting_id
                         and current_posting.user_id = goals.user_id
                        left join job_postings final_posting
                          on final_posting.id = goals.final_posting_id
                         and final_posting.user_id = goals.user_id
                        where goals.user_id = :userId
                        """)
                .param("userId", userId)
                .query((rs, rowNum) -> new CareerGoals(
                        rs.getObject("current_posting_id", UUID.class),
                        rs.getString("current_company_name"),
                        rs.getString("current_role_title"),
                        rs.getObject("final_posting_id", UUID.class),
                        rs.getString("final_company_name"),
                        rs.getString("final_role_title"),
                        rs.getString("final_goal_text")
                ))
                .optional()
                .orElse(new CareerGoals(null, null, null, null, null, null, null)));
    }

    public CareerGoals update(UUID userId, UpdateCareerGoals request) {
        return rls.write(userId, jdbc -> {
            requireOwnedPosting(jdbc, userId, request.currentPostingId());
            requireOwnedPosting(jdbc, userId, request.finalPostingId());
            String finalGoalText = normalize(request.finalGoalText());
            jdbc.sql("""
                            insert into user_career_goals (
                                user_id, current_posting_id, final_posting_id, final_goal_text
                            ) values (
                                :userId, :currentPostingId, :finalPostingId, :finalGoalText
                            )
                            on conflict (user_id) do update set
                                current_posting_id = excluded.current_posting_id,
                                final_posting_id = excluded.final_posting_id,
                                final_goal_text = excluded.final_goal_text
                            """)
                    .param("userId", userId)
                    .param("currentPostingId", request.currentPostingId())
                    .param("finalPostingId", request.finalPostingId())
                    .param("finalGoalText", finalGoalText)
                    .update();
            return getWithinTransaction(jdbc, userId);
        });
    }

    private CareerGoals getWithinTransaction(JdbcClient jdbc, UUID userId) {
        return jdbc.sql("""
                        select goals.current_posting_id,
                               current_posting.company_name as current_company_name,
                               current_posting.role_title as current_role_title,
                               goals.final_posting_id,
                               final_posting.company_name as final_company_name,
                               final_posting.role_title as final_role_title,
                               goals.final_goal_text
                        from user_career_goals goals
                        left join job_postings current_posting
                          on current_posting.id = goals.current_posting_id
                         and current_posting.user_id = goals.user_id
                        left join job_postings final_posting
                          on final_posting.id = goals.final_posting_id
                         and final_posting.user_id = goals.user_id
                        where goals.user_id = :userId
                        """)
                .param("userId", userId)
                .query((rs, rowNum) -> new CareerGoals(
                        rs.getObject("current_posting_id", UUID.class),
                        rs.getString("current_company_name"),
                        rs.getString("current_role_title"),
                        rs.getObject("final_posting_id", UUID.class),
                        rs.getString("final_company_name"),
                        rs.getString("final_role_title"),
                        rs.getString("final_goal_text")
                ))
                .single();
    }

    private void requireOwnedPosting(JdbcClient jdbc, UUID userId, UUID postingId) {
        if (postingId == null) return;
        boolean exists = jdbc.sql("""
                        select exists(
                            select 1 from job_postings
                            where id = :postingId and user_id = :userId and archived_at is null
                        )
                        """)
                .param("postingId", postingId)
                .param("userId", userId)
                .query(Boolean.class)
                .single();
        if (!exists) {
            throw new ApiException(
                    HttpStatus.BAD_REQUEST,
                    "CAREER_GOAL_POSTING_INVALID",
                    "현재 사용할 수 있는 내 채용 공고만 목표로 선택할 수 있습니다."
            );
        }
    }

    private String normalize(String value) {
        if (value == null || value.isBlank()) return null;
        return value.trim();
    }

    public record UpdateCareerGoals(
            UUID currentPostingId,
            UUID finalPostingId,
            String finalGoalText
    ) {
    }

    public record CareerGoals(
            UUID currentPostingId,
            String currentCompanyName,
            String currentRoleTitle,
            UUID finalPostingId,
            String finalCompanyName,
            String finalRoleTitle,
            String finalGoalText
    ) {
    }
}
