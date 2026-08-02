CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TYPE account_status AS ENUM ('ACTIVE', 'SUSPENDED', 'WITHDRAWN');
CREATE TYPE posting_source AS ENUM ('TEXT', 'URL', 'FILE');
CREATE TYPE analysis_job_status AS ENUM ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED');
CREATE TYPE graph_node_kind AS ENUM (
    'FOUNDATION',
    'SKILL',
    'PROJECT',
    'CREDENTIAL',
    'EXPERIENCE',
    'OPPORTUNITY',
    'OPPORTUNITY_CLUSTER'
);
CREATE TYPE progress_status AS ENUM ('NOT_STARTED', 'IN_PROGRESS', 'COMPLETED', 'REJECTED');
CREATE TYPE requirement_kind AS ENUM ('REQUIRED', 'PREFERRED');
CREATE TYPE change_set_status AS ENUM ('PROPOSED', 'APPROVED', 'REJECTED');

CREATE TABLE users (
    id uuid PRIMARY KEY,
    email citext NOT NULL UNIQUE,
    display_name varchar(80) NOT NULL,
    status account_status NOT NULL DEFAULT 'ACTIVE',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE auth_identities (
    user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    email citext NOT NULL UNIQUE,
    password_hash text NOT NULL,
    status account_status NOT NULL DEFAULT 'ACTIVE',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE career_graphs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title varchar(120) NOT NULL DEFAULT '나의 커리어 지도',
    version bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id),
    UNIQUE (user_id)
);

CREATE TABLE competency_catalog (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_key varchar(120) NOT NULL UNIQUE,
    title varchar(120) NOT NULL,
    domain varchar(40) NOT NULL,
    scope_definition text NOT NULL,
    level_definition jsonb NOT NULL DEFAULT '{}'::jsonb,
    self_confirmable boolean NOT NULL DEFAULT false,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE job_postings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_type posting_source NOT NULL,
    source_url text,
    raw_text text NOT NULL,
    company_name varchar(160),
    role_title varchar(200),
    employment_type varchar(80),
    experience_text varchar(160),
    parsed_data jsonb,
    archived_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id)
);

CREATE TABLE analysis_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    posting_id uuid NOT NULL,
    status analysis_job_status NOT NULL DEFAULT 'QUEUED',
    attempt_count integer NOT NULL DEFAULT 0,
    worker_id varchar(120),
    locked_until timestamptz,
    error_code varchar(80),
    error_message text,
    result_data jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    completed_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id),
    CONSTRAINT analysis_job_posting_owner_fk
        FOREIGN KEY (posting_id, user_id)
        REFERENCES job_postings(id, user_id)
        ON DELETE CASCADE
);

CREATE TABLE analysis_job_queue (
    analysis_job_id uuid PRIMARY KEY,
    user_id uuid NOT NULL,
    available_at timestamptz NOT NULL DEFAULT now(),
    locked_until timestamptz,
    worker_id varchar(120),
    attempt_count integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE graph_change_sets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    analysis_job_id uuid NOT NULL,
    status change_set_status NOT NULL DEFAULT 'PROPOSED',
    proposal jsonb NOT NULL,
    approved_at timestamptz,
    rejected_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id),
    UNIQUE (analysis_job_id),
    CONSTRAINT change_set_analysis_owner_fk
        FOREIGN KEY (analysis_job_id, user_id)
        REFERENCES analysis_jobs(id, user_id)
        ON DELETE CASCADE
);

CREATE TABLE career_nodes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    graph_id uuid NOT NULL,
    competency_id uuid REFERENCES competency_catalog(id),
    posting_id uuid,
    kind graph_node_kind NOT NULL,
    canonical_key varchar(160) NOT NULL,
    title varchar(160) NOT NULL,
    subtitle varchar(240),
    domain varchar(40) NOT NULL,
    scope_definition text,
    level integer NOT NULL DEFAULT 1 CHECK (level BETWEEN 1 AND 5),
    detail jsonb NOT NULL DEFAULT '{}'::jsonb,
    rank integer NOT NULL DEFAULT 0,
    archived_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id),
    UNIQUE (graph_id, canonical_key),
    CONSTRAINT career_node_graph_owner_fk
        FOREIGN KEY (graph_id, user_id)
        REFERENCES career_graphs(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT career_node_posting_owner_fk
        FOREIGN KEY (posting_id, user_id)
        REFERENCES job_postings(id, user_id)
        ON DELETE SET NULL (posting_id)
);

