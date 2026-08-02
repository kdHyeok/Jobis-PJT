-- AI calls can legitimately take several minutes. Keep queue leases longer than
-- the AI and backend HTTP timeouts so another worker cannot claim the same job.

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
        SELECT q.analysis_job_id
        FROM analysis_job_queue q
        WHERE
            q.available_at <= now()
            AND (q.locked_until IS NULL OR q.locked_until < now())
            AND q.attempt_count < 3
        ORDER BY q.created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    ),
    claimed AS (
        UPDATE analysis_job_queue q
        SET
            worker_id = p_worker_id,
            locked_until = now() + interval '15 minutes',
            attempt_count = q.attempt_count + 1
        FROM candidate c
        WHERE q.analysis_job_id = c.analysis_job_id
        RETURNING q.analysis_job_id, q.user_id, q.attempt_count
    )
    SELECT c.analysis_job_id, c.user_id, c.attempt_count
    FROM claimed c;
END;
$$;

CREATE OR REPLACE FUNCTION claim_evidence_verification(p_worker_id varchar)
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
        SELECT q.evidence_id
        FROM evidence_verification_queue q
        WHERE
            q.available_at <= now()
            AND (q.locked_until IS NULL OR q.locked_until < now())
            AND q.attempt_count < 3
        ORDER BY q.created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    ),
    claimed AS (
        UPDATE evidence_verification_queue q
        SET
            worker_id = p_worker_id,
            locked_until = now() + interval '15 minutes',
            attempt_count = q.attempt_count + 1
        FROM candidate c
        WHERE q.evidence_id = c.evidence_id
        RETURNING q.evidence_id, q.user_id, q.attempt_count
    )
    SELECT c.evidence_id, c.user_id, c.attempt_count
    FROM claimed c;
END;
$$;

CREATE OR REPLACE FUNCTION claim_chat_reply_job(p_worker_id varchar)
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
        SELECT q.chat_reply_job_id
        FROM chat_reply_job_queue q
        JOIN chat_reply_jobs j ON j.id = q.chat_reply_job_id
        WHERE
            q.available_at <= now()
            AND (q.locked_until IS NULL OR q.locked_until < now())
            AND q.attempt_count < 3
            AND NOT EXISTS (
                SELECT 1
                FROM chat_reply_jobs earlier
                WHERE earlier.conversation_id = j.conversation_id
                  AND earlier.status IN ('QUEUED', 'RUNNING')
                  AND (earlier.created_at, earlier.id) < (j.created_at, j.id)
            )
        ORDER BY q.created_at, q.chat_reply_job_id
        FOR UPDATE OF q SKIP LOCKED
        LIMIT 1
    ),
    claimed AS (
        UPDATE chat_reply_job_queue q
        SET
            worker_id = p_worker_id,
            locked_until = now() + interval '15 minutes',
            attempt_count = q.attempt_count + 1
        FROM candidate c
        WHERE q.chat_reply_job_id = c.chat_reply_job_id
        RETURNING q.chat_reply_job_id, q.user_id, q.attempt_count
    )
    SELECT c.chat_reply_job_id, c.user_id, c.attempt_count
    FROM claimed c;
END;
$$;

CREATE OR REPLACE FUNCTION claim_career_source(p_worker_id varchar)
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
        SELECT q.career_source_id
        FROM career_source_queue q
        WHERE
            q.available_at <= now()
            AND (q.locked_until IS NULL OR q.locked_until < now())
            AND q.attempt_count < 3
        ORDER BY q.created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    ),
    claimed AS (
        UPDATE career_source_queue q
        SET
            worker_id = p_worker_id,
            locked_until = now() + interval '15 minutes',
            attempt_count = q.attempt_count + 1
        FROM candidate c
        WHERE q.career_source_id = c.career_source_id
        RETURNING q.career_source_id, q.user_id, q.attempt_count
    )
    SELECT c.career_source_id, c.user_id, c.attempt_count
    FROM claimed c;
END;
$$;

REVOKE ALL ON FUNCTION claim_analysis_job(varchar) FROM PUBLIC;
REVOKE ALL ON FUNCTION claim_evidence_verification(varchar) FROM PUBLIC;
REVOKE ALL ON FUNCTION claim_chat_reply_job(varchar) FROM PUBLIC;
REVOKE ALL ON FUNCTION claim_career_source(varchar) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION claim_analysis_job(varchar) TO jobiss_app;
GRANT EXECUTE ON FUNCTION claim_evidence_verification(varchar) TO jobiss_app;
GRANT EXECUTE ON FUNCTION claim_chat_reply_job(varchar) TO jobiss_app;
GRANT EXECUTE ON FUNCTION claim_career_source(varchar) TO jobiss_app;
