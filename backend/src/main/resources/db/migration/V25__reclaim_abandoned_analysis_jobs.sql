-- 좀비 분석 작업을 회수한다.
--
-- V16 의 회수 조건은 `job.status = 'QUEUED'` 하나였다. 워커(또는 서버)가 실행 도중 죽으면
-- 작업은 'RUNNING' 인 채로 남고 락(`locked_until`)이 만료돼도 **아무도 다시 집지 않는다.**
-- 게다가 `JobPostingService.findActiveAnalysis` 는 'RUNNING' 을 "진행 중"으로 보고 새 요청을
-- 그 좀비에 붙여서, 같은 공고로 재시도하면 영원히 "분석 중"이 된다(실측 08-04: 좀비 5건,
-- 새 공고로 우회해야 지도가 그려졌다).
--
-- 두 가지를 한다.
--   ① 락이 만료된 'RUNNING' 도 회수 대상에 넣는다 — 재시도 상한(attempt_count < 3)은 그대로다.
--   ② 상한까지 쓴 좀비는 'FAILED' 로 닫는다. 아니면 재시도도 회수도 못 하는 채로 화면에
--      "분석 중"으로 영원히 남는다 — 실패를 실패라고 말하는 편이 정직하다(§2-6).

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
    -- ② 재시도 상한까지 쓴 좀비를 닫는다. 폴링마다 돌지만 대상은 만료된 RUNNING 뿐이다.
    UPDATE analysis_jobs job
    SET
        status = 'FAILED',
        stage = 'FAILED',
        locked_until = NULL,
        error_code = coalesce(job.error_code, 'ABANDONED'),
        error_message = coalesce(
            nullif(job.error_message, ''),
            '분석이 중단돼 다시 시도하지 못했어요. 공고를 다시 분석해 주세요.'
        ),
        updated_at = now()
    FROM analysis_job_queue queue
    WHERE queue.analysis_job_id = job.id
      AND job.status = 'RUNNING'
      AND (job.locked_until IS NULL OR job.locked_until < now())
      AND queue.attempt_count >= 3;

    RETURN QUERY
    WITH candidate AS (
        SELECT queue.analysis_job_id
        FROM analysis_job_queue queue
        JOIN analysis_jobs job
          ON job.id = queue.analysis_job_id
        WHERE
            -- ① 버려진 RUNNING 도 집는다. 살아 있는 워커의 작업은 자기 락(job.locked_until,
            -- 15분)이 아직 유효해서 여기 걸리지 않는다.
            (
                job.status = 'QUEUED'
                OR (
                    job.status = 'RUNNING'
                    AND (job.locked_until IS NULL OR job.locked_until < now())
                )
            )
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
