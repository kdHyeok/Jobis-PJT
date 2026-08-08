CREATE OR REPLACE FUNCTION recover_stale_analysis_jobs()
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    stale_job record;
    recovered_count integer := 0;
BEGIN
    FOR stale_job IN
        SELECT id, user_id
        FROM analysis_jobs
        WHERE status = 'RUNNING'
          AND (locked_until IS NULL OR locked_until < now())
        FOR UPDATE SKIP LOCKED
    LOOP
        UPDATE analysis_jobs
        SET
            status = 'FAILED',
            stage = 'INTERRUPTED',
            stage_message = '서버 중단으로 분석이 멈췄어요',
            worker_id = NULL,
            locked_until = NULL,
            error_code = 'WORKER_INTERRUPTED',
            error_message = '분석 서버가 종료되어 진행 중이던 작업을 안전하게 중단했습니다.',
            completed_at = now()
        WHERE id = stale_job.id;

        DELETE FROM analysis_job_queue
        WHERE analysis_job_id = stale_job.id;

        DELETE FROM posting_analysis_leases
        WHERE owner_analysis_job_id = stale_job.id;

        recovered_count := recovered_count + 1;
    END LOOP;

    RETURN recovered_count;
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

REVOKE ALL ON FUNCTION recover_stale_analysis_jobs() FROM PUBLIC;
REVOKE ALL ON FUNCTION interrupt_analysis_jobs(varchar) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION recover_stale_analysis_jobs() TO jobiss_app;
GRANT EXECUTE ON FUNCTION interrupt_analysis_jobs(varchar) TO jobiss_app;
