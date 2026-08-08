ALTER TABLE ai_usage_hourly
    DROP CONSTRAINT ai_usage_hourly_usage_kind_check,
    ADD CONSTRAINT ai_usage_hourly_usage_kind_check
        CHECK (
            usage_kind IN (
                'CHAT', 'ANALYSIS', 'EVIDENCE', 'CAREER',
                'ASSESSMENT', 'LEARNING'
            )
        );

CREATE TABLE agent_work_products (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id uuid NOT NULL,
    chat_reply_job_id uuid NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal BETWEEN 0 AND 50),
    agent_id varchar(80) NOT NULL,
    product_type varchar(40) NOT NULL CHECK (
        product_type IN (
            'DIAGNOSIS',
            'COMPARISON',
            'INTERVIEW_SET',
            'COVER_LETTER_DRAFT',
            'APPLICATION_PLAN',
            'JOB_RECOMMENDATIONS',
            'PREFERENCES',
            'ROADMAP_VIEW',
            'POSTING_ANALYSIS'
        )
    ),
    title varchar(200) NOT NULL,
    summary text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    reply_sources jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id),
    UNIQUE (chat_reply_job_id, ordinal),
    CONSTRAINT agent_work_product_conversation_owner_fk
        FOREIGN KEY (conversation_id, user_id)
        REFERENCES conversations(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT agent_work_product_job_owner_fk
        FOREIGN KEY (chat_reply_job_id, user_id)
        REFERENCES chat_reply_jobs(id, user_id)
        ON DELETE CASCADE
);

CREATE TABLE user_agent_preferences (
    user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    preferences jsonb NOT NULL DEFAULT '{}'::jsonb,
    source_work_product_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT user_agent_preferences_source_owner_fk
        FOREIGN KEY (source_work_product_id, user_id)
        REFERENCES agent_work_products(id, user_id)
        ON DELETE SET NULL (source_work_product_id)
);

CREATE TABLE agent_workspace_states (
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id uuid NOT NULL,
    state jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, conversation_id),
    CONSTRAINT agent_workspace_state_conversation_owner_fk
        FOREIGN KEY (conversation_id, user_id)
        REFERENCES conversations(id, user_id)
        ON DELETE CASCADE
);

CREATE TABLE interview_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id uuid NOT NULL,
    posting_id uuid,
    source_work_product_id uuid NOT NULL,
    status varchar(24) NOT NULL DEFAULT 'DRAFT'
        CHECK (status IN ('DRAFT', 'IN_PROGRESS', 'COMPLETED', 'ARCHIVED')),
    state jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id),
    UNIQUE (source_work_product_id),
    CONSTRAINT interview_session_conversation_owner_fk
        FOREIGN KEY (conversation_id, user_id)
        REFERENCES conversations(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT interview_session_posting_owner_fk
        FOREIGN KEY (posting_id, user_id)
        REFERENCES job_postings(id, user_id)
        ON DELETE SET NULL (posting_id),
    CONSTRAINT interview_session_product_owner_fk
        FOREIGN KEY (source_work_product_id, user_id)
        REFERENCES agent_work_products(id, user_id)
        ON DELETE CASCADE
);

CREATE TABLE cover_letter_drafts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    posting_id uuid,
    source_work_product_id uuid NOT NULL,
    version integer NOT NULL DEFAULT 1 CHECK (version BETWEEN 1 AND 1000),
    status varchar(24) NOT NULL DEFAULT 'DRAFT'
        CHECK (status IN ('DRAFT', 'SAVED', 'ARCHIVED')),
    title varchar(200) NOT NULL,
    content jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id),
    UNIQUE (source_work_product_id),
    CONSTRAINT cover_letter_posting_owner_fk
        FOREIGN KEY (posting_id, user_id)
        REFERENCES job_postings(id, user_id)
        ON DELETE SET NULL (posting_id),
    CONSTRAINT cover_letter_product_owner_fk
        FOREIGN KEY (source_work_product_id, user_id)
        REFERENCES agent_work_products(id, user_id)
        ON DELETE CASCADE
);

