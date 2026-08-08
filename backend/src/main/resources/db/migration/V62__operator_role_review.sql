CREATE TABLE role_review_candidates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    analysis_job_id uuid NOT NULL,
    position_id varchar(160) NOT NULL,
    source_title varchar(240) NOT NULL,
    proposed_family varchar(160) NOT NULL,
    proposed_specialization varchar(160) NOT NULL,
    evidence_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    confidence numeric(5,4) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    status varchar(32) NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING','ON_HOLD','APPROVED_STAGED','LINKED','REJECTED')),
    selected_canonical_role_id varchar(160),
    operator_user_id uuid REFERENCES users(id),
    operator_reason text,
    decided_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (analysis_job_id, position_id),
    CONSTRAINT role_review_job_owner_fk
        FOREIGN KEY (analysis_job_id, source_user_id)
        REFERENCES analysis_jobs(id, user_id)
        ON DELETE CASCADE,
    CHECK (jsonb_typeof(evidence_ids) = 'array')
);

CREATE TABLE role_review_actions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    candidate_id uuid NOT NULL REFERENCES role_review_candidates(id) ON DELETE CASCADE,
    operator_user_id uuid NOT NULL REFERENCES users(id),
    action varchar(32) NOT NULL,
    before_state jsonb NOT NULL,
    after_state jsonb NOT NULL,
    reason text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER role_review_candidates_touch_updated_at
BEFORE UPDATE ON role_review_candidates
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

CREATE INDEX role_review_candidates_status_idx
    ON role_review_candidates (status, created_at);

ALTER TABLE role_review_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE role_review_candidates FORCE ROW LEVEL SECURITY;
ALTER TABLE role_review_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE role_review_actions FORCE ROW LEVEL SECURITY;

CREATE POLICY role_review_candidates_owner_policy ON role_review_candidates
    USING (source_user_id = app_current_user_id())
    WITH CHECK (source_user_id = app_current_user_id());
CREATE POLICY role_review_candidates_operator_policy ON role_review_candidates
    USING (EXISTS (SELECT 1 FROM users u WHERE u.id = app_current_user_id() AND u.account_role = 'OPERATOR'))
    WITH CHECK (EXISTS (SELECT 1 FROM users u WHERE u.id = app_current_user_id() AND u.account_role = 'OPERATOR'));
CREATE POLICY role_review_actions_operator_policy ON role_review_actions
    USING (EXISTS (SELECT 1 FROM users u WHERE u.id = app_current_user_id() AND u.account_role = 'OPERATOR'))
    WITH CHECK (EXISTS (SELECT 1 FROM users u WHERE u.id = app_current_user_id() AND u.account_role = 'OPERATOR'));

GRANT SELECT, INSERT, UPDATE ON role_review_candidates TO jobiss_app;
GRANT SELECT, INSERT ON role_review_actions TO jobiss_app;
REVOKE ALL ON role_review_candidates, role_review_actions FROM PUBLIC;
