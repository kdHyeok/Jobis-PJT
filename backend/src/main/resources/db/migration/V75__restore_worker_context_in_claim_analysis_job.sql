-- develop 의 V37·V60 이 claim_analysis_job 을 재정의하면서 두 가지가 사라졌다.
--
-- 1) 워커 컨텍스트: analysis_jobs 는 FORCE ROW LEVEL SECURITY 라서, SECURITY DEFINER
--    함수라도 app.worker_context 를 켜지 않으면 조인 결과가 항상 0건이다(V28 참고).
--    V60 판은 set_config 호출이 없어 워커가 큐를 영원히 집지 못한다.
-- 2) 버려진 RUNNING 회수: 락이 만료된 RUNNING 재청구와 시도 소진 좀비 정리를
--    claim 이 맡는다는 계약(V25→V28) 위에 백엔드가 서 있다 — JobPostingService 는
--    "회수는 claim 이 하고, 여기서는 붙이지 않는 것만 한다"로 주석까지 못 박았다.
--    V60 판은 status='QUEUED' 만 집으므로 좀비가 영원히 "분석 중"으로 남는다.
--
-- V60 의 사용자당 동시 실행 상한은 develop 백엔드의 활성화 방식(claim 안에서 RUNNING
-- 전환)과 묶인 설계라 여기서는 채택하지 않는다. 이 저장소의 워커는 claim 뒤 자기가
-- 활성화한다(AnalysisWorker). V28 정의를 그대로 복원한다.

CREATE OR REPLACE FUNCTION claim_analysis_job(p_worker_id character varying)
RETURNS TABLE(id uuid, user_id uuid, attempt_count integer)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_temp'
AS $function$
BEGIN
    PERFORM set_config('app.worker_context', 'on', true);

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

    PERFORM set_config('app.worker_context', '', true);
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config('app.worker_context', '', true);
    RAISE;
END;
$function$;

REVOKE ALL ON FUNCTION claim_analysis_job(varchar) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION claim_analysis_job(varchar) TO jobiss_app;
