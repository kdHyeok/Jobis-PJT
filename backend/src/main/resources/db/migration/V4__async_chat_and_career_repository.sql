ALTER TABLE analysis_jobs
    ADD COLUMN stage varchar(40) NOT NULL DEFAULT 'QUEUED',
    ADD COLUMN stage_message text NOT NULL DEFAULT '분석 대기 중';

ALTER TABLE ai_usage_hourly
    DROP CONSTRAINT ai_usage_hourly_usage_kind_check,
    ADD CONSTRAINT ai_usage_hourly_usage_kind_check
        CHECK (usage_kind IN ('CHAT', 'ANALYSIS', 'EVIDENCE', 'CAREER'));

UPDATE career_nodes
SET detail = detail || CASE canonical_key
    WHEN 'foundation.programming' THEN '{
      "why":"모든 개발 분야에서 코드를 읽고 작은 문제를 해결하기 위한 공통 출발점입니다.",
      "estimatedDuration":"1~2일",
      "outcomes":["변수, 조건문, 반복문과 함수를 설명한다","작은 문제를 코드로 해결한다"],
      "quests":[
        {"title":"기초 문법 점검","description":"익숙한 언어 하나로 변수·조건·반복 예제를 작성합니다.","doneCriteria":"각 문법이 언제 필요한지 설명할 수 있다"},
        {"title":"함수로 문제 나누기","description":"작은 프로그램을 여러 함수로 분리합니다.","doneCriteria":"입력·처리·출력을 함수로 구분한다"},
        {"title":"작은 문제 해결","description":"자료구조 하나를 사용한 문제를 직접 해결합니다.","doneCriteria":"실행 결과와 선택 이유를 설명한다"}
      ]
    }'::jsonb
    WHEN 'foundation.git-terminal' THEN '{
      "why":"프로젝트 실행과 협업 기록을 남기기 위한 모든 개발 직무의 공통 도구입니다.",
      "estimatedDuration":"1일",
      "outcomes":["터미널에서 프로젝트를 실행한다","브랜치와 커밋으로 변경 이력을 관리한다"],
      "quests":[
        {"title":"터미널로 프로젝트 실행","description":"디렉터리 이동, 파일 확인, 실행 명령을 사용합니다.","doneCriteria":"README만 보고 프로젝트를 실행한다"},
        {"title":"브랜치 작업","description":"기능 브랜치를 만들고 의미 있는 커밋을 남깁니다.","doneCriteria":"브랜치와 커밋 기록을 확인할 수 있다"},
        {"title":"실행 방법 기록","description":"다른 사람이 따라 할 수 있는 실행 문서를 작성합니다.","doneCriteria":"새 환경에서 문서대로 실행된다"}
      ]
    }'::jsonb
    WHEN 'foundation.cs' THEN '{
      "why":"기술 이름을 외우는 대신 프로그램이 동작하는 이유를 설명하기 위한 기반입니다.",
      "estimatedDuration":"2~3일",
      "outcomes":["프로세스와 메모리의 기본 역할을 설명한다","자료구조와 시간 복잡도를 비교한다"],
      "quests":[
        {"title":"프로세스와 메모리 설명","description":"실행 중인 프로그램과 메모리 사용 흐름을 자신의 말로 정리합니다.","doneCriteria":"예시를 들어 핵심 개념을 설명한다"},
        {"title":"자료구조 비교","description":"배열, 리스트, 맵의 선택 기준을 비교합니다.","doneCriteria":"조회·삽입 특성에 따라 선택한다"},
        {"title":"복잡도 점검","description":"작성한 코드의 반복 횟수와 시간 복잡도를 계산합니다.","doneCriteria":"간단한 코드의 Big-O를 설명한다"}
      ]
    }'::jsonb
    ELSE '{}'::jsonb
END
WHERE canonical_key IN (
    'foundation.programming',
    'foundation.git-terminal',
    'foundation.cs'
);

CREATE TABLE chat_reply_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id uuid NOT NULL,
    trigger_message_id uuid NOT NULL,
    status analysis_job_status NOT NULL DEFAULT 'QUEUED',
    stage varchar(40) NOT NULL DEFAULT 'QUEUED',
    stage_message text NOT NULL DEFAULT '답변 대기 중',
    attempt_count integer NOT NULL DEFAULT 0,
    worker_id varchar(120),
    locked_until timestamptz,
    error_code varchar(80),
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    completed_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id),
    UNIQUE (trigger_message_id),
    CONSTRAINT chat_reply_conversation_owner_fk
        FOREIGN KEY (conversation_id, user_id)
        REFERENCES conversations(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT chat_reply_message_owner_fk
        FOREIGN KEY (trigger_message_id, user_id)
        REFERENCES conversation_messages(id, user_id)
        ON DELETE CASCADE
);

