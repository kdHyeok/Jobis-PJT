-- 채팅 답변은 분석 작업과 달리 사용자가 작성 중 즉시 중지할 수 있어야 한다.
-- 공용 enum(analysis_job_status)을 늘리면 다른 작업 상태 계약까지 불필요하게 넓어지므로
-- chat_reply_jobs 한 열만 varchar 계약으로 분리한다.
ALTER TABLE chat_reply_jobs
    ALTER COLUMN status DROP DEFAULT;

ALTER TABLE chat_reply_jobs
    ALTER COLUMN status TYPE varchar(24) USING status::text;

ALTER TABLE chat_reply_jobs
    ALTER COLUMN status SET DEFAULT 'QUEUED';

ALTER TABLE chat_reply_jobs
    ADD CONSTRAINT chat_reply_jobs_status_check
        CHECK (status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED'));

-- 최종 메시지가 저장되기 전에도 토큰 델타를 화면에 보여 주는 임시 초안이다.
-- 최종 답변의 진실의 출처는 계속 conversation_messages 이다.
ALTER TABLE chat_reply_jobs
    ADD COLUMN draft_text text NOT NULL DEFAULT '';

-- 취소된 큐 행을 워커가 집어 가지 않도록 작업 상태까지 함께 확인한다.
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
    -- V28 이 도입한 워커 컨텍스트를 그대로 유지한다. 이 함수는 SECURITY DEFINER 지만
    -- chat_reply_jobs 에 FORCE ROW LEVEL SECURITY 가 걸려 있어, 워커 컨텍스트를 켜지
    -- 않으면 조인 결과가 항상 0건이 되어 큐를 집지 못한다.
    PERFORM set_config('app.worker_context', 'on', true);

    RETURN QUERY
    WITH candidate AS (
        SELECT q.chat_reply_job_id
        FROM chat_reply_job_queue q
        JOIN chat_reply_jobs j ON j.id = q.chat_reply_job_id
        WHERE
            -- 취소된 작업을 워커가 집어가지 않도록 상태까지 확인한다(V29 에서 추가).
            j.status = 'QUEUED'
            AND q.available_at <= now()
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

    PERFORM set_config('app.worker_context', '', true);
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config('app.worker_context', '', true);
    RAISE;
END;
$$;

REVOKE ALL ON FUNCTION claim_chat_reply_job(varchar) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION claim_chat_reply_job(varchar) TO jobiss_app;