CREATE TABLE career_edges (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    graph_id uuid NOT NULL,
    from_node_id uuid NOT NULL,
    to_node_id uuid NOT NULL,
    edge_kind varchar(40) NOT NULL DEFAULT 'PREREQUISITE',
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id),
    UNIQUE (graph_id, from_node_id, to_node_id, edge_kind),
    CHECK (from_node_id <> to_node_id),
    CONSTRAINT career_edge_graph_owner_fk
        FOREIGN KEY (graph_id, user_id)
        REFERENCES career_graphs(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT career_edge_from_owner_fk
        FOREIGN KEY (from_node_id, user_id)
        REFERENCES career_nodes(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT career_edge_to_owner_fk
        FOREIGN KEY (to_node_id, user_id)
        REFERENCES career_nodes(id, user_id)
        ON DELETE CASCADE
);

CREATE TABLE job_requirements (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    posting_id uuid NOT NULL,
    node_id uuid NOT NULL,
    requirement requirement_kind NOT NULL,
    source_text text,
    confidence numeric(4,3) CHECK (confidence BETWEEN 0 AND 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (posting_id, node_id, requirement),
    CONSTRAINT requirement_posting_owner_fk
        FOREIGN KEY (posting_id, user_id)
        REFERENCES job_postings(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT requirement_node_owner_fk
        FOREIGN KEY (node_id, user_id)
        REFERENCES career_nodes(id, user_id)
        ON DELETE CASCADE
);

CREATE TABLE node_progress (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    node_id uuid NOT NULL,
    status progress_status NOT NULL DEFAULT 'NOT_STARTED',
    completion_method varchar(40),
    completed_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (node_id),
    CONSTRAINT progress_node_owner_fk
        FOREIGN KEY (node_id, user_id)
        REFERENCES career_nodes(id, user_id)
        ON DELETE CASCADE
);

CREATE TABLE evidence (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    node_id uuid,
    evidence_type varchar(40) NOT NULL,
    title varchar(180) NOT NULL,
    source_url text,
    content jsonb NOT NULL DEFAULT '{}'::jsonb,
    verification_status varchar(40) NOT NULL DEFAULT 'PENDING',
    verification_result jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id),
    CONSTRAINT evidence_node_owner_fk
        FOREIGN KEY (node_id, user_id)
        REFERENCES career_nodes(id, user_id)
        ON DELETE SET NULL (node_id)
);

CREATE TABLE notifications (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    notification_type varchar(60) NOT NULL,
    title varchar(180) NOT NULL,
    body text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    read_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id)
);

CREATE INDEX analysis_jobs_queue_idx
    ON analysis_jobs (status, created_at)
    WHERE status = 'QUEUED';
CREATE INDEX analysis_job_queue_available_idx
    ON analysis_job_queue (available_at, locked_until, created_at);
CREATE INDEX job_postings_user_created_idx ON job_postings (user_id, created_at DESC);
CREATE INDEX career_nodes_graph_rank_idx ON career_nodes (graph_id, rank);
CREATE INDEX notifications_user_unread_idx ON notifications (user_id, created_at DESC)
    WHERE read_at IS NULL;

INSERT INTO competency_catalog
    (canonical_key, title, domain, scope_definition, level_definition, self_confirmable)
VALUES
    (
        'foundation.programming',
        '프로그래밍 기초',
        'COMMON',
        '변수, 제어문, 함수와 기본 자료구조를 사용해 작은 문제를 해결하는 범위',
        '{"1":"기초 문법을 설명하고 작은 프로그램을 작성한다"}',
        true
    ),
    (
        'foundation.git-terminal',
        'Git · 터미널',
        'COMMON',
        '명령줄에서 프로젝트를 실행하고 Git 브랜치와 커밋으로 변경 이력을 관리하는 범위',
        '{"1":"브랜치 기반 작업과 실행 문서를 남긴다"}',
        true
    ),
    (
        'foundation.cs',
        'CS 기초',
        'COMMON',
        '운영체제, 자료구조, 프로세스, 메모리와 시간 복잡도의 기본 범위',
        '{"1":"핵심 개념을 자신의 말로 설명한다"}',
        true
    ),
    (
        'shared.http-network',
        'HTTP · 네트워크',
        'COMMON',
        'HTTP 요청·응답, 상태 코드, TCP/IP와 DNS의 애플리케이션 개발 공통 범위',
        '{"1":"요청 흐름을 설명한다","2":"패킷과 헤더를 분석한다"}',
        false
    ),
    (
        'shared.linux-foundation',
        'Linux 기초',
        'COMMON',
        '프로세스, 파일 권한, 로그와 네트워크 명령을 사용하는 공통 운영 범위',
        '{"1":"기본 명령을 사용한다","2":"장애 원인을 진단한다"}',
        false
    );

CREATE OR REPLACE FUNCTION app_current_user_id()
RETURNS uuid
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
    SELECT nullif(current_setting('app.current_user_id', true), '')::uuid
$$;

CREATE OR REPLACE FUNCTION touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER users_touch_updated_at
BEFORE UPDATE ON users
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
CREATE TRIGGER auth_identities_touch_updated_at
BEFORE UPDATE ON auth_identities
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
CREATE TRIGGER career_graphs_touch_updated_at
BEFORE UPDATE ON career_graphs
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
CREATE TRIGGER job_postings_touch_updated_at
BEFORE UPDATE ON job_postings
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
CREATE TRIGGER analysis_jobs_touch_updated_at
BEFORE UPDATE ON analysis_jobs
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
CREATE TRIGGER graph_change_sets_touch_updated_at
BEFORE UPDATE ON graph_change_sets
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
CREATE TRIGGER career_nodes_touch_updated_at
BEFORE UPDATE ON career_nodes
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
CREATE TRIGGER node_progress_touch_updated_at
BEFORE UPDATE ON node_progress
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
CREATE TRIGGER evidence_touch_updated_at
BEFORE UPDATE ON evidence
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;
ALTER TABLE career_graphs ENABLE ROW LEVEL SECURITY;
ALTER TABLE career_graphs FORCE ROW LEVEL SECURITY;
ALTER TABLE job_postings ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_postings FORCE ROW LEVEL SECURITY;
ALTER TABLE analysis_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis_jobs FORCE ROW LEVEL SECURITY;
ALTER TABLE graph_change_sets ENABLE ROW LEVEL SECURITY;
ALTER TABLE graph_change_sets FORCE ROW LEVEL SECURITY;
ALTER TABLE career_nodes ENABLE ROW LEVEL SECURITY;
ALTER TABLE career_nodes FORCE ROW LEVEL SECURITY;
ALTER TABLE career_edges ENABLE ROW LEVEL SECURITY;
ALTER TABLE career_edges FORCE ROW LEVEL SECURITY;
ALTER TABLE job_requirements ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_requirements FORCE ROW LEVEL SECURITY;
ALTER TABLE node_progress ENABLE ROW LEVEL SECURITY;
ALTER TABLE node_progress FORCE ROW LEVEL SECURITY;
ALTER TABLE evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence FORCE ROW LEVEL SECURITY;
ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications FORCE ROW LEVEL SECURITY;

CREATE POLICY users_owner_policy ON users
    USING (id = app_current_user_id())
    WITH CHECK (id = app_current_user_id());
CREATE POLICY career_graphs_owner_policy ON career_graphs
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());
CREATE POLICY job_postings_owner_policy ON job_postings
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());
CREATE POLICY analysis_jobs_owner_policy ON analysis_jobs
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());
CREATE POLICY graph_change_sets_owner_policy ON graph_change_sets
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());
CREATE POLICY career_nodes_owner_policy ON career_nodes
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());
CREATE POLICY career_edges_owner_policy ON career_edges
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());
CREATE POLICY job_requirements_owner_policy ON job_requirements
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());
CREATE POLICY node_progress_owner_policy ON node_progress
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());
CREATE POLICY evidence_owner_policy ON evidence
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());
CREATE POLICY notifications_owner_policy ON notifications
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());

