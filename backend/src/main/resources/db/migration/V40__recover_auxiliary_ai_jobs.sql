CREATE OR REPLACE FUNCTION recover_stale_auxiliary_ai_jobs()
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    changed integer := 0;
    affected integer := 0;
BEGIN
    UPDATE chat_reply_jobs job
    SET
        status = 'FAILED',
        stage = 'FAILED',
        stage_message = '중단된 답변 작업을 자동으로 복구하지 못했어요',
        worker_id = NULL,
        locked_until = NULL,
        error_code = 'CHAT_RETRY_EXHAUSTED',
        error_message = '답변 작업이 반복해서 중단되어 자동 재시도 횟수를 초과했습니다.',
        completed_at = now()
    FROM chat_reply_job_queue queue
    WHERE queue.chat_reply_job_id = job.id
      AND queue.attempt_count >= 3
      AND (queue.locked_until IS NULL OR queue.locked_until < now())
      AND job.status IN ('QUEUED', 'RUNNING');
    GET DIAGNOSTICS affected = ROW_COUNT;
    changed := changed + affected;

    DELETE FROM chat_reply_job_queue queue
    USING chat_reply_jobs job
    WHERE queue.chat_reply_job_id = job.id
      AND job.status = 'FAILED'
      AND job.error_code = 'CHAT_RETRY_EXHAUSTED';

    UPDATE chat_reply_jobs job
    SET
        status = 'QUEUED',
        stage = 'QUEUED',
        stage_message = '중단된 답변을 다시 시작할 준비를 하고 있어요',
        worker_id = NULL,
        locked_until = NULL,
        error_code = NULL,
        error_message = NULL,
        completed_at = NULL
    FROM chat_reply_job_queue queue
    WHERE queue.chat_reply_job_id = job.id
      AND queue.attempt_count < 3
      AND queue.worker_id IS NOT NULL
      AND queue.locked_until < now()
      AND job.status = 'RUNNING';
    GET DIAGNOSTICS affected = ROW_COUNT;
    changed := changed + affected;

    UPDATE chat_reply_job_queue
    SET worker_id = NULL, locked_until = NULL, available_at = now()
    WHERE attempt_count < 3
      AND worker_id IS NOT NULL
      AND locked_until < now();

    UPDATE career_sources source
    SET
        status = 'FAILED',
        stage = 'FAILED',
        stage_message = '중단된 자료 분석을 자동으로 복구하지 못했어요',
        worker_id = NULL,
        locked_until = NULL,
        error_code = 'CAREER_RETRY_EXHAUSTED',
        error_message = '자료 분석이 반복해서 중단되어 자동 재시도 횟수를 초과했습니다.',
        completed_at = now()
    FROM career_source_queue queue
    WHERE queue.career_source_id = source.id
      AND queue.attempt_count >= 3
      AND (queue.locked_until IS NULL OR queue.locked_until < now())
      AND source.status IN ('QUEUED', 'RUNNING');
    GET DIAGNOSTICS affected = ROW_COUNT;
    changed := changed + affected;

    DELETE FROM career_source_queue queue
    USING career_sources source
    WHERE queue.career_source_id = source.id
      AND source.status = 'FAILED'
      AND source.error_code = 'CAREER_RETRY_EXHAUSTED';

    UPDATE career_sources source
    SET
        status = 'QUEUED',
        stage = 'QUEUED',
        stage_message = '중단된 자료 분석을 다시 시작할 준비를 하고 있어요',
        worker_id = NULL,
        locked_until = NULL,
        error_code = NULL,
        error_message = NULL,
        completed_at = NULL
    FROM career_source_queue queue
    WHERE queue.career_source_id = source.id
      AND queue.attempt_count < 3
      AND queue.worker_id IS NOT NULL
      AND queue.locked_until < now()
      AND source.status = 'RUNNING';
    GET DIAGNOSTICS affected = ROW_COUNT;
    changed := changed + affected;

    UPDATE career_source_queue
    SET worker_id = NULL, locked_until = NULL, available_at = now()
    WHERE attempt_count < 3
      AND worker_id IS NOT NULL
      AND locked_until < now();

    UPDATE evidence item
    SET
        verification_status = 'FAILED',
        error_message = '증거 검증이 반복해서 중단되어 자동 재시도 횟수를 초과했습니다.',
        completed_at = now()
    FROM evidence_verification_queue queue
    WHERE queue.evidence_id = item.id
      AND queue.attempt_count >= 3
      AND (queue.locked_until IS NULL OR queue.locked_until < now())
      AND item.verification_status IN ('PENDING', 'RUNNING');
    GET DIAGNOSTICS affected = ROW_COUNT;
    changed := changed + affected;

    DELETE FROM evidence_verification_queue queue
    USING evidence item
    WHERE queue.evidence_id = item.id
      AND item.verification_status = 'FAILED'
      AND item.error_message LIKE '증거 검증이 반복해서 중단%';

    UPDATE evidence item
    SET
        verification_status = 'PENDING',
        error_message = NULL,
        completed_at = NULL
    FROM evidence_verification_queue queue
    WHERE queue.evidence_id = item.id
      AND queue.attempt_count < 3
      AND queue.worker_id IS NOT NULL
      AND queue.locked_until < now()
      AND item.verification_status = 'RUNNING';
    GET DIAGNOSTICS affected = ROW_COUNT;
    changed := changed + affected;

    UPDATE evidence_verification_queue
    SET worker_id = NULL, locked_until = NULL, available_at = now()
    WHERE attempt_count < 3
      AND worker_id IS NOT NULL
      AND locked_until < now();

    RETURN changed;