CREATE TABLE chat_reply_job_queue (
    chat_reply_job_id uuid PRIMARY KEY,
    user_id uuid NOT NULL,
    available_at timestamptz NOT NULL DEFAULT now(),
    locked_until timestamptz,
    worker_id varchar(120),
    attempt_count integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE career_sources (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_type varchar(30) NOT NULL
        CHECK (source_type IN ('TEXT', 'FILE', 'URL')),
    title varchar(180) NOT NULL,
    source_url text,
    raw_text text NOT NULL,
    status varchar(30) NOT NULL DEFAULT 'QUEUED'
        CHECK (status IN ('QUEUED', 'RUNNING', 'REVIEW_READY', 'CONFIRMED', 'FAILED')),
    stage varchar(40) NOT NULL DEFAULT 'QUEUED',
    stage_message text NOT NULL DEFAULT '자료 분석 대기 중',
    summary text,
    attempt_count integer NOT NULL DEFAULT 0,
    worker_id varchar(120),
    locked_until timestamptz,
    error_code varchar(80),
    error_message text,
    archived_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id),
    CHECK (char_length(raw_text) BETWEEN 20 AND 100000)
);

CREATE TABLE career_source_queue (
    career_source_id uuid PRIMARY KEY,
    user_id uuid NOT NULL,
    available_at timestamptz NOT NULL DEFAULT now(),
    locked_until timestamptz,
    worker_id varchar(120),
    attempt_count integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE career_fragments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_id uuid NOT NULL,
    kind varchar(40) NOT NULL
        CHECK (kind IN (
            'SKILL',
            'PROJECT',
            'EXPERIENCE',
            'EDUCATION',
            'CREDENTIAL',
            'ACHIEVEMENT',
            'LINK'
        )),
    title varchar(180) NOT NULL,
    description text NOT NULL DEFAULT '',
    canonical_key varchar(160),
    detail jsonb NOT NULL DEFAULT '{}'::jsonb,
    review_status varchar(30) NOT NULL DEFAULT 'SUGGESTED'
        CHECK (review_status IN ('SUGGESTED', 'CONFIRMED', 'REJECTED')),
    archived_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id),
    CONSTRAINT career_fragment_source_owner_fk
        FOREIGN KEY (source_id, user_id)
        REFERENCES career_sources(id, user_id)
        ON DELETE CASCADE
);

CREATE INDEX chat_reply_jobs_conversation_created_idx
    ON chat_reply_jobs (conversation_id, created_at);
CREATE INDEX chat_reply_job_queue_available_idx
    ON chat_reply_job_queue (available_at, locked_until, created_at);
CREATE INDEX career_sources_user_recent_idx
    ON career_sources (user_id, created_at DESC);
CREATE INDEX career_source_queue_available_idx
    ON career_source_queue (available_at, locked_until, created_at);
CREATE INDEX career_fragments_user_filter_idx
    ON career_fragments (user_id, review_status, kind, created_at DESC);

CREATE TRIGGER chat_reply_jobs_touch_updated_at
BEFORE UPDATE ON chat_reply_jobs
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

CREATE TRIGGER career_sources_touch_updated_at
BEFORE UPDATE ON career_sources
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

CREATE TRIGGER career_fragments_touch_updated_at
BEFORE UPDATE ON career_fragments
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

CREATE OR REPLACE FUNCTION enqueue_chat_reply_job()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    INSERT INTO chat_reply_job_queue (chat_reply_job_id, user_id)
    VALUES (NEW.id, NEW.user_id)
    ON CONFLICT (chat_reply_job_id)
    DO UPDATE SET
        available_at = now(),
        locked_until = NULL,
        worker_id = NULL;
    RETURN NEW;
END;
$$;

CREATE TRIGGER chat_reply_jobs_enqueue
AFTER INSERT ON chat_reply_jobs
FOR EACH ROW EXECUTE FUNCTION enqueue_chat_reply_job();

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
    RETURN QUERY
    WITH candidate AS (
        SELECT q.chat_reply_job_id
        FROM chat_reply_job_queue q
        WHERE
            q.available_at <= now()
            AND (q.locked_until IS NULL OR q.locked_until < now())
            AND q.attempt_count < 3
        ORDER BY q.created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    ),
    claimed AS (
        UPDATE chat_reply_job_queue q
        SET
            worker_id = p_worker_id,
            locked_until = now() + interval '5 minutes',
            attempt_count = q.attempt_count + 1
        FROM candidate c
        WHERE q.chat_reply_job_id = c.chat_reply_job_id
        RETURNING q.chat_reply_job_id, q.user_id, q.attempt_count
    )
    SELECT c.chat_reply_job_id, c.user_id, c.attempt_count
    FROM claimed c;
END;
$$;

