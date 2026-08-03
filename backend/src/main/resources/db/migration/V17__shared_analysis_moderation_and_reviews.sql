CREATE EXTENSION IF NOT EXISTS pg_trgm;

ALTER TABLE users
    ADD COLUMN account_role varchar(24) NOT NULL DEFAULT 'USER'
        CHECK (account_role IN ('USER', 'OPERATOR'));

ALTER TABLE job_postings
    ADD COLUMN source_platform varchar(80),
    ADD COLUMN source_posting_key varchar(200),
    ADD COLUMN content_fingerprint varchar(64),
    ADD COLUMN canonical_posting_id uuid,
    ADD COLUMN closes_at timestamptz,
    ADD COLUMN lifecycle_status varchar(24) NOT NULL DEFAULT 'ACTIVE'
        CHECK (lifecycle_status IN ('ACTIVE', 'EXPIRED', 'CLOSED', 'UNKNOWN'));

ALTER TABLE job_postings
    ADD CONSTRAINT job_postings_canonical_posting_fk
        FOREIGN KEY (canonical_posting_id)
        REFERENCES posting_catalog(id)
        ON DELETE SET NULL;

UPDATE job_postings
SET content_fingerprint = encode(
    digest(
        lower(regexp_replace(btrim(raw_text), '\s+', ' ', 'g')),
        'sha256'
    ),
    'hex'
)
WHERE content_fingerprint IS NULL;

ALTER TABLE job_postings
    ALTER COLUMN content_fingerprint SET NOT NULL;

CREATE INDEX job_postings_content_fingerprint_idx
    ON job_postings (content_fingerprint);

CREATE INDEX job_postings_source_identity_idx
    ON job_postings (source_platform, source_posting_key)
    WHERE source_platform IS NOT NULL AND source_posting_key IS NOT NULL;

ALTER TABLE posting_catalog
    ADD COLUMN source_platform varchar(80),
    ADD COLUMN source_posting_key varchar(200),
    ADD COLUMN content_fingerprint varchar(64),
    ADD COLUMN closes_at timestamptz,
    ADD COLUMN lifecycle_status varchar(24) NOT NULL DEFAULT 'ACTIVE'
        CHECK (lifecycle_status IN ('ACTIVE', 'EXPIRED', 'CLOSED', 'UNKNOWN')),
    ADD COLUMN moderation_status varchar(24) NOT NULL DEFAULT 'VERIFIED'
        CHECK (moderation_status IN ('VERIFIED', 'REVIEW', 'MERGED', 'HIDDEN'));

UPDATE posting_catalog catalog
SET content_fingerprint = source.content_fingerprint
FROM (
    SELECT DISTINCT ON (canonical_posting_id)
        canonical_posting_id,
        content_fingerprint
    FROM job_postings
    WHERE canonical_posting_id IS NOT NULL
    ORDER BY canonical_posting_id, updated_at DESC
) source
WHERE catalog.id = source.canonical_posting_id
  AND catalog.content_fingerprint IS NULL;

CREATE UNIQUE INDEX posting_catalog_source_identity_uidx
    ON posting_catalog (source_platform, source_posting_key)
    WHERE source_platform IS NOT NULL
      AND source_posting_key IS NOT NULL
      AND moderation_status <> 'MERGED';

CREATE INDEX posting_catalog_content_fingerprint_idx
    ON posting_catalog (content_fingerprint)
    WHERE content_fingerprint IS NOT NULL;

CREATE TABLE posting_analysis_cache (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    content_fingerprint varchar(64) NOT NULL,
    clarification_fingerprint varchar(64) NOT NULL,
    normalized_analysis jsonb NOT NULL,
    schema_version integer NOT NULL DEFAULT 1,
    use_count bigint NOT NULL DEFAULT 0,
    first_created_at timestamptz NOT NULL DEFAULT now(),
    last_used_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (content_fingerprint, clarification_fingerprint),
    CHECK (jsonb_typeof(normalized_analysis) = 'object')
);

CREATE TRIGGER posting_analysis_cache_touch_updated_at
BEFORE UPDATE ON posting_analysis_cache
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

CREATE TABLE posting_catalog_observations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    private_posting_id uuid NOT NULL,
    posting_catalog_id uuid NOT NULL REFERENCES posting_catalog(id),
    observed_url text,
    content_fingerprint varchar(64) NOT NULL,
    first_observed_at timestamptz NOT NULL DEFAULT now(),
    last_observed_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, private_posting_id),
    CONSTRAINT posting_catalog_observation_private_owner_fk
        FOREIGN KEY (private_posting_id, user_id)
        REFERENCES job_postings(id, user_id)
        ON DELETE CASCADE
);

CREATE TABLE posting_duplicate_candidates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    left_posting_id uuid NOT NULL REFERENCES posting_catalog(id),
    right_posting_id uuid NOT NULL REFERENCES posting_catalog(id),
    match_kind varchar(32) NOT NULL
        CHECK (match_kind IN ('PLATFORM_ID', 'URL', 'CONTENT_HASH', 'FUZZY')),
    similarity_score numeric(5,4) NOT NULL CHECK (similarity_score BETWEEN 0 AND 1),
    proposed_action varchar(24) NOT NULL
        CHECK (proposed_action IN ('MERGE', 'SEPARATE', 'REVIEW')),
    proposal_reason text NOT NULL,
    status varchar(24) NOT NULL DEFAULT 'OPEN'
        CHECK (status IN ('OPEN', 'MERGED', 'SEPARATED', 'ON_HOLD')),
    resolved_by uuid REFERENCES users(id),
    resolved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (left_posting_id <> right_posting_id)
);

