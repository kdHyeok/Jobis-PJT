CREATE OR REPLACE FUNCTION requeue_chat_reply_job(
    p_chat_reply_job_id uuid,
    p_user_id uuid,
    p_delay_seconds integer
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    IF p_user_id IS DISTINCT FROM app_current_user_id() THEN
        RAISE EXCEPTION 'chat reply job owner mismatch';
    END IF;

    UPDATE chat_reply_job_queue
    SET
        available_at = now() + make_interval(secs => greatest(p_delay_seconds, 0)),
        locked_until = NULL,
        worker_id = NULL
    WHERE chat_reply_job_id = p_chat_reply_job_id
      AND user_id = p_user_id;
END;
$$;

REVOKE ALL ON FUNCTION requeue_chat_reply_job(uuid, uuid, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION requeue_chat_reply_job(uuid, uuid, integer) TO jobiss_app;
