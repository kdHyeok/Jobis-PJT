package com.jobiss.profile;

import com.jobiss.common.ApiException;
import com.jobiss.db.RlsTransactionExecutor;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

import java.time.OffsetDateTime;
import java.util.UUID;

@Service
public class GoalProfileService {

    private final RlsTransactionExecutor rls;

    public GoalProfileService(RlsTransactionExecutor rls) {
        this.rls = rls;
    }

    public GoalProfileView get(UUID userId) {
        return rls.read(userId, jdbc -> load(jdbc, userId));
    }

    public GoalProfileView update(
            UUID userId,
            UUID currentGoalPostingId,
            String finalGoalText
    ) {
        String normalizedFinalGoal = normalize(finalGoalText);
        return rls.write(userId, jdbc -> {
            if (currentGoalPostingId != null) {
                boolean selectable = jdbc.sql("""
                                select exists (
                                    select 1
                                    from job_postings posting
                                    join analysis_jobs analysis
                                      on analysis.posting_id = posting.id
                                     and analysis.user_id = posting.user_id
                                    where posting.id = :postingId
                                      and posting.archived_at is null
                                      and analysis.status = 'SUCCEEDED'
                                )
                                """)
                        .param("postingId", currentGoalPostingId)
                        .query(Boolean.class)
                        .single();
                if (!selectable) {
                    throw new ApiException(
                            HttpStatus.BAD_REQUEST,
                            "CURRENT_GOAL_NOT_SELECTABLE",
                            "분석이 완료된 활성 공고만 현재 목표로 선택할 수 있습니다."
                    );
                }
            }

            jdbc.sql("""
                            insert into user_goal_profiles (
                                user_id,
                                current_goal_posting_id,
                                final_goal_text
                            )
                            values (
                                :userId,
                                :currentGoalPostingId,
                                :finalGoalText
                            )
                            on conflict (user_id)
                            do update set
                                current_goal_posting_id =
                                    excluded.current_goal_posting_id,
                                final_goal_text = excluded.final_goal_text,
                                updated_at = now()
                            """)
                    .param("userId", userId)
                    .param("currentGoalPostingId", currentGoalPostingId)
                    .param("finalGoalText", normalizedFinalGoal)
                    .update();
            return load(jdbc, userId);
        });
    }

    private GoalProfileView load(JdbcClient jdbc, UUID userId) {
        return jdbc.sql("""
                        select
                            goal.current_goal_posting_id,
                            posting.company_name,
                            posting.role_title,
                            goal.final_goal_text,
                            goal.updated_at
                        from user_goal_profiles goal
                        left join job_postings posting
                          on posting.id = goal.current_goal_posting_id
                        where goal.user_id = :userId
                        """)
                .param("userId", userId)
                .query((rs, rowNum) -> new GoalProfileView(
                        rs.getObject("current_goal_posting_id", UUID.class),
                        rs.getString("company_name"),
                        rs.getString("role_title"),
                        rs.getString("final_goal_text"),
                        rs.getObject("updated_at", OffsetDateTime.class)
                ))
                .optional()
                .orElse(new GoalProfileView(null, null, null, null, null));
    }

    private String normalize(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        return value.trim();
    }

    public record GoalProfileView(
            UUID currentGoalPostingId,
            String currentGoalCompanyName,
            String currentGoalRoleTitle,
            String finalGoalText,
            OffsetDateTime updatedAt
    ) {
    }
}