CREATE UNIQUE INDEX posting_duplicate_pair_uidx
    ON posting_duplicate_candidates (
        least(left_posting_id, right_posting_id),
        greatest(left_posting_id, right_posting_id)
    );

CREATE INDEX posting_duplicate_open_idx
    ON posting_duplicate_candidates (created_at)
    WHERE status = 'OPEN';

CREATE TRIGGER posting_duplicate_candidates_touch_updated_at
BEFORE UPDATE ON posting_duplicate_candidates
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

CREATE TABLE operator_action_audit (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    operator_user_id uuid NOT NULL REFERENCES users(id),
    action_kind varchar(48) NOT NULL,
    target_type varchar(48) NOT NULL,
    target_id uuid NOT NULL,
    before_state jsonb NOT NULL DEFAULT '{}'::jsonb,
    after_state jsonb NOT NULL DEFAULT '{}'::jsonb,
    reason text,
    rolled_back_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE competency_assessment_sessions
    ADD COLUMN review_status varchar(24) NOT NULL DEFAULT 'NONE'
        CHECK (review_status IN ('NONE', 'REQUESTED', 'APPROVED', 'REJECTED')),
    ADD COLUMN appeal_text text,
    ADD COLUMN reviewed_by uuid REFERENCES users(id),
    ADD COLUMN reviewed_at timestamptz;

ALTER TABLE competency_assessment_turns
    ADD COLUMN criterion_scope varchar(24) NOT NULL DEFAULT 'CORE_GATE'
        CHECK (criterion_scope IN ('CORE_GATE', 'FUTURE_EXTENSION')),
    ADD COLUMN core_criteria jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN future_extensions jsonb NOT NULL DEFAULT '[]'::jsonb;

CREATE TABLE assessment_review_actions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id uuid NOT NULL,
    operator_user_id uuid REFERENCES users(id),
    action varchar(24) NOT NULL
        CHECK (action IN ('REQUESTED', 'APPROVED', 'REJECTED', 'ROLLED_BACK')),
    comment text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT assessment_review_session_owner_fk
        FOREIGN KEY (session_id, user_id)
        REFERENCES competency_assessment_sessions(id, user_id)
        ON DELETE CASCADE
);

ALTER TABLE posting_catalog_observations ENABLE ROW LEVEL SECURITY;
ALTER TABLE posting_catalog_observations FORCE ROW LEVEL SECURITY;
ALTER TABLE assessment_review_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE assessment_review_actions FORCE ROW LEVEL SECURITY;

CREATE POLICY posting_catalog_observations_owner_or_operator
ON posting_catalog_observations
    USING (
        user_id = app_current_user_id()
        OR EXISTS (
            SELECT 1
            FROM users current_user_record
            WHERE current_user_record.id = app_current_user_id()
              AND current_user_record.account_role = 'OPERATOR'
        )
    )
    WITH CHECK (
        user_id = app_current_user_id()
        OR EXISTS (
            SELECT 1
            FROM users current_user_record
            WHERE current_user_record.id = app_current_user_id()
              AND current_user_record.account_role = 'OPERATOR'
        )
    );

CREATE POLICY assessment_review_actions_owner_or_operator
ON assessment_review_actions
    USING (
        user_id = app_current_user_id()
        OR EXISTS (
            SELECT 1
            FROM users current_user_record
            WHERE current_user_record.id = app_current_user_id()
              AND current_user_record.account_role = 'OPERATOR'
        )
    )
    WITH CHECK (
        user_id = app_current_user_id()
        OR EXISTS (
            SELECT 1
            FROM users current_user_record
            WHERE current_user_record.id = app_current_user_id()
              AND current_user_record.account_role = 'OPERATOR'
        )
    );

CREATE POLICY competency_assessment_sessions_operator_policy
ON competency_assessment_sessions
    USING (
        EXISTS (
            SELECT 1
            FROM users current_user_record
            WHERE current_user_record.id = app_current_user_id()
              AND current_user_record.account_role = 'OPERATOR'
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1
            FROM users current_user_record
            WHERE current_user_record.id = app_current_user_id()
              AND current_user_record.account_role = 'OPERATOR'
        )
    );

CREATE POLICY competency_assessment_turns_operator_policy
ON competency_assessment_turns
    USING (
        EXISTS (
            SELECT 1
            FROM users current_user_record
            WHERE current_user_record.id = app_current_user_id()
              AND current_user_record.account_role = 'OPERATOR'
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1
            FROM users current_user_record
            WHERE current_user_record.id = app_current_user_id()
              AND current_user_record.account_role = 'OPERATOR'
        )
    );

GRANT SELECT, INSERT, UPDATE ON posting_analysis_cache TO jobiss_app;
GRANT UPDATE (
    source_platform,
    source_posting_key,
    content_fingerprint,
    closes_at,
    lifecycle_status,
    moderation_status,
    active,
    last_seen_at,
    updated_at
) ON posting_catalog TO jobiss_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON posting_catalog_observations TO jobiss_app;
GRANT SELECT, INSERT, UPDATE ON posting_duplicate_candidates TO jobiss_app;
GRANT SELECT, INSERT, UPDATE ON operator_action_audit TO jobiss_app;
GRANT INSERT, UPDATE, DELETE ON posting_catalog_requirements TO jobiss_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON assessment_review_actions TO jobiss_app;

REVOKE ALL ON posting_analysis_cache,
    posting_catalog_observations,
    posting_duplicate_candidates,
    operator_action_audit,
    assessment_review_actions
FROM PUBLIC;
