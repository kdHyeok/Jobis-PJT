CREATE TABLE analysis_agent_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    analysis_job_id uuid NOT NULL,
    sequence integer NOT NULL,
    event_data jsonb NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (analysis_job_id, sequence),
    CONSTRAINT analysis_agent_event_job_owner_fk
        FOREIGN KEY (analysis_job_id, user_id)
        REFERENCES analysis_jobs(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT analysis_agent_event_sequence_check
        CHECK (sequence BETWEEN 1 AND 10000),
    CONSTRAINT analysis_agent_event_data_check
        CHECK (jsonb_typeof(event_data) = 'object')
);

CREATE INDEX analysis_agent_events_job_sequence_idx
    ON analysis_agent_events (analysis_job_id, sequence);

ALTER TABLE analysis_agent_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis_agent_events FORCE ROW LEVEL SECURITY;

CREATE POLICY analysis_agent_events_owner_policy ON analysis_agent_events
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON analysis_agent_events TO jobiss_app;
REVOKE ALL ON analysis_agent_events FROM PUBLIC;
