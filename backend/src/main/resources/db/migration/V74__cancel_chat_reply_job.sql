-- The queue table intentionally is not exposed to jobiss_app. Cancellation must
-- update the user-owned job and remove its internal queue row through one
-- ownership-checking SECURITY DEFINER function.
CREATE OR REPLACE FUNCTION cancel_chat_reply_job(
    p_chat_reply_job_id uuid,
    p_user_id uuid
)
RETURNS varchar
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    previous_status varchar(24);
BEGIN
    IF p_user_id IS DISTINCT FROM app_current_user_id() THEN
        RAISE EXCEPTION 'chat reply job owner mismatch';
    END IF;

    SELECT status
    INTO previous_status
    FROM chat_reply_jobs
    WHERE id = p_chat_reply_job_id
      AND user_id = p_user_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    -- Repeated cancellation and a completion race are safe no-ops. The caller
    -- uses the returned previous state to decide whether the AI signal is useful.
    IF previous_status NOT IN ('QUEUED', 'RUNNING') THEN
        RETURN previous_status;
    END IF;

    UPDATE chat_reply_jobs
    SET
        status = 'CANCELLED',
        stage = 'CANCELLED',
        stage_message = '응답 생성을 중지했어요.',
        worker_id = NULL,
        locked_until = NULL,
        error_code = NULL,
        error_message = NULL,
        completed_at = now()
    WHERE id = p_chat_reply_job_id
      AND user_id = p_user_id;

    DELETE FROM chat_reply_job_queue
    WHERE chat_reply_job_id = p_chat_reply_job_id
      AND user_id = p_user_id;

    RETURN previous_status;
END;
$$;

REVOKE ALL ON FUNCTION cancel_chat_reply_job(uuid, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION cancel_chat_reply_job(uuid, uuid) TO jobiss_app;
