CREATE TABLE user_project_task_progress (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_node_id uuid NOT NULL,
    task_key varchar(180) NOT NULL,
    task_order integer NOT NULL CHECK (task_order >= 0),
    necessity varchar(20) NOT NULL CHECK (necessity IN ('REQUIRED', 'RECOMMENDED', 'EXTENSION')),
    title varchar(240) NOT NULL,
    objective text NOT NULL,
    acceptance_criteria jsonb NOT NULL DEFAULT '[]'::jsonb,
    capability_keys jsonb NOT NULL DEFAULT '[]'::jsonb,
    depends_on_task_keys jsonb NOT NULL DEFAULT '[]'::jsonb,
    task_revision_hash varchar(64) NOT NULL,
    progress_state varchar(20) NOT NULL DEFAULT 'NOT_STARTED'
        CHECK (progress_state IN ('NOT_STARTED', 'CLAIMED', 'EVIDENCED', 'VERIFIED')),
    archived_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id),
    UNIQUE (user_id, project_node_id, task_key),
    CONSTRAINT user_project_task_progress_project_owner_fk
        FOREIGN KEY (project_node_id, user_id)
        REFERENCES career_nodes(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT user_project_task_acceptance_check CHECK (jsonb_typeof(acceptance_criteria) = 'array'),
    CONSTRAINT user_project_task_capabilities_check CHECK (jsonb_typeof(capability_keys) = 'array'),
    CONSTRAINT user_project_task_dependencies_check CHECK (jsonb_typeof(depends_on_task_keys) = 'array')
);

CREATE TABLE user_project_task_evidence (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    task_progress_id uuid NOT NULL,
    title varchar(240) NOT NULL,
    evidence_url text NOT NULL,
    description text NOT NULL,
    verification_state varchar(20) NOT NULL DEFAULT 'EVIDENCED'
        CHECK (verification_state IN ('EVIDENCED', 'VERIFIED', 'REJECTED')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id),
    CONSTRAINT user_project_task_evidence_owner_fk
        FOREIGN KEY (task_progress_id, user_id)
        REFERENCES user_project_task_progress(id, user_id)
        ON DELETE CASCADE
);

CREATE INDEX user_project_task_progress_project_idx
    ON user_project_task_progress (user_id, project_node_id, task_order)
    WHERE archived_at IS NULL;
CREATE INDEX user_project_task_evidence_task_idx
    ON user_project_task_evidence (user_id, task_progress_id, created_at DESC);

CREATE TRIGGER user_project_task_progress_touch_updated_at
BEFORE UPDATE ON user_project_task_progress
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
CREATE TRIGGER user_project_task_evidence_touch_updated_at
BEFORE UPDATE ON user_project_task_evidence
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

ALTER TABLE user_project_task_progress ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_project_task_progress FORCE ROW LEVEL SECURITY;
ALTER TABLE user_project_task_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_project_task_evidence FORCE ROW LEVEL SECURITY;

CREATE POLICY user_project_task_progress_owner_policy ON user_project_task_progress
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());
CREATE POLICY user_project_task_evidence_owner_policy ON user_project_task_evidence
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON
    user_project_task_progress,
    user_project_task_evidence
TO jobiss_app;

REVOKE ALL ON user_project_task_progress, user_project_task_evidence FROM PUBLIC;
