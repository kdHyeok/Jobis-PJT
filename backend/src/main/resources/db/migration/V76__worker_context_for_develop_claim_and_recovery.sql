-- V75 는 develop 워커가 claim 안에서 활성화(RUNNING 전환)한다는 사실을 놓친 채
-- V28 정의(큐만 집는 판)를 복원했다. develop 의 AnalysisWorker 에는 자가 활성화
-- 코드가 없고 requireCurrentWorker 가 status='RUNNING' AND worker_id 를 검사하므로,
-- V75 그대로면 모든 분석 작업이 SupersededAnalysisException 으로 죽는다.
--
-- 여기서는 develop 의 함수 본문(V60 claim, V37 recover, V36 interrupt)을 정본으로
-- 삼되, 세 함수 모두에 app.worker_context 활성화를 넣는다. analysis_jobs 는
-- FORCE ROW LEVEL SECURITY 이고 함수 소유자 jobiss_migrator 는 의도적으로
-- NOBYPASSRLS 라서(ops/bootstrap-jobis-v2-database), set_config 없이는 SECURITY
-- DEFINER 여도 워커 경로가 0건을 본다(V28 참고). set_config 의 is_local=true 라
-- 트랜잭션이 끝나면 자동으로 풀린다 — 세 함수 모두 워커가 짧은 단독 트랜잭션으로
-- 부른다(AnalysisWorker: claim/recoverStaleJobs/shutdown).
--
-- 회수·좀비 정리는 V28 처럼 claim 이 아니라 recover_stale_analysis_jobs 가 맡는다
-- (develop 워커가 폴링마다 recover 를 부른다). 사용자당 동시 2건 제한(V60)도 유지한다.

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
    PERFORM set_config('app.worker_context', 'on', true);

    RETURN QUERY
    WITH candidate AS MATERIALIZED (
        SELECT queue.analysis_job_id
        FROM analysis_job_queue queue
        JOIN analysis_jobs job
          ON job.id = queue.analysis_job_id
        WHERE job.status = 'QUEUED'
          AND queue.available_at <= now()
          AND (queue.locked_until IS NULL OR queue.locked_until < now())
          AND queue.attempt_count < 3
          AND (
              SELECT count(*)
              FROM analysis_jobs running
              WHERE running.user_id = job.user_id
                AND running.status = 'RUNNING'
          ) < 2
          AND pg_try_advisory_xact_lock(
              hashtextextended('jobiss-analysis-user:' || job.user_id::text, 0)
          )
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
        RETURNING queue.analysis_job_id, queue.user_id, queue.attempt_count
    ),
    activated AS (
        UPDATE analysis_jobs job
        SET
            status = 'RUNNING',
            stage = 'CONTEXT',
            stage_message = '공고와 현재 커리어 자료를 정리하고 있어요.',
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
    PERFORM set_config('app.worker_context', 'on', true);

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

CREATE OR REPLACE FUNCTION interrupt_analysis_jobs(p_worker_id varchar)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    interrupted_job record;
    interrupted_count integer := 0;
BEGIN
    PERFORM set_config('app.worker_context', 'on', true);

    FOR interrupted_job IN
        SELECT id, user_id
        FROM analysis_jobs
        WHERE status = 'RUNNING'
          AND worker_id = p_worker_id
        FOR UPDATE SKIP LOCKED
    LOOP
        UPDATE analysis_jobs
        SET
            status = 'FAILED',
            stage = 'INTERRUPTED',
            stage_message = '서버 종료로 분석이 멈췄어요',
            worker_id = NULL,
            locked_until = NULL,
            error_code = 'WORKER_INTERRUPTED',
            error_message = '백엔드 서버가 종료되어 진행 중이던 작업을 안전하게 중단했습니다.',
            completed_at = now()
        WHERE id = interrupted_job.id;

        DELETE FROM analysis_job_queue
        WHERE analysis_job_id = interrupted_job.id;

        DELETE FROM posting_analysis_leases
        WHERE owner_analysis_job_id = interrupted_job.id;

        interrupted_count := interrupted_count + 1;
    END LOOP;

    RETURN interrupted_count;
END;
$$;

REVOKE ALL ON FUNCTION claim_analysis_job(varchar) FROM PUBLIC;
REVOKE ALL ON FUNCTION recover_stale_analysis_jobs() FROM PUBLIC;
REVOKE ALL ON FUNCTION interrupt_analysis_jobs(varchar) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION claim_analysis_job(varchar) TO jobiss_app;
GRANT EXECUTE ON FUNCTION recover_stale_analysis_jobs() TO jobiss_app;
GRANT EXECUTE ON FUNCTION interrupt_analysis_jobs(varchar) TO jobiss_app;
