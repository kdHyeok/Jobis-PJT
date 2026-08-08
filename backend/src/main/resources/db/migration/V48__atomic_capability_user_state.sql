-- User progress is tracked against approved atomic capability graph nodes.
-- Legacy broad competencies are retained as evidence and may only become
-- migration candidates; they never verify an atomic node automatically.

CREATE TABLE user_atomic_capabilities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    canonical_key varchar(180) NOT NULL,
    graph_version varchar(64) NOT NULL,
    graph_node_version integer NOT NULL CHECK (graph_node_version >= 1),
    technology_key varchar(180) NOT NULL,
    title varchar(200) NOT NULL,
    scope_definition text NOT NULL,
    verification_methods jsonb NOT NULL DEFAULT '[]'::jsonb,
    progress_state varchar(20) NOT NULL DEFAULT 'NOT_STARTED'
        CHECK (progress_state IN ('NOT_STARTED', 'CLAIMED', 'EVIDENCED', 'VERIFIED')),
    verified_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id),
    UNIQUE (user_id, canonical_key),
    CONSTRAINT user_atomic_capabilities_verification_methods_check
        CHECK (jsonb_typeof(verification_methods) = 'array'),
    CONSTRAINT user_atomic_capabilities_verified_at_check
        CHECK (progress_state = 'VERIFIED' OR verified_at IS NULL)
);

CREATE TABLE user_atomic_capability_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    atomic_capability_id uuid NOT NULL,
    from_state varchar(20),
    to_state varchar(20) NOT NULL,
    event_type varchar(40) NOT NULL
        CHECK (event_type IN (
            'ROADMAP_REGISTERED',
            'MIGRATION_REVIEW',
            'USER_CLAIM',
            'EVIDENCE_SUBMITTED',
            'ASSESSMENT',
            'OPERATOR_REVIEW',
            'RESET'
        )),
    source_ref text,
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id),
    CONSTRAINT user_atomic_capability_events_owner_fk
        FOREIGN KEY (atomic_capability_id, user_id)
        REFERENCES user_atomic_capabilities(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT user_atomic_capability_events_from_state_check
        CHECK (from_state IS NULL OR from_state IN ('NOT_STARTED', 'CLAIMED', 'EVIDENCED', 'VERIFIED')),
    CONSTRAINT user_atomic_capability_events_to_state_check
        CHECK (to_state IN ('NOT_STARTED', 'CLAIMED', 'EVIDENCED', 'VERIFIED')),
    CONSTRAINT user_atomic_capability_events_evidence_check
        CHECK (jsonb_typeof(evidence) = 'object')
);

CREATE TABLE user_atomic_migration_candidates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    legacy_competency_id uuid NOT NULL,
    atomic_capability_id uuid NOT NULL,
    technology_key varchar(180) NOT NULL,
    status varchar(24) NOT NULL DEFAULT 'PENDING_REVIEW'
        CHECK (status IN ('PENDING_REVIEW', 'CONFIRMED', 'REJECTED', 'SUPERSEDED')),
    legacy_progress_status varchar(40) NOT NULL,
    legacy_verified_level integer NOT NULL CHECK (legacy_verified_level BETWEEN 0 AND 5),
    confidence numeric(4,3) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    reason text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    decided_at timestamptz,
    UNIQUE (id, user_id),
    UNIQUE (user_id, legacy_competency_id, atomic_capability_id),
    CONSTRAINT user_atomic_migration_legacy_owner_fk
        FOREIGN KEY (legacy_competency_id, user_id)
        REFERENCES user_competencies(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT user_atomic_migration_atomic_owner_fk
        FOREIGN KEY (atomic_capability_id, user_id)
        REFERENCES user_atomic_capabilities(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT user_atomic_migration_decision_check
        CHECK (
            (status = 'PENDING_REVIEW' AND decided_at IS NULL)
            OR (status <> 'PENDING_REVIEW' AND decided_at IS NOT NULL)
        )
);

CREATE INDEX user_atomic_capabilities_state_idx
    ON user_atomic_capabilities (user_id, progress_state, technology_key);
CREATE INDEX user_atomic_capability_events_capability_idx
    ON user_atomic_capability_events (user_id, atomic_capability_id, created_at DESC);
CREATE INDEX user_atomic_migration_pending_idx
    ON user_atomic_migration_candidates (user_id, created_at)
    WHERE status = 'PENDING_REVIEW';

CREATE TRIGGER user_atomic_capabilities_touch_updated_at
BEFORE UPDATE ON user_atomic_capabilities
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

ALTER TABLE user_atomic_capabilities ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_atomic_capabilities FORCE ROW LEVEL SECURITY;
ALTER TABLE user_atomic_capability_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_atomic_capability_events FORCE ROW LEVEL SECURITY;
ALTER TABLE user_atomic_migration_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_atomic_migration_candidates FORCE ROW LEVEL SECURITY;

CREATE POLICY user_atomic_capabilities_owner_policy ON user_atomic_capabilities
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());
CREATE POLICY user_atomic_capability_events_owner_policy ON user_atomic_capability_events
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());
CREATE POLICY user_atomic_migration_candidates_owner_policy ON user_atomic_migration_candidates
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());

CREATE POLICY user_atomic_capabilities_operator_policy ON user_atomic_capabilities
    USING (EXISTS (
        SELECT 1 FROM users current_user_record
        WHERE current_user_record.id = app_current_user_id()
          AND current_user_record.account_role = 'OPERATOR'
    ))
    WITH CHECK (EXISTS (
        SELECT 1 FROM users current_user_record
        WHERE current_user_record.id = app_current_user_id()
          AND current_user_record.account_role = 'OPERATOR'
    ));
CREATE POLICY user_atomic_capability_events_operator_policy ON user_atomic_capability_events
    USING (EXISTS (
        SELECT 1 FROM users current_user_record
        WHERE current_user_record.id = app_current_user_id()
          AND current_user_record.account_role = 'OPERATOR'
    ))
    WITH CHECK (EXISTS (
        SELECT 1 FROM users current_user_record
        WHERE current_user_record.id = app_current_user_id()
          AND current_user_record.account_role = 'OPERATOR'
    ));
CREATE POLICY user_atomic_migration_candidates_operator_policy ON user_atomic_migration_candidates
    USING (EXISTS (
        SELECT 1 FROM users current_user_record
        WHERE current_user_record.id = app_current_user_id()
          AND current_user_record.account_role = 'OPERATOR'
    ))
    WITH CHECK (EXISTS (
        SELECT 1 FROM users current_user_record
        WHERE current_user_record.id = app_current_user_id()
          AND current_user_record.account_role = 'OPERATOR'
    ));

GRANT SELECT, INSERT, UPDATE, DELETE ON
    user_atomic_capabilities,
    user_atomic_capability_events,
    user_atomic_migration_candidates
TO jobiss_app;

REVOKE ALL ON
    user_atomic_capabilities,
    user_atomic_capability_events,
    user_atomic_migration_candidates
FROM PUBLIC;
