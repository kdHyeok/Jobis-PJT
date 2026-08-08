CREATE TABLE ai_v3_roadmap_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    proposal_id uuid,
    version_number bigint NOT NULL,
    status varchar(20) NOT NULL,
    snapshot jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    UNIQUE (id, user_id),
    UNIQUE (user_id, version_number),
    CONSTRAINT ai_v3_roadmap_version_proposal_owner_fk
        FOREIGN KEY (proposal_id, user_id)
        REFERENCES ai_v3_roadmap_proposals(id, user_id)
        ON DELETE SET NULL (proposal_id),
    CONSTRAINT ai_v3_roadmap_version_status_check
        CHECK (status IN ('PUBLISHED', 'SUPERSEDED')),
    CONSTRAINT ai_v3_roadmap_version_number_check
        CHECK (version_number >= 1),
    CONSTRAINT ai_v3_roadmap_version_snapshot_check
        CHECK (jsonb_typeof(snapshot) = 'object')
);

CREATE UNIQUE INDEX ai_v3_roadmap_one_published_idx
    ON ai_v3_roadmap_versions (user_id)
    WHERE status = 'PUBLISHED';

ALTER TABLE ai_v3_roadmap_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_v3_roadmap_versions FORCE ROW LEVEL SECURITY;

CREATE POLICY ai_v3_roadmap_versions_owner_policy ON ai_v3_roadmap_versions
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON ai_v3_roadmap_versions TO jobiss_app;
REVOKE ALL ON ai_v3_roadmap_versions FROM PUBLIC;