END;
$$;

REVOKE ALL ON FUNCTION recover_stale_auxiliary_ai_jobs() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION recover_stale_auxiliary_ai_jobs() TO jobiss_app;

CREATE OR REPLACE FUNCTION interrupt_auxiliary_ai_jobs(p_worker_id varchar)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    changed integer := 0;
    affected integer := 0;
BEGIN
    UPDATE chat_reply_jobs job
    SET
        status = 'QUEUED',
        stage = 'QUEUED',
        stage_message = '서버 재시작 후 답변을 이어갈 준비를 하고 있어요',
        worker_id = NULL,
        locked_until = NULL,
        error_code = NULL,
        error_message = NULL,
        completed_at = NULL
    WHERE job.status = 'RUNNING'
      AND job.worker_id = p_worker_id;
    GET DIAGNOSTICS affected = ROW_COUNT;
    changed := changed + affected;

    UPDATE chat_reply_job_queue
    SET
        worker_id = NULL,
        locked_until = NULL,
        available_at = now(),
        attempt_count = greatest(0, attempt_count - 1)
    WHERE worker_id = p_worker_id;

    UPDATE career_sources source
    SET
        status = 'QUEUED',
        stage = 'QUEUED',
        stage_message = '서버 재시작 후 자료 분석을 이어갈 준비를 하고 있어요',
        worker_id = NULL,
        locked_until = NULL,
        error_code = NULL,
        error_message = NULL,
        completed_at = NULL
    WHERE source.status = 'RUNNING'
      AND source.worker_id = p_worker_id;
    GET DIAGNOSTICS affected = ROW_COUNT;
    changed := changed + affected;

    UPDATE career_source_queue
    SET
        worker_id = NULL,
        locked_until = NULL,
        available_at = now(),
        attempt_count = greatest(0, attempt_count - 1)
    WHERE worker_id = p_worker_id;

    UPDATE evidence item
    SET
        verification_status = 'PENDING',
        error_message = NULL,
        completed_at = NULL
    FROM evidence_verification_queue queue
    WHERE queue.evidence_id = item.id
      AND queue.worker_id = p_worker_id
      AND item.verification_status = 'RUNNING';
    GET DIAGNOSTICS affected = ROW_COUNT;
    changed := changed + affected;

    UPDATE evidence_verification_queue
    SET
        worker_id = NULL,
        locked_until = NULL,
        available_at = now(),
        attempt_count = greatest(0, attempt_count - 1)
    WHERE worker_id = p_worker_id;

    RETURN changed;
END;
$$;

REVOKE ALL ON FUNCTION interrupt_auxiliary_ai_jobs(varchar) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION interrupt_auxiliary_ai_jobs(varchar) TO jobiss_app;
