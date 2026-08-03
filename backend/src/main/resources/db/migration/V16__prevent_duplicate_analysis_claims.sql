-- Keep only the first unanswered clarification if an older worker race created
-- more than one pending question for the same analysis.
WITH ranked_pending AS (
    SELECT
        id,
        row_number() OVER (
            PARTITION BY analysis_job_id
            ORDER BY ordinal, created_at, id
        ) AS pending_rank
    FROM analysis_questions
    WHERE status = 'PENDING'
)
DELETE FROM analysis_questions question
USING ranked_pending duplicate
WHERE question.id = duplicate.id
  AND duplicate.pending_rank > 1;

UPDATE analysis_jobs job
SET question_count = (
    SELECT count(*)::integer
    FROM analysis_questions question
    WHERE question.analysis_job_id = job.id
)
WHERE question_count <> (
    SELECT count(*)::integer
    FROM analysis_questions question
    WHERE question.analysis_job_id = job.id
);

UPDATE analysis_jobs job
SET
    status = 'WAITING_FOR_INPUT',
    stage = 'WAITING_FOR_INPUT',
    stage_message = (
        SELECT question.question_text
        FROM analysis_questions question
        WHERE question.analysis_job_id = job.id
          AND question.status = 'PENDING'
        ORDER BY question.ordinal
        LIMIT 1
    ),
    worker_id = NULL,
    locked_until = NULL,
    error_code = NULL,
    error_message = NULL,
    completed_at = NULL
WHERE job.status IN ('FAILED', 'WAITING_FOR_INPUT')
  AND EXISTS (
      SELECT 1
      FROM analysis_questions question
      WHERE question.analysis_job_id = job.id
        AND question.status = 'PENDING'
  );

DELETE FROM analysis_job_queue queue
USING analysis_jobs job
WHERE job.id = queue.analysis_job_id
  AND job.status <> 'QUEUED';

CREATE UNIQUE INDEX analysis_questions_one_pending_per_job_idx
    ON analysis_questions (analysis_job_id)
    WHERE status = 'PENDING';

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
    WITH candidate AS (
        SELECT queue.analysis_job_id
        FROM analysis_job_queue queue
        JOIN analysis_jobs job
          ON job.id = queue.analysis_job_id
        WHERE
            job.status = 'QUEUED'
            AND queue.available_at <= now()
            AND (
                queue.locked_until IS NULL
                OR queue.locked_until < now()
            )
            AND queue.attempt_count < 3
        ORDER BY queue.created_at
        FOR UPDATE OF queue SKIP LOCKED
        LIMIT 1
    ),
    claimed AS (
        UPDATE analysis_job_queue queue
        SET
            worker_id = p_worker_id,
            locked_until = now() + interval '15 minutes',
            attempt_count = queue.attempt_count + 1
        FROM candidate
        WHERE queue.analysis_job_id = candidate.analysis_job_id
        RETURNING
            queue.analysis_job_id,
            queue.user_id,
            queue.attempt_count
    )
    SELECT
        claimed.analysis_job_id,
        claimed.user_id,
        claimed.attempt_count
    FROM claimed;
END;
$$;

REVOKE ALL ON FUNCTION claim_analysis_job(varchar) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION claim_analysis_job(varchar) TO jobiss_app;
