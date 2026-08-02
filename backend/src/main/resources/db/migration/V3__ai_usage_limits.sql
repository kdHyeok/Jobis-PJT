CREATE TABLE ai_usage_hourly (
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    usage_kind varchar(30) NOT NULL
        CHECK (usage_kind IN ('CHAT', 'ANALYSIS', 'EVIDENCE')),
    hour_start timestamptz NOT NULL,
    usage_count integer NOT NULL DEFAULT 0 CHECK (usage_count >= 0),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, usage_kind, hour_start)
);

CREATE INDEX ai_usage_hourly_cleanup_idx ON ai_usage_hourly (hour_start);

ALTER TABLE ai_usage_hourly ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_usage_hourly FORCE ROW LEVEL SECURITY;

CREATE POLICY ai_usage_hourly_owner_policy ON ai_usage_hourly
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON ai_usage_hourly TO jobiss_app;
