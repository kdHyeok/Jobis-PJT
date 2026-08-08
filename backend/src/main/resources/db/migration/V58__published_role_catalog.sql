ALTER TABLE role_review_candidates DROP CONSTRAINT role_review_candidates_status_check;
ALTER TABLE role_review_candidates ADD CONSTRAINT role_review_candidates_status_check
    CHECK (status IN ('PENDING','ON_HOLD','APPROVED_STAGED','LINKED','REJECTED','PUBLISHED'));

CREATE TABLE approved_role_catalog (
    canonical_role_id varchar(160) PRIMARY KEY,
    family varchar(160) NOT NULL,
    specialization varchar(160) NOT NULL,
    catalog_version bigint NOT NULL,
    source_candidate_id uuid REFERENCES role_review_candidates(id) ON DELETE SET NULL,
    active boolean NOT NULL DEFAULT true,
    published_at timestamptz NOT NULL DEFAULT now(),
    published_by uuid REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE role_catalog_releases (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version_number bigint NOT NULL UNIQUE,
    published_count integer NOT NULL CHECK (published_count >= 0),
    notes text NOT NULL,
    published_by uuid REFERENCES users(id) ON DELETE SET NULL,
    published_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE approved_role_catalog ENABLE ROW LEVEL SECURITY;
ALTER TABLE approved_role_catalog FORCE ROW LEVEL SECURITY;
ALTER TABLE role_catalog_releases ENABLE ROW LEVEL SECURITY;
ALTER TABLE role_catalog_releases FORCE ROW LEVEL SECURITY;
CREATE POLICY approved_role_catalog_read_policy ON approved_role_catalog USING (true);
CREATE POLICY role_catalog_releases_read_policy ON role_catalog_releases USING (true);
CREATE POLICY approved_role_catalog_operator_policy ON approved_role_catalog
    FOR ALL USING (EXISTS (SELECT 1 FROM users u WHERE u.id = app_current_user_id() AND u.account_role = 'OPERATOR'))
    WITH CHECK (EXISTS (SELECT 1 FROM users u WHERE u.id = app_current_user_id() AND u.account_role = 'OPERATOR'));
CREATE POLICY role_catalog_releases_operator_policy ON role_catalog_releases
    FOR ALL USING (EXISTS (SELECT 1 FROM users u WHERE u.id = app_current_user_id() AND u.account_role = 'OPERATOR'))
    WITH CHECK (EXISTS (SELECT 1 FROM users u WHERE u.id = app_current_user_id() AND u.account_role = 'OPERATOR'));
GRANT SELECT, INSERT, UPDATE ON approved_role_catalog, role_catalog_releases TO jobiss_app;
REVOKE ALL ON approved_role_catalog, role_catalog_releases FROM PUBLIC;
