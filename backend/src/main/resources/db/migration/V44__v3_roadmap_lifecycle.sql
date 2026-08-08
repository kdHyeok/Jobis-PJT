ALTER TABLE ai_v3_roadmap_proposals
    ALTER COLUMN analysis_job_id DROP NOT NULL;

ALTER TABLE ai_v3_roadmap_proposals
    ADD COLUMN proposal_kind varchar(24) NOT NULL DEFAULT 'ANALYSIS',
    ADD CONSTRAINT ai_v3_proposal_kind_check
        CHECK (proposal_kind IN ('ANALYSIS', 'REMOVE_TARGET', 'RESET_TARGETS'));

CREATE INDEX ai_v3_proposals_user_kind_status_idx
    ON ai_v3_roadmap_proposals (user_id, proposal_kind, status, created_at DESC);
