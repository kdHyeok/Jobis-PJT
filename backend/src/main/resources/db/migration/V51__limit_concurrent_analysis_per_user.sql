-- Queue work may accumulate, but one user may consume at most two worker slots.
-- The transaction-scoped advisory lock closes the race between multiple worker
-- processes checking the same user's RUNNING count at the same time.
CREATE OR REPLACE FUNCTION claim_analysis_job(p_worker_id varchar)
RETURNS TABLE (
    id uuid,
    user_id uuid,
    attempt_count integer
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    RETURN QUERY
    WITH candidate AS MATERIALIZED (
        SELECT queue.analysis_job_id
        FROM analysis_job_queue queue
        JOIN analysis_jobs job
          ON job.id = queue.analysis_job_id
        WHERE job.status = 'QUEUED'
          AND queue.available_at <= now()
          AND (queue.locked_until IS NULL OR queue.locked_until < now())
          AND queue.attempt_count < 3
          AND (
              SELECT count(*)
              FROM analysis_jobs running
              WHERE running.user_id = job.user_id
                AND running.status = 'RUNNING'
          ) < 2
          AND pg_try_advisory_xact_lock(
              hashtextextended('jobiss-analysis-user:' || job.user_id::text, 0)
          )
        ORDER BY job.created_at, job.id
        FOR UPDATE OF queue, job SKIP LOCKED
        LIMIT 1
    ),
    claimed_queue AS (
        UPDATE analysis_job_queue queue
        SET
            worker_id = p_worker_id,
            locked_until = now() + interval '15 minutes',
            attempt_count = queue.attempt_count + 1
        FROM candidate
        WHERE queue.analysis_job_id = candidate.analysis_job_id
        RETURNING queue.analysis_job_id, queue.user_id, queue.attempt_count
    ),
    activated AS (
        UPDATE analysis_jobs job
        SET
            status = 'RUNNING',
            stage = 'CONTEXT',
            stage_message = '공고와 현재 커리어 자료를 정리하고 있어요.',
            worker_id = p_worker_id,
            locked_until = now() + interval '15 minutes',
            attempt_count = claimed_queue.attempt_count,
            started_at = coalesce(job.started_at, now()),
            completed_at = NULL,
            error_code = NULL,
            error_message = NULL
        FROM claimed_queue
        WHERE job.id = claimed_queue.analysis_job_id
          AND job.status = 'QUEUED'
        RETURNING job.id, job.user_id, job.attempt_count
    )
    SELECT activated.id, activated.user_id, activated.attempt_count
    FROM activated;
END;
$$;

REVOKE ALL ON FUNCTION claim_analysis_job(varchar) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION claim_analysis_job(varchar) TO jobiss_app;