CREATE OR REPLACE FUNCTION create_auth_identity(
    p_user_id uuid,
    p_email citext,
    p_password_hash text
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    IF p_user_id IS DISTINCT FROM app_current_user_id() THEN
        RAISE EXCEPTION 'auth identity must match current RLS user';
    END IF;

    INSERT INTO auth_identities (user_id, email, password_hash)
    VALUES (p_user_id, p_email, p_password_hash);
END;
$$;

CREATE OR REPLACE FUNCTION auth_lookup_user(p_email citext)
RETURNS TABLE (
    id uuid,
    email citext,
    password_hash text,
    status account_status
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT a.user_id, a.email, a.password_hash, a.status
    FROM auth_identities a
    WHERE a.email = p_email
    LIMIT 1
$$;

CREATE OR REPLACE FUNCTION sync_auth_identity_status()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    IF NEW.status IS DISTINCT FROM OLD.status THEN
        UPDATE auth_identities
        SET status = NEW.status
        WHERE user_id = NEW.id;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER users_sync_auth_status
AFTER UPDATE OF status ON users
FOR EACH ROW EXECUTE FUNCTION sync_auth_identity_status();

CREATE OR REPLACE FUNCTION enqueue_analysis_job()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    INSERT INTO analysis_job_queue (analysis_job_id, user_id)
    VALUES (NEW.id, NEW.user_id)
    ON CONFLICT (analysis_job_id)
    DO UPDATE SET
        available_at = now(),
        locked_until = NULL,
        worker_id = NULL;
    RETURN NEW;
END;
$$;

CREATE TRIGGER analysis_jobs_enqueue
AFTER INSERT ON analysis_jobs
FOR EACH ROW EXECUTE FUNCTION enqueue_analysis_job();

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
    RETURN QUERY
    WITH candidate AS (
        SELECT q.analysis_job_id
        FROM analysis_job_queue q
        WHERE
            q.available_at <= now()
            AND (q.locked_until IS NULL OR q.locked_until < now())
            AND q.attempt_count < 3
        ORDER BY q.created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    ),
    claimed AS (
        UPDATE analysis_job_queue q
        SET
            worker_id = p_worker_id,
            locked_until = now() + interval '5 minutes',
            attempt_count = q.attempt_count + 1
        FROM candidate c
        WHERE q.analysis_job_id = c.analysis_job_id
        RETURNING q.analysis_job_id, q.user_id, q.attempt_count
    )
    SELECT c.analysis_job_id, c.user_id, c.attempt_count
    FROM claimed c;
END;
$$;

CREATE OR REPLACE FUNCTION finish_analysis_job(
    p_analysis_job_id uuid,
    p_user_id uuid
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    IF p_user_id IS DISTINCT FROM app_current_user_id() THEN
        RAISE EXCEPTION 'analysis job owner mismatch';
    END IF;

    DELETE FROM analysis_job_queue
    WHERE analysis_job_id = p_analysis_job_id
      AND user_id = p_user_id;
END;
$$;

CREATE OR REPLACE FUNCTION requeue_analysis_job(
    p_analysis_job_id uuid,
    p_user_id uuid
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    IF p_user_id IS DISTINCT FROM app_current_user_id() THEN
        RAISE EXCEPTION 'analysis job owner mismatch';
    END IF;

    INSERT INTO analysis_job_queue (analysis_job_id, user_id)
    VALUES (p_analysis_job_id, p_user_id)
    ON CONFLICT (analysis_job_id)
    DO UPDATE SET
        available_at = now(),
        locked_until = NULL,
        worker_id = NULL;
END;
$$;

REVOKE ALL ON auth_identities, analysis_job_queue FROM PUBLIC;
REVOKE ALL ON FUNCTION create_auth_identity(uuid, citext, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION auth_lookup_user(citext) FROM PUBLIC;
REVOKE ALL ON FUNCTION claim_analysis_job(varchar) FROM PUBLIC;
REVOKE ALL ON FUNCTION finish_analysis_job(uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION requeue_analysis_job(uuid, uuid) FROM PUBLIC;

GRANT USAGE ON SCHEMA public TO jobiss_app;
GRANT SELECT ON competency_catalog TO jobiss_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON
    users,
    career_graphs,
    job_postings,
    analysis_jobs,
    graph_change_sets,
    career_nodes,
    career_edges,
    job_requirements,
    node_progress,
    evidence,
    notifications
TO jobiss_app;
GRANT EXECUTE ON FUNCTION app_current_user_id() TO jobiss_app;
GRANT EXECUTE ON FUNCTION create_auth_identity(uuid, citext, text) TO jobiss_app;
GRANT EXECUTE ON FUNCTION auth_lookup_user(citext) TO jobiss_app;
GRANT EXECUTE ON FUNCTION claim_analysis_job(varchar) TO jobiss_app;
GRANT EXECUTE ON FUNCTION finish_analysis_job(uuid, uuid) TO jobiss_app;
GRANT EXECUTE ON FUNCTION requeue_analysis_job(uuid, uuid) TO jobiss_app;

REVOKE ALL ON
    users,
    career_graphs,
    job_postings,
    analysis_jobs,
    graph_change_sets,
    career_nodes,
    career_edges,
    job_requirements,
    node_progress,
    evidence,
    notifications
FROM PUBLIC;
