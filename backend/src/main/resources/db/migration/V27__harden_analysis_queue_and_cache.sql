ALTER TABLE posting_analysis_cache
    ADD COLUMN invalidated_at timestamptz,
    ADD COLUMN invalid_reason text;

CREATE INDEX posting_analysis_cache_valid_lookup_idx
    ON posting_analysis_cache (
        content_fingerprint,
        clarification_fingerprint,
        schema_version
    )
    WHERE invalidated_at IS NULL;

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
            WHERE queued.status = 'QUEUED'
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
        WHERE job.id = p_job_id
          AND job.user_id = p_user_id
    ) current_job
$$;

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
          AND (
              queue.locked_until IS NULL
              OR queue.locked_until < now()
          )
          AND queue.attempt_count < 3
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
        RETURNING
            queue.analysis_job_id,
            queue.user_id,
            queue.attempt_count
    ),
    activated AS (
        UPDATE analysis_jobs job
        SET
            status = 'RUNNING',
            stage = 'CONTEXT',
            stage_message = '공고와 현재 커리어 자료를 정리하고 있어요',
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

CREATE OR REPLACE FUNCTION recover_stale_analysis_jobs()
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    stale_job record;
    recovered_count integer := 0;
    exhausted_count integer := 0;
BEGIN
    FOR stale_job IN
        SELECT job.id, job.user_id, job.attempt_count
        FROM analysis_jobs job
        WHERE job.status = 'RUNNING'
          AND (job.locked_until IS NULL OR job.locked_until < now())
        FOR UPDATE SKIP LOCKED
    LOOP
        DELETE FROM posting_analysis_leases
        WHERE owner_analysis_job_id = stale_job.id;

        IF stale_job.attempt_count < 3 THEN
            UPDATE analysis_jobs
            SET
                status = 'QUEUED',
                stage = 'QUEUED',
                stage_message = '중단된 분석을 다시 시작할 준비를 하고 있어요',
                worker_id = NULL,
                locked_until = NULL,
                error_code = NULL,
                error_message = NULL,
                completed_at = NULL
            WHERE id = stale_job.id;

            INSERT INTO analysis_job_queue (
                analysis_job_id,
                user_id,
                available_at,
                worker_id,
                locked_until,
                attempt_count
            ) VALUES (
                stale_job.id,
                stale_job.user_id,
                now(),
                NULL,
                NULL,
                stale_job.attempt_count
            )
            ON CONFLICT (analysis_job_id) DO UPDATE SET
                user_id = excluded.user_id,
                available_at = excluded.available_at,
                worker_id = NULL,
                locked_until = NULL,
                attempt_count = greatest(
                    analysis_job_queue.attempt_count,
                    excluded.attempt_count
                );
        ELSE
            UPDATE analysis_jobs
            SET
                status = 'FAILED',
                stage = 'FAILED',
                stage_message = '중단된 분석을 자동으로 복구하지 못했어요',
                worker_id = NULL,
                locked_until = NULL,
                error_code = 'ANALYSIS_RETRY_EXHAUSTED',
                error_message = '분석 작업이 반복해서 중단되어 자동 재시도 횟수를 초과했습니다.',
                completed_at = now()
            WHERE id = stale_job.id;

            DELETE FROM analysis_job_queue
            WHERE analysis_job_id = stale_job.id;
        END IF;

        recovered_count := recovered_count + 1;
    END LOOP;

    UPDATE analysis_job_queue queue
    SET worker_id = NULL, locked_until = NULL, available_at = now()
    FROM analysis_jobs job
    WHERE job.id = queue.analysis_job_id
      AND job.status = 'QUEUED'
      AND queue.worker_id IS NOT NULL
      AND queue.attempt_count < 3
      AND queue.locked_until < now();

    WITH exhausted AS (
        SELECT job.id
        FROM analysis_jobs job
        JOIN analysis_job_queue queue
          ON queue.analysis_job_id = job.id
        WHERE job.status = 'QUEUED'
          AND queue.attempt_count >= 3
          AND (queue.locked_until IS NULL OR queue.locked_until < now())
        FOR UPDATE OF job, queue SKIP LOCKED
    ),
    failed AS (
        UPDATE analysis_jobs job
        SET
            status = 'FAILED',
            stage = 'FAILED',
            stage_message = '분석을 자동으로 시작하지 못했어요',
            worker_id = NULL,
            locked_until = NULL,
            error_code = 'ANALYSIS_RETRY_EXHAUSTED',
            error_message = '분석 작업을 시작하는 과정에서 자동 재시도 횟수를 초과했습니다.',
            completed_at = now()
        FROM exhausted
        WHERE job.id = exhausted.id
        RETURNING job.id
    )
    DELETE FROM analysis_job_queue queue
    USING failed
    WHERE queue.analysis_job_id = failed.id;

    GET DIAGNOSTICS exhausted_count = ROW_COUNT;
    RETURN recovered_count + exhausted_count;
END;
$$;

REVOKE ALL ON FUNCTION count_analysis_jobs_ahead(uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION claim_analysis_job(varchar) FROM PUBLIC;
REVOKE ALL ON FUNCTION recover_stale_analysis_jobs() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION count_analysis_jobs_ahead(uuid, uuid) TO jobiss_app;
GRANT EXECUTE ON FUNCTION claim_analysis_job(varchar) TO jobiss_app;
GRANT EXECUTE ON FUNCTION recover_stale_analysis_jobs() TO jobiss_app;