CREATE OR REPLACE FUNCTION finish_chat_reply_job(
    p_chat_reply_job_id uuid,
    p_user_id uuid
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

    DELETE FROM chat_reply_job_queue
    WHERE chat_reply_job_id = p_chat_reply_job_id
      AND user_id = p_user_id;
END;
$$;

CREATE OR REPLACE FUNCTION requeue_chat_reply_job(
    p_chat_reply_job_id uuid,
    p_user_id uuid
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

    INSERT INTO chat_reply_job_queue (chat_reply_job_id, user_id)
    VALUES (p_chat_reply_job_id, p_user_id)
    ON CONFLICT (chat_reply_job_id)
    DO UPDATE SET
        available_at = now(),
        locked_until = NULL,
        worker_id = NULL;
END;
$$;

CREATE OR REPLACE FUNCTION enqueue_career_source()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    INSERT INTO career_source_queue (career_source_id, user_id)
    VALUES (NEW.id, NEW.user_id)
    ON CONFLICT (career_source_id)
    DO UPDATE SET
        available_at = now(),
        locked_until = NULL,
        worker_id = NULL;
    RETURN NEW;
END;
$$;

CREATE TRIGGER career_sources_enqueue
AFTER INSERT ON career_sources
FOR EACH ROW EXECUTE FUNCTION enqueue_career_source();

CREATE OR REPLACE FUNCTION claim_career_source(p_worker_id varchar)
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
    RETURN QUERY
    WITH candidate AS (
        SELECT q.career_source_id
        FROM career_source_queue q
        WHERE
            q.available_at <= now()
            AND (q.locked_until IS NULL OR q.locked_until < now())
            AND q.attempt_count < 3
        ORDER BY q.created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    ),
    claimed AS (
        UPDATE career_source_queue q
        SET
            worker_id = p_worker_id,
            locked_until = now() + interval '5 minutes',
            attempt_count = q.attempt_count + 1
        FROM candidate c
        WHERE q.career_source_id = c.career_source_id
        RETURNING q.career_source_id, q.user_id, q.attempt_count
    )
    SELECT c.career_source_id, c.user_id, c.attempt_count
    FROM claimed c;
END;
$$;

CREATE OR REPLACE FUNCTION finish_career_source(
    p_career_source_id uuid,
    p_user_id uuid
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    IF p_user_id IS DISTINCT FROM app_current_user_id() THEN
        RAISE EXCEPTION 'career source owner mismatch';
    END IF;

    DELETE FROM career_source_queue
    WHERE career_source_id = p_career_source_id
      AND user_id = p_user_id;
END;
$$;

CREATE OR REPLACE FUNCTION requeue_career_source(
    p_career_source_id uuid,
    p_user_id uuid
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    IF p_user_id IS DISTINCT FROM app_current_user_id() THEN
        RAISE EXCEPTION 'career source owner mismatch';
    END IF;

    INSERT INTO career_source_queue (career_source_id, user_id)
    VALUES (p_career_source_id, p_user_id)
    ON CONFLICT (career_source_id)
    DO UPDATE SET
        available_at = now(),
        locked_until = NULL,
        worker_id = NULL;
END;
$$;

ALTER TABLE chat_reply_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_reply_jobs FORCE ROW LEVEL SECURITY;
ALTER TABLE career_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE career_sources FORCE ROW LEVEL SECURITY;
ALTER TABLE career_fragments ENABLE ROW LEVEL SECURITY;
ALTER TABLE career_fragments FORCE ROW LEVEL SECURITY;

CREATE POLICY chat_reply_jobs_owner_policy ON chat_reply_jobs
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());
CREATE POLICY career_sources_owner_policy ON career_sources
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());
CREATE POLICY career_fragments_owner_policy ON career_fragments
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());

REVOKE ALL ON chat_reply_job_queue, career_source_queue FROM PUBLIC;
REVOKE ALL ON FUNCTION claim_chat_reply_job(varchar) FROM PUBLIC;
REVOKE ALL ON FUNCTION finish_chat_reply_job(uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION requeue_chat_reply_job(uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION claim_career_source(varchar) FROM PUBLIC;
REVOKE ALL ON FUNCTION finish_career_source(uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION requeue_career_source(uuid, uuid) FROM PUBLIC;

GRANT SELECT, INSERT, UPDATE, DELETE ON
    chat_reply_jobs,
    career_sources,
    career_fragments
TO jobiss_app;
GRANT EXECUTE ON FUNCTION claim_chat_reply_job(varchar) TO jobiss_app;
GRANT EXECUTE ON FUNCTION finish_chat_reply_job(uuid, uuid) TO jobiss_app;
GRANT EXECUTE ON FUNCTION requeue_chat_reply_job(uuid, uuid) TO jobiss_app;
GRANT EXECUTE ON FUNCTION claim_career_source(varchar) TO jobiss_app;
GRANT EXECUTE ON FUNCTION finish_career_source(uuid, uuid) TO jobiss_app;
GRANT EXECUTE ON FUNCTION requeue_career_source(uuid, uuid) TO jobiss_app;

REVOKE ALL ON chat_reply_jobs, career_sources, career_fragments FROM PUBLIC;
