CREATE TABLE user_goal_profiles (
    user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    current_goal_posting_id uuid,
    final_goal_text text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT user_goal_current_posting_owner_fk
        FOREIGN KEY (current_goal_posting_id, user_id)
        REFERENCES job_postings(id, user_id)
        ON DELETE SET NULL (current_goal_posting_id),
    CONSTRAINT user_goal_final_text_check
        CHECK (
            final_goal_text IS NULL
            OR char_length(final_goal_text) BETWEEN 1 AND 2000
        )
);

ALTER TABLE user_goal_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_goal_profiles FORCE ROW LEVEL SECURITY;

CREATE POLICY user_goal_profiles_owner_policy ON user_goal_profiles
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON user_goal_profiles TO jobiss_app;
REVOKE ALL ON user_goal_profiles FROM PUBLIC;
