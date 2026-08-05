-- 백그라운드 워커가 작업 큐를 claim 하지 못하던 문제를 고친다.
--
-- 증상: chat_reply_jobs 가 QUEUED 상태로 남고 attempt_count 가 0에서 오르지 않는다.
--       analysis_job_queue 도 worker_id 가 한 번도 채워지지 않는다.
--
-- 원인: claim_chat_reply_job / claim_analysis_job 은 SECURITY DEFINER 지만
--       chat_reply_jobs 와 analysis_jobs 에 FORCE ROW LEVEL SECURITY 가 걸려 있어
--       테이블 소유자로 실행해도 RLS 가 적용된다. 두 테이블의 정책은
--       user_id = app_current_user_id() 하나뿐인데, 워커는 특정 사용자로 동작하지
--       않으므로 app.current_user_id 가 비어 있고 조인 결과가 항상 0건이 된다.
--
-- 해결: 사용자 컨텍스트와 구분되는 "워커 컨텍스트"를 도입한다.
--       두 claim 함수 안에서만 app.worker_context 를 켜고 반환 직전에 되돌리며,
--       해당 컨텍스트를 허용하는 정책을 추가한다.
--       RLS 자체는 유지되므로 일반 사용자 세션의 격리는 그대로다.
--
--       함수 수준 SET 절(SET "app.worker_context" TO 'on')은 쓰지 않는다. 정의되지 않은
--       사용자 정의 파라미터를 함수 정의에 넣으려면 별도 권한이 필요해서, 슈퍼유저가 아닌
--       마이그레이션 사용자로 실행되는 Flyway 에서 42501 로 실패한다.
--       반면 실행 시점의 set_config(..., is_local => true) 는 일반 역할도 사용할 수 있다
--       (애플리케이션이 app.current_user_id 를 설정하는 것과 같은 방식).
--
-- 신뢰 경계: app.current_user_id 와 마찬가지로 이 GUC 도 애플리케이션이 올바르게
--       다룬다는 전제 위에 있다. 워커 컨텍스트를 켜는 곳은 아래 두 함수뿐이며,
--       애플리케이션 코드에서 직접 설정하지 않는다.

CREATE OR REPLACE FUNCTION app_is_worker_context()
RETURNS boolean
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
    SELECT coalesce(current_setting('app.worker_context', true), '') = 'on'
$$;

DROP POLICY IF EXISTS chat_reply_jobs_worker_policy ON chat_reply_jobs;
CREATE POLICY chat_reply_jobs_worker_policy ON chat_reply_jobs
    FOR ALL
    USING (app_is_worker_context())
    WITH CHECK (app_is_worker_context());

DROP POLICY IF EXISTS analysis_jobs_worker_policy ON analysis_jobs;
CREATE POLICY analysis_jobs_worker_policy ON analysis_jobs
    FOR ALL
    USING (app_is_worker_context())
    WITH CHECK (app_is_worker_context());

-- 아래 두 함수는 기존 질의를 그대로 두고 워커 컨텍스트 설정·해제만 감싼다.

CREATE OR REPLACE FUNCTION claim_chat_reply_job(p_worker_id character varying)
RETURNS TABLE(id uuid, user_id uuid, attempt_count integer)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_temp'
AS $function$
BEGIN
    PERFORM set_config('app.worker_context', 'on', true);

    RETURN QUERY
    WITH candidate AS (
        SELECT q.chat_reply_job_id
        FROM chat_reply_job_queue q
        JOIN chat_reply_jobs j ON j.id = q.chat_reply_job_id
        WHERE
            q.available_at <= now()
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
$function$;

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
