CREATE TABLE capability_review_candidates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    analysis_job_id uuid NOT NULL,
    normalization_id varchar(160) NOT NULL,
    requirement_id varchar(160) NOT NULL,
    candidate_id varchar(160) NOT NULL,
    decision_kind varchar(40) NOT NULL,
    display_name varchar(240) NOT NULL,
    proposed_kind varchar(40),
    scope_definition text,
    aliases jsonb NOT NULL DEFAULT '[]'::jsonb,
    evidence_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    match_candidates jsonb NOT NULL DEFAULT '[]'::jsonb,
    confidence numeric(5,4),
    reason text NOT NULL,
    status varchar(32) NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING','ON_HOLD','APPROVED_STAGED','LINKED','NEEDS_SPLIT','REJECTED','PUBLISHED')),
    selected_canonical_key varchar(160),
    operator_user_id uuid REFERENCES users(id),
    operator_reason text,
    decided_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (analysis_job_id, candidate_id),
    CONSTRAINT capability_review_job_owner_fk
        FOREIGN KEY (analysis_job_id, source_user_id)
        REFERENCES analysis_jobs(id, user_id)
        ON DELETE CASCADE,
    CHECK (jsonb_typeof(aliases) = 'array'),
    CHECK (jsonb_typeof(evidence_ids) = 'array'),
    CHECK (jsonb_typeof(match_candidates) = 'array')
);

CREATE TABLE capability_graph_releases (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    graph_version varchar(80) NOT NULL UNIQUE,
    status varchar(24) NOT NULL DEFAULT 'PUBLISHED' CHECK (status IN ('PUBLISHED','SUPERSEDED')),
    candidate_snapshot jsonb NOT NULL,
    published_by uuid NOT NULL REFERENCES users(id),
    release_notes text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (jsonb_typeof(candidate_snapshot) = 'array')
);

CREATE TABLE capability_review_actions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_id uuid NOT NULL REFERENCES capability_review_candidates(id) ON DELETE CASCADE,
    operator_user_id uuid NOT NULL REFERENCES users(id),
    action varchar(32) NOT NULL,
    before_state jsonb NOT NULL,
    after_state jsonb NOT NULL,
    reason text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER capability_review_candidates_touch_updated_at
BEFORE UPDATE ON capability_review_candidates
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

CREATE INDEX capability_review_candidates_status_idx
    ON capability_review_candidates (status, created_at);
CREATE INDEX capability_review_actions_candidate_idx
    ON capability_review_actions (candidate_id, created_at DESC);

ALTER TABLE capability_review_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE capability_review_candidates FORCE ROW LEVEL SECURITY;
ALTER TABLE capability_graph_releases ENABLE ROW LEVEL SECURITY;
ALTER TABLE capability_graph_releases FORCE ROW LEVEL SECURITY;
ALTER TABLE capability_review_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE capability_review_actions FORCE ROW LEVEL SECURITY;

CREATE POLICY capability_review_candidates_owner_policy ON capability_review_candidates
    USING (source_user_id = app_current_user_id())
    WITH CHECK (source_user_id = app_current_user_id());
CREATE POLICY capability_review_candidates_operator_policy ON capability_review_candidates
    USING (EXISTS (SELECT 1 FROM users u WHERE u.id = app_current_user_id() AND u.account_role = 'OPERATOR'))
    WITH CHECK (EXISTS (SELECT 1 FROM users u WHERE u.id = app_current_user_id() AND u.account_role = 'OPERATOR'));
CREATE POLICY capability_graph_releases_operator_policy ON capability_graph_releases
    USING (EXISTS (SELECT 1 FROM users u WHERE u.id = app_current_user_id() AND u.account_role = 'OPERATOR'))
    WITH CHECK (EXISTS (SELECT 1 FROM users u WHERE u.id = app_current_user_id() AND u.account_role = 'OPERATOR'));
CREATE POLICY capability_review_actions_operator_policy ON capability_review_actions
    USING (EXISTS (SELECT 1 FROM users u WHERE u.id = app_current_user_id() AND u.account_role = 'OPERATOR'))
    WITH CHECK (EXISTS (SELECT 1 FROM users u WHERE u.id = app_current_user_id() AND u.account_role = 'OPERATOR'));

GRANT SELECT, INSERT, UPDATE ON capability_review_candidates TO jobiss_app;
GRANT SELECT, INSERT, UPDATE ON capability_graph_releases TO jobiss_app;
GRANT SELECT, INSERT ON capability_review_actions TO jobiss_app;
REVOKE ALL ON capability_review_candidates, capability_graph_releases, capability_review_actions FROM PUBLIC;
