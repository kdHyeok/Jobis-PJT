DROP POLICY user_employment_records_owner_policy ON user_employment_records;

CREATE POLICY user_employment_records_owner_policy ON user_employment_records
    USING (
        user_id = app_current_user_id()
        OR EXISTS (
            SELECT 1 FROM users operator
            WHERE operator.id = app_current_user_id()
              AND operator.account_role = 'OPERATOR'
        )
    )
    WITH CHECK (
        user_id = app_current_user_id()
        OR EXISTS (
            SELECT 1 FROM users operator
            WHERE operator.id = app_current_user_id()
              AND operator.account_role = 'OPERATOR'
        )
    );
