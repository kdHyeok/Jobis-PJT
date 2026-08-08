ALTER TABLE competency_assessment_sessions
    ADD COLUMN source_node_id uuid;

UPDATE competency_assessment_sessions session
SET source_node_id = (
    SELECT node.id AS node_id
    FROM user_competencies competency
    JOIN career_nodes node
      ON node.user_id = competency.user_id
     AND node.canonical_key = competency.canonical_key
    WHERE competency.id = session.competency_id
      AND node.level = session.required_level
    ORDER BY node.archived_at NULLS FIRST, node.updated_at DESC
    LIMIT 1
)
WHERE session.source_node_id IS NULL;

ALTER TABLE competency_assessment_sessions
    ADD CONSTRAINT competency_assessment_source_node_owner_fk
        FOREIGN KEY (source_node_id, user_id)
        REFERENCES career_nodes(id, user_id)
        ON DELETE SET NULL (source_node_id);

CREATE INDEX competency_assessment_source_node_recent_idx
    ON competency_assessment_sessions (user_id, source_node_id, created_at DESC);