CREATE TABLE application_plans (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    posting_id uuid,
    source_work_product_id uuid NOT NULL,
    detailed_status varchar(80),
    plan jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id),
    UNIQUE (source_work_product_id),
    CONSTRAINT application_plan_posting_owner_fk
        FOREIGN KEY (posting_id, user_id)
        REFERENCES job_postings(id, user_id)
        ON DELETE SET NULL (posting_id),
    CONSTRAINT application_plan_product_owner_fk
        FOREIGN KEY (source_work_product_id, user_id)
        REFERENCES agent_work_products(id, user_id)
        ON DELETE CASCADE
);

CREATE TABLE competency_learning_contents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    competency_id uuid NOT NULL,
    target_posting_id uuid,
    context_fingerprint varchar(64) NOT NULL,
    content jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id),
    UNIQUE (user_id, competency_id, context_fingerprint),
    CONSTRAINT competency_learning_competency_owner_fk
        FOREIGN KEY (competency_id, user_id)
        REFERENCES user_competencies(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT competency_learning_posting_owner_fk
        FOREIGN KEY (target_posting_id, user_id)
        REFERENCES job_postings(id, user_id)
        ON DELETE SET NULL (target_posting_id)
);

CREATE TABLE repository_connections (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider varchar(16) NOT NULL CHECK (provider IN ('GITHUB', 'GITLAB')),
    provider_base_url text NOT NULL,
    external_account_id varchar(200),
    external_account_name varchar(200),
    installation_id varchar(200),
    encrypted_access_token text,
    encrypted_refresh_token text,
    token_expires_at timestamptz,
    scopes jsonb NOT NULL DEFAULT '[]'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    status varchar(20) NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'REAUTH_REQUIRED', 'REVOKED')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id),
    UNIQUE (user_id, provider, provider_base_url)
);

CREATE TABLE repository_oauth_states (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider varchar(16) NOT NULL CHECK (provider IN ('GITHUB', 'GITLAB')),
    state_hash varchar(64) NOT NULL UNIQUE,
    provider_base_url text NOT NULL,
    redirect_uri text NOT NULL,
    expires_at timestamptz NOT NULL,
    consumed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id)
);

CREATE TABLE repository_evidence_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    evidence_id uuid NOT NULL,
    connection_id uuid,
    provider varchar(16) NOT NULL CHECK (provider IN ('GITHUB', 'GITLAB')),
    repository_full_name varchar(400) NOT NULL,
    commit_sha varchar(100) NOT NULL,
    default_branch varchar(200),
    collected_data jsonb NOT NULL,
    collected_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id),
    UNIQUE (evidence_id, commit_sha),
    CONSTRAINT repository_snapshot_evidence_owner_fk
        FOREIGN KEY (evidence_id, user_id)
        REFERENCES evidence(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT repository_snapshot_connection_owner_fk
        FOREIGN KEY (connection_id, user_id)
        REFERENCES repository_connections(id, user_id)
        ON DELETE SET NULL (connection_id)
);

CREATE INDEX agent_work_products_conversation_idx
    ON agent_work_products (user_id, conversation_id, created_at DESC);
CREATE INDEX competency_learning_recent_idx
    ON competency_learning_contents (user_id, competency_id, updated_at DESC);
CREATE INDEX repository_snapshots_evidence_idx
    ON repository_evidence_snapshots (user_id, evidence_id, collected_at DESC);

CREATE TRIGGER user_agent_preferences_touch_updated_at
BEFORE UPDATE ON user_agent_preferences
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
CREATE TRIGGER agent_workspace_states_touch_updated_at
BEFORE UPDATE ON agent_workspace_states
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
CREATE TRIGGER interview_sessions_touch_updated_at
BEFORE UPDATE ON interview_sessions
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
CREATE TRIGGER cover_letter_drafts_touch_updated_at
BEFORE UPDATE ON cover_letter_drafts
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
CREATE TRIGGER application_plans_touch_updated_at
BEFORE UPDATE ON application_plans
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
CREATE TRIGGER competency_learning_touch_updated_at
BEFORE UPDATE ON competency_learning_contents
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
CREATE TRIGGER repository_connections_touch_updated_at
BEFORE UPDATE ON repository_connections
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

