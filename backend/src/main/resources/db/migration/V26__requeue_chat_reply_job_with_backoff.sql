-- AI 서버가 잠깐 사라진 턴을 되살린다.
--
-- 실측(08-04 09:20): 대화 도중 AI 서버(8000)가 재시작되자 진행 중이던 답변 작업이
-- "Connection reset" 으로, 뒤이어 큐에 있던 작업이 "Connection refused" 로 각각 한 번에
-- FAILED 로 닫혔다. 큐는 이미 3회 재시도를 허용하는데(`attempt_count < 3`) 워커가
-- 전송 실패까지 최종 실패로 처리해 그 예산을 한 번도 쓰지 않았다. 사용자는 판정이 다 끝난
-- 턴을 잃고 같은 말을 다시 쳐야 했다.
--
-- 기존 2인자 `requeue_chat_reply_job` 은 `available_at = now()` 라 즉시 재시도한다. 사람이
-- 버튼을 눌러 재시도할 때는 그게 맞지만(ChatReplyJobService.retry), 서버가 아직 안 떠 있는
-- 상황에서는 폴링 주기(3초)마다 남은 시도를 순식간에 태워 버린다 — 재시도 예산이 있으나
-- 마나가 된다. 그래서 **지연을 받는 3인자 판**을 더한다. 2인자는 그대로 둔다(기본값을 달면
-- 두 시그니처가 모호해진다).

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

    -- INSERT 하지 않는다. 큐 행이 사라진 뒤 다시 넣으면 attempt_count 가 0 으로 돌아가
    -- 재시도 상한이 없어진다 — 되살릴 것이 없으면 아무것도 하지 않는 편이 옳다.
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
