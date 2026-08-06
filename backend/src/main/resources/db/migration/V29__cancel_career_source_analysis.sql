ALTER TABLE career_sources DROP CONSTRAINT career_sources_status_check;
ALTER TABLE career_sources ADD CONSTRAINT career_sources_status_check
    CHECK (status IN ('QUEUED', 'RUNNING', 'REVIEW_READY', 'CONFIRMED', 'FAILED', 'CANCELLED'));
