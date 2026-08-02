-- Keep assistant replies in the same order as user messages, even when several
-- backend instances are polling the queue concurrently.

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
            locked_until = now() + interval '5 minutes',
            attempt_count = q.attempt_count + 1
        FROM candidate c
        WHERE q.chat_reply_job_id = c.chat_reply_job_id
        RETURNING q.chat_reply_job_id, q.user_id, q.attempt_count
    )
    SELECT c.chat_reply_job_id, c.user_id, c.attempt_count
    FROM claimed c;
END;
$$;

REVOKE ALL ON FUNCTION claim_chat_reply_job(varchar) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION claim_chat_reply_job(varchar) TO jobiss_app;
