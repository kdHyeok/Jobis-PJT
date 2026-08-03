-- Operators need narrowly scoped cross-user access while resolving posting
-- duplicates and competency assessment appeals. Every policy still verifies
-- the current authenticated user against the users table; normal users keep
-- the owner-only policies defined by the earlier migrations.

CREATE POLICY job_postings_operator_policy
ON job_postings
    USING (
        EXISTS (
            SELECT 1
            FROM users current_user_record
            WHERE current_user_record.id = app_current_user_id()
              AND current_user_record.account_role = 'OPERATOR'
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1
            FROM users current_user_record
            WHERE current_user_record.id = app_current_user_id()
              AND current_user_record.account_role = 'OPERATOR'
        )
    );

CREATE POLICY user_competencies_operator_policy
ON user_competencies
    USING (
        EXISTS (
            SELECT 1
            FROM users current_user_record
            WHERE current_user_record.id = app_current_user_id()
              AND current_user_record.account_role = 'OPERATOR'
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1
            FROM users current_user_record
            WHERE current_user_record.id = app_current_user_id()
              AND current_user_record.account_role = 'OPERATOR'
        )
    );

CREATE POLICY career_nodes_operator_policy
ON career_nodes
    USING (
        EXISTS (
            SELECT 1
            FROM users current_user_record
            WHERE current_user_record.id = app_current_user_id()
              AND current_user_record.account_role = 'OPERATOR'
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1
            FROM users current_user_record
            WHERE current_user_record.id = app_current_user_id()
              AND current_user_record.account_role = 'OPERATOR'
        )
    );

CREATE POLICY node_progress_operator_policy
ON node_progress
    USING (
        EXISTS (
            SELECT 1
            FROM users current_user_record
            WHERE current_user_record.id = app_current_user_id()
              AND current_user_record.account_role = 'OPERATOR'
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1
            FROM users current_user_record
            WHERE current_user_record.id = app_current_user_id()
              AND current_user_record.account_role = 'OPERATOR'
        )
    );

CREATE POLICY notifications_operator_policy
ON notifications
    USING (
        EXISTS (
            SELECT 1
            FROM users current_user_record
            WHERE current_user_record.id = app_current_user_id()
              AND current_user_record.account_role = 'OPERATOR'
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1
            FROM users current_user_record
            WHERE current_user_record.id = app_current_user_id()
              AND current_user_record.account_role = 'OPERATOR'
        )
    );
