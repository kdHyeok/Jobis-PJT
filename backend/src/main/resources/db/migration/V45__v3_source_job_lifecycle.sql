ALTER TABLE analysis_jobs
    ADD COLUMN v3_source_id uuid,
    ADD COLUMN v3_snapshot_id uuid;

ALTER TABLE analysis_jobs
    ADD CONSTRAINT analysis_jobs_v3_source_owner_fk
        FOREIGN KEY (v3_source_id, user_id)
        REFERENCES ai_v3_source_documents(id, user_id)
        ON DELETE RESTRICT,
    ADD CONSTRAINT analysis_jobs_v3_snapshot_owner_fk
        FOREIGN KEY (v3_snapshot_id, user_id)
        REFERENCES ai_v3_verified_posting_snapshots(id, user_id)
        ON DELETE RESTRICT,
    ADD CONSTRAINT analysis_jobs_v3_source_pair_check
        CHECK (
            (v3_source_id IS NULL AND v3_snapshot_id IS NULL)
            OR
            (analysis_provider = 'V3' AND v3_source_id IS NOT NULL AND v3_snapshot_id IS NOT NULL)
        );

CREATE UNIQUE INDEX analysis_jobs_v3_snapshot_once_idx
    ON analysis_jobs (user_id, v3_snapshot_id)
    WHERE analysis_provider = 'V3' AND v3_snapshot_id IS NOT NULL;

-- A queue position is the number of genuinely claimable predecessors, not the
-- ordinal of stale/terminal rows that happen to remain in analysis_jobs.
CREATE OR REPLACE FUNCTION count_analysis_jobs_ahead(
    p_job_id uuid,
    p_user_id uuid
)
RETURNS integer
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT CASE
        WHEN current_job.id IS NULL OR current_job.status <> 'QUEUED' THEN NULL
        ELSE (
            SELECT count(*)::integer
            FROM analysis_jobs queued
            JOIN analysis_job_queue queued_queue
              ON queued_queue.analysis_job_id = queued.id
            WHERE queued.status = 'QUEUED'
              AND queued_queue.attempt_count < 3
              AND queued_queue.available_at <= now()
              AND (
                  queued_queue.locked_until IS NULL
                  OR queued_queue.locked_until < now()
              )
              AND (
                  queued.created_at < current_job.created_at
                  OR (
                      queued.created_at = current_job.created_at
                      AND queued.id < current_job.id
                  )
              )
        )
    END
    FROM (
        SELECT job.id, job.status, job.created_at
        FROM analysis_jobs job
        JOIN analysis_job_queue queue
          ON queue.analysis_job_id = job.id
        WHERE job.id = p_job_id
          AND job.user_id = p_user_id
          AND queue.attempt_count < 3
    ) current_job
$$;

REVOKE ALL ON FUNCTION count_analysis_jobs_ahead(uuid, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION count_analysis_jobs_ahead(uuid, uuid) TO jobiss_app;
