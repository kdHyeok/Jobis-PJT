CREATE TABLE user_competencies (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    catalog_competency_id uuid REFERENCES competency_catalog(id),
    canonical_key varchar(160) NOT NULL,
    title varchar(160) NOT NULL,
    competency_kind varchar(40) NOT NULL,
    domain varchar(40) NOT NULL,
    default_stage varchar(40) NOT NULL,
    scope_definition text NOT NULL,
    progress_status progress_status NOT NULL DEFAULT 'NOT_STARTED',
    verified_level integer NOT NULL DEFAULT 0 CHECK (verified_level BETWEEN 0 AND 5),
    completion_method varchar(40),
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id),
    UNIQUE (user_id, canonical_key)
);

CREATE TABLE posting_competency_requirements (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    posting_id uuid NOT NULL,
    analysis_job_id uuid NOT NULL,
    competency_id uuid NOT NULL,
    relation_kind varchar(24) NOT NULL
        CHECK (relation_kind IN ('REQUIRED', 'PREFERRED', 'RESPONSIBILITY')),
    required_scope text NOT NULL,
    required_level integer NOT NULL CHECK (required_level BETWEEN 1 AND 5),
    source_text text NOT NULL,
    confidence numeric(4,3) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id),
    UNIQUE (posting_id, competency_id, relation_kind),
    CONSTRAINT posting_competency_posting_owner_fk
        FOREIGN KEY (posting_id, user_id)
        REFERENCES job_postings(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT posting_competency_analysis_owner_fk
        FOREIGN KEY (analysis_job_id, user_id)
        REFERENCES analysis_jobs(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT posting_competency_owner_fk
        FOREIGN KEY (competency_id, user_id)
        REFERENCES user_competencies(id, user_id)
        ON DELETE CASCADE
);

CREATE TABLE posting_target_projects (
    posting_id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    analysis_job_id uuid NOT NULL,
    title varchar(200) NOT NULL,
    objective text NOT NULL,
    domain_context text NOT NULL,
    required_competency_keys jsonb NOT NULL DEFAULT '[]'::jsonb,
    optional_competency_keys jsonb NOT NULL DEFAULT '[]'::jsonb,
    deliverables jsonb NOT NULL DEFAULT '[]'::jsonb,
    acceptance_criteria jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (posting_id, user_id),
    CONSTRAINT posting_target_project_posting_owner_fk
        FOREIGN KEY (posting_id, user_id)
        REFERENCES job_postings(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT posting_target_project_analysis_owner_fk
        FOREIGN KEY (analysis_job_id, user_id)
        REFERENCES analysis_jobs(id, user_id)
        ON DELETE CASCADE
);

CREATE TABLE roadmap_targets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    posting_id uuid NOT NULL,
    analysis_job_id uuid NOT NULL,
    active boolean NOT NULL DEFAULT true,
    added_at timestamptz NOT NULL DEFAULT now(),
    removed_at timestamptz,
    UNIQUE (id, user_id),
    UNIQUE (user_id, posting_id),
    CONSTRAINT roadmap_target_posting_owner_fk
        FOREIGN KEY (posting_id, user_id)
        REFERENCES job_postings(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT roadmap_target_analysis_owner_fk
        FOREIGN KEY (analysis_job_id, user_id)
        REFERENCES analysis_jobs(id, user_id)
        ON DELETE CASCADE
);

CREATE TABLE roadmap_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    version_number bigint NOT NULL,
    status varchar(20) NOT NULL
        CHECK (status IN ('DRAFT', 'PUBLISHED', 'SUPERSEDED', 'DISCARDED')),
    base_version_number bigint,
    target_signature varchar(128) NOT NULL,
    snapshot jsonb NOT NULL,
    change_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    UNIQUE (id, user_id),
    UNIQUE (user_id, version_number)
);

CREATE UNIQUE INDEX roadmap_versions_one_draft_idx
    ON roadmap_versions (user_id)
    WHERE status = 'DRAFT';

CREATE UNIQUE INDEX roadmap_versions_one_published_idx
    ON roadmap_versions (user_id)
    WHERE status = 'PUBLISHED';

CREATE INDEX posting_competency_posting_idx
    ON posting_competency_requirements (posting_id, relation_kind);
CREATE INDEX roadmap_targets_user_active_idx
    ON roadmap_targets (user_id, added_at)
    WHERE active;
CREATE INDEX user_competencies_user_stage_idx
    ON user_competencies (user_id, default_stage, canonical_key);

CREATE TRIGGER user_competencies_touch_updated_at
BEFORE UPDATE ON user_competencies
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

CREATE TRIGGER posting_target_projects_touch_updated_at
BEFORE UPDATE ON posting_target_projects
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

INSERT INTO user_competencies (
    user_id,
    catalog_competency_id,
    canonical_key,
    title,
    competency_kind,
    domain,
    default_stage,
    scope_definition,
    progress_status,
    verified_level,
    completion_method,
    completed_at
)
SELECT DISTINCT ON (n.user_id, n.canonical_key)
    n.user_id,
    n.competency_id,
    n.canonical_key,
    n.title,
    CASE
        WHEN n.kind = 'FOUNDATION' THEN 'KNOWLEDGE'
        WHEN n.kind = 'CREDENTIAL' THEN 'CREDENTIAL'
        WHEN n.kind = 'EXPERIENCE' THEN 'EXPERIENCE'
        ELSE 'TECHNOLOGY'
    END,
    n.domain,
    CASE
        WHEN n.kind = 'FOUNDATION' THEN 'FOUNDATION'
        ELSE 'FRAMEWORK'
    END,
    coalesce(n.scope_definition, n.title),
    coalesce(p.status, 'NOT_STARTED'::progress_status),
    CASE WHEN p.status = 'COMPLETED' THEN n.level ELSE 0 END,
    p.completion_method,
    p.completed_at
FROM career_nodes n
LEFT JOIN node_progress p ON p.node_id = n.id
WHERE n.kind NOT IN ('OPPORTUNITY', 'OPPORTUNITY_CLUSTER', 'PROJECT')
ORDER BY n.user_id, n.canonical_key, n.updated_at DESC
ON CONFLICT (user_id, canonical_key) DO NOTHING;

ALTER TABLE user_competencies ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_competencies FORCE ROW LEVEL SECURITY;
ALTER TABLE posting_competency_requirements ENABLE ROW LEVEL SECURITY;
ALTER TABLE posting_competency_requirements FORCE ROW LEVEL SECURITY;
ALTER TABLE posting_target_projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE posting_target_projects FORCE ROW LEVEL SECURITY;
ALTER TABLE roadmap_targets ENABLE ROW LEVEL SECURITY;
ALTER TABLE roadmap_targets FORCE ROW LEVEL SECURITY;
ALTER TABLE roadmap_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE roadmap_versions FORCE ROW LEVEL SECURITY;

CREATE POLICY user_competencies_owner_policy ON user_competencies
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());
CREATE POLICY posting_competency_requirements_owner_policy ON posting_competency_requirements
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());
CREATE POLICY posting_target_projects_owner_policy ON posting_target_projects
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());
CREATE POLICY roadmap_targets_owner_policy ON roadmap_targets
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());
CREATE POLICY roadmap_versions_owner_policy ON roadmap_versions
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON
    user_competencies,
    posting_competency_requirements,
    posting_target_projects,
    roadmap_targets,
    roadmap_versions
TO jobiss_app;

REVOKE ALL ON
    user_competencies,
    posting_competency_requirements,
    posting_target_projects,
    roadmap_targets,
    roadmap_versions
FROM PUBLIC;
