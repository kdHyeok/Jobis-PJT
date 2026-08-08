ALTER TABLE ai_v3_source_documents
    DROP CONSTRAINT ai_v3_source_documents_source_document_id_key;
ALTER TABLE ai_v3_source_documents
    ADD CONSTRAINT ai_v3_source_document_owner_contract_key
    UNIQUE (user_id, source_document_id);

ALTER TABLE ai_v3_verified_posting_snapshots
    DROP CONSTRAINT ai_v3_verified_posting_snapshots_verified_snapshot_id_key;
ALTER TABLE ai_v3_verified_posting_snapshots
    ADD CONSTRAINT ai_v3_verified_snapshot_owner_contract_key
    UNIQUE (user_id, verified_snapshot_id);

ALTER TABLE ai_v3_roadmap_proposals
    DROP CONSTRAINT ai_v3_roadmap_proposals_proposal_id_key;
ALTER TABLE ai_v3_roadmap_proposals
    ADD CONSTRAINT ai_v3_roadmap_proposal_owner_contract_key
    UNIQUE (user_id, proposal_id);
