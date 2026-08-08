CREATE TABLE user_employment_records (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    canonical_role_id varchar(160),
    role_family varchar(120) NOT NULL,
    role_specialization varchar(160) NOT NULL,
    employer varchar(200) NOT NULL,
    role_title varchar(200) NOT NULL,
    started_on date NOT NULL,
    ended_on date,
    evidence_url text NOT NULL,
    description text NOT NULL,
    evidence_state varchar(20) NOT NULL DEFAULT 'EVIDENCED'
        CHECK (evidence_state IN ('CLAIMED', 'EVIDENCED', 'VERIFIED', 'REJECTED')),
    operator_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
    operator_reason text,
    reviewed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id),
    CHECK (ended_on IS NULL OR ended_on >= started_on)
);

CREATE INDEX user_employment_records_role_idx
    ON user_employment_records (user_id, role_family, role_specialization, evidence_state);
CREATE INDEX user_employment_records_pending_idx
    ON user_employment_records (created_at)
    WHERE evidence_state = 'EVIDENCED';

CREATE TRIGGER user_employment_records_touch_updated_at
BEFORE UPDATE ON user_employment_records
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

ALTER TABLE user_employment_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_employment_records FORCE ROW LEVEL SECURITY;
CREATE POLICY user_employment_records_owner_policy ON user_employment_records
    USING (
        user_id = app_current_user_id()
        OR EXISTS (
            SELECT 1 FROM users operator
            WHERE operator.id = app_current_user_id()
              AND operator.account_role = 'OPERATOR'
        )
    )
    WITH CHECK (user_id = app_current_user_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON user_employment_records TO jobiss_app;
REVOKE ALL ON user_employment_records FROM PUBLIC;