ALTER TABLE agent_work_products ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_work_products FORCE ROW LEVEL SECURITY;
ALTER TABLE user_agent_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_agent_preferences FORCE ROW LEVEL SECURITY;
ALTER TABLE agent_workspace_states ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_workspace_states FORCE ROW LEVEL SECURITY;
ALTER TABLE interview_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE interview_sessions FORCE ROW LEVEL SECURITY;
ALTER TABLE cover_letter_drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE cover_letter_drafts FORCE ROW LEVEL SECURITY;
ALTER TABLE application_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE application_plans FORCE ROW LEVEL SECURITY;
ALTER TABLE competency_learning_contents ENABLE ROW LEVEL SECURITY;
ALTER TABLE competency_learning_contents FORCE ROW LEVEL SECURITY;
ALTER TABLE repository_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE repository_connections FORCE ROW LEVEL SECURITY;
ALTER TABLE repository_oauth_states ENABLE ROW LEVEL SECURITY;
ALTER TABLE repository_oauth_states FORCE ROW LEVEL SECURITY;
ALTER TABLE repository_evidence_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE repository_evidence_snapshots FORCE ROW LEVEL SECURITY;

CREATE POLICY agent_work_products_owner_policy ON agent_work_products
    USING (user_id = app_current_user_id()) WITH CHECK (user_id = app_current_user_id());
CREATE POLICY user_agent_preferences_owner_policy ON user_agent_preferences
    USING (user_id = app_current_user_id()) WITH CHECK (user_id = app_current_user_id());
CREATE POLICY agent_workspace_states_owner_policy ON agent_workspace_states
    USING (user_id = app_current_user_id()) WITH CHECK (user_id = app_current_user_id());
CREATE POLICY interview_sessions_owner_policy ON interview_sessions
    USING (user_id = app_current_user_id()) WITH CHECK (user_id = app_current_user_id());
CREATE POLICY cover_letter_drafts_owner_policy ON cover_letter_drafts
    USING (user_id = app_current_user_id()) WITH CHECK (user_id = app_current_user_id());
CREATE POLICY application_plans_owner_policy ON application_plans
    USING (user_id = app_current_user_id()) WITH CHECK (user_id = app_current_user_id());
CREATE POLICY competency_learning_contents_owner_policy ON competency_learning_contents
    USING (user_id = app_current_user_id()) WITH CHECK (user_id = app_current_user_id());
CREATE POLICY repository_connections_owner_policy ON repository_connections
    USING (user_id = app_current_user_id()) WITH CHECK (user_id = app_current_user_id());
CREATE POLICY repository_oauth_states_owner_policy ON repository_oauth_states
    USING (user_id = app_current_user_id()) WITH CHECK (user_id = app_current_user_id());
CREATE POLICY repository_evidence_snapshots_owner_policy ON repository_evidence_snapshots
    USING (user_id = app_current_user_id()) WITH CHECK (user_id = app_current_user_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON
    agent_work_products,
    user_agent_preferences,
    agent_workspace_states,
    interview_sessions,
    cover_letter_drafts,
    application_plans,
    competency_learning_contents,
    repository_connections,
    repository_oauth_states,
    repository_evidence_snapshots
TO jobiss_app;

REVOKE ALL ON
    agent_work_products,
    user_agent_preferences,
    agent_workspace_states,
    interview_sessions,
    cover_letter_drafts,
    application_plans,
    competency_learning_contents,
    repository_connections,
    repository_oauth_states,
    repository_evidence_snapshots
FROM PUBLIC;
