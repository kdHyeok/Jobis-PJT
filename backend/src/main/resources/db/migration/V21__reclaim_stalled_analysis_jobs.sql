-- 락이 만료된 RUNNING 분석 작업을 회수한다.
--
-- claim_analysis_job 은 `job.status = 'QUEUED'` 인 것만 집었다. 워커가 실행 중에 죽으면
-- (배포·재시작·프로세스 종료) 그 작업은 RUNNING 으로 남고, 큐 행의 15분 락이 만료된 뒤에도
-- 아무도 다시 집지 않는다 — 사용자에게는 진행 휠이 영원히 도는 것으로 보인다.
-- 실측(2026-08-03): 15:20 이후 멈춘 작업 1건. AI 쪽은 판정과 로드맵까지 이미 냈는데
-- 저장이 되지 않아 커리어지도가 비었다.
--
-- 큐 행의 존재 자체가 "아직 안 끝났다"는 뜻이다 — finish_analysis_job 이 완료·실패 시 큐 행을
-- 지운다. 그래서 상태 조건은 필요하지 않고, 이미 같은 저장소의 claim_chat_reply_job 이
-- 그렇게 되어 있다(대화 답변 작업은 이 문제가 없던 이유다). 두 함수를 같은 규칙으로 맞춘다.
--
-- 재실행은 안전하다: loadRequest 가 stage 를 되돌리고 analysis_agent_events 를 지운 뒤
-- 다시 시작하며, attempt_count < 3 상한은 그대로다.

CREATE OR REPLACE FUNCTION claim_analysis_job(p_worker_id character varying)
RETURNS TABLE(id uuid, user_id uuid, attempt_count integer)
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
            queue.available_at <= now()
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
