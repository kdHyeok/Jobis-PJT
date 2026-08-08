CREATE TABLE career_fragment_merge_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target_fragment_id uuid NOT NULL,
    fragment_ids uuid[] NOT NULL,
    before_snapshot jsonb NOT NULL,
    undone_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (jsonb_typeof(before_snapshot) = 'array'),
    CHECK (cardinality(fragment_ids) >= 2)
);

CREATE INDEX career_fragment_merge_events_user_recent_idx
    ON career_fragment_merge_events (user_id, created_at DESC);

ALTER TABLE career_fragment_merge_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE career_fragment_merge_events FORCE ROW LEVEL SECURITY;

CREATE POLICY career_fragment_merge_events_owner_policy
ON career_fragment_merge_events
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());

GRANT SELECT, INSERT, UPDATE ON career_fragment_merge_events TO jobiss_app;
REVOKE ALL ON career_fragment_merge_events FROM PUBLIC;
