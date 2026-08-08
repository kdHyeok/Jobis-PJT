CREATE TABLE user_career_goals (
    user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    current_posting_id uuid,
    final_posting_id uuid,
    final_goal_text varchar(240),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT user_career_goals_current_posting_fk
        FOREIGN KEY (current_posting_id, user_id)
        REFERENCES job_postings(id, user_id)
        ON DELETE SET NULL (current_posting_id),
    CONSTRAINT user_career_goals_final_posting_fk
        FOREIGN KEY (final_posting_id, user_id)
        REFERENCES job_postings(id, user_id)
        ON DELETE SET NULL (final_posting_id),
    CONSTRAINT user_career_goals_final_goal_text_check
        CHECK (final_goal_text IS NULL OR length(btrim(final_goal_text)) > 0)
);

CREATE TRIGGER user_career_goals_touch_updated_at
BEFORE UPDATE ON user_career_goals
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

ALTER TABLE user_career_goals ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_career_goals FORCE ROW LEVEL SECURITY;

CREATE POLICY user_career_goals_owner_policy ON user_career_goals
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON user_career_goals TO jobiss_app;
REVOKE ALL ON user_career_goals FROM PUBLIC;
