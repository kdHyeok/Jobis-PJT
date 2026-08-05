\set ON_ERROR_STOP on

BEGIN;

CREATE EXTENSION IF NOT EXISTS dblink;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM legacy_import_audit WHERE source_database = 'jobiss') THEN
        RAISE EXCEPTION 'legacy jobiss import was already recorded';
    END IF;
    IF EXISTS (SELECT 1 FROM users)
       OR EXISTS (SELECT 1 FROM job_postings)
       OR EXISTS (SELECT 1 FROM conversations)
       OR EXISTS (SELECT 1 FROM analysis_jobs)
       OR EXISTS (SELECT 1 FROM career_sources)
       OR EXISTS (SELECT 1 FROM evidence)
       OR EXISTS (SELECT 1 FROM roadmap_versions) THEN
        RAISE EXCEPTION 'target v2 domain tables must be empty before legacy import';
    END IF;
END
$$;

CREATE OR REPLACE FUNCTION pg_temp.legacy_uuid(kind text, legacy_id bigint)
RETURNS uuid
LANGUAGE sql
IMMUTABLE
STRICT
AS $$
    SELECT (
        substr(value, 1, 8) || '-' || substr(value, 9, 4) || '-' ||
        substr(value, 13, 4) || '-' || substr(value, 17, 4) || '-' ||
        substr(value, 21, 12)
    )::uuid
    FROM (SELECT md5('jobiss-v2:' || kind || ':' || legacy_id::text) AS value) digest
$$;

CREATE TEMP TABLE legacy_users AS
SELECT *
FROM dblink(
    'dbname=jobiss',
    'SELECT id, created_at, email::text, name::text, password_hash::text, status::text, updated_at, withdrawn_at FROM public.users'
) AS source(
    id bigint,
    created_at timestamp,
    email text,
    name text,
    password_hash text,
    status text,
    updated_at timestamp,
    withdrawn_at timestamp
);

INSERT INTO users (id, email, display_name, status, created_at, updated_at)
SELECT
    pg_temp.legacy_uuid('user', id),
    email,
    left(name, 80),
    CASE
        WHEN withdrawn_at IS NOT NULL OR upper(status) = 'WITHDRAWN' THEN 'WITHDRAWN'
        WHEN upper(status) = 'SUSPENDED' THEN 'SUSPENDED'
        ELSE 'ACTIVE'
    END::account_status,
    created_at AT TIME ZONE 'Asia/Seoul',
    updated_at AT TIME ZONE 'Asia/Seoul'
FROM legacy_users;

INSERT INTO auth_identities (user_id, email, password_hash, status, created_at, updated_at)
SELECT
    pg_temp.legacy_uuid('user', id),
    email,
    password_hash,
    CASE
        WHEN withdrawn_at IS NOT NULL OR upper(status) = 'WITHDRAWN' THEN 'WITHDRAWN'
        WHEN upper(status) = 'SUSPENDED' THEN 'SUSPENDED'
        ELSE 'ACTIVE'
    END::account_status,
    created_at AT TIME ZONE 'Asia/Seoul',
    updated_at AT TIME ZONE 'Asia/Seoul'
FROM legacy_users;

INSERT INTO career_graphs (id, user_id, title, created_at, updated_at)
SELECT
    pg_temp.legacy_uuid('career-graph', id),
    pg_temp.legacy_uuid('user', id),
    '나의 커리어 지도',
    created_at AT TIME ZONE 'Asia/Seoul',
    updated_at AT TIME ZONE 'Asia/Seoul'
FROM legacy_users;

CREATE TEMP TABLE legacy_job_postings AS
SELECT *
FROM dblink(
    'dbname=jobiss',
    'SELECT id, career::text, code::text, company::text, created_at, due::text, parsed::text, raw_text, role::text, source_type::text, stack::text, url::text, user_id FROM public.job_postings'
) AS source(
    id bigint,
    career text,
    code text,
    company text,
    created_at timestamp,
    due text,
    parsed_json text,
    raw_text text,
    role text,
    source_type text,
    stack_json text,
    url text,
    user_id bigint
);

INSERT INTO job_postings (
    id, user_id, source_type, source_url, raw_text, company_name, role_title,
    experience_text, parsed_data, content_fingerprint, created_at, updated_at
)
SELECT
    pg_temp.legacy_uuid('posting', posting.id),
    pg_temp.legacy_uuid('user', posting.user_id),
    CASE WHEN upper(posting.source_type) = 'URL' THEN 'URL' ELSE 'TEXT' END::posting_source,
    posting.url,
    posting.raw_text,
    left(posting.company, 160),
    left(posting.role, 200),
    left(posting.career, 160),
    coalesce(posting.parsed_json::jsonb, '{}'::jsonb) ||
        jsonb_strip_nulls(jsonb_build_object(
            'legacyCode', posting.code,
            'legacyDue', posting.due,
            'legacyStack', posting.stack_json::jsonb,
            'legacySourceType', posting.source_type
        )),
    encode(
        digest(lower(regexp_replace(btrim(posting.raw_text), '\s+', ' ', 'g')), 'sha256'),
        'hex'
    ),
    posting.created_at AT TIME ZONE 'Asia/Seoul',
    posting.created_at AT TIME ZONE 'Asia/Seoul'
FROM legacy_job_postings posting
JOIN legacy_users legacy_user ON legacy_user.id = posting.user_id
WHERE posting.raw_text IS NOT NULL;

CREATE TEMP TABLE legacy_conversations AS
SELECT *
FROM dblink(
    'dbname=jobiss',
    'SELECT id, conversation_id::text, created_at, title::text, updated_at, user_id FROM public.conversations'
) AS source(
    id bigint,
    external_id text,
    created_at timestamp,
    title text,
    updated_at timestamp,
    user_id bigint
);

INSERT INTO conversations (
    id, user_id, title, context, last_message_at, created_at, updated_at
)
SELECT
    pg_temp.legacy_uuid('conversation', conversation.id),
    pg_temp.legacy_uuid('user', conversation.user_id),
    left(conversation.title, 160),
    jsonb_build_object('legacyConversationId', conversation.external_id),
    conversation.updated_at AT TIME ZONE 'Asia/Seoul',
    conversation.created_at AT TIME ZONE 'Asia/Seoul',
    conversation.updated_at AT TIME ZONE 'Asia/Seoul'
FROM legacy_conversations conversation
JOIN legacy_users legacy_user ON legacy_user.id = conversation.user_id;

CREATE TEMP TABLE legacy_analysis_runs AS
SELECT *
FROM dblink(
    'dbname=jobiss',
    $remote$
        SELECT run.id, run.analysis_id::text, run.created_at, run.engine::text,
               run.parent_analysis_id::text, run.selected_route::text, run.status::text,
               run.updated_at, run.conversation_id, run.job_posting_id, run.user_id,
               result.result::text
        FROM public.analysis_runs run
        LEFT JOIN LATERAL (
            SELECT analysis_result.result
            FROM public.analysis_results analysis_result
            WHERE analysis_result.run_id = run.id
            ORDER BY analysis_result.created_at DESC, analysis_result.id DESC
            LIMIT 1
        ) result ON true
    $remote$
) AS source(
    id bigint,
    analysis_id text,
    created_at timestamp,
    engine text,
    parent_analysis_id text,
    selected_route text,
    status text,
    updated_at timestamp,
    conversation_id bigint,
    job_posting_id bigint,
    user_id bigint,
    result_json text
);

INSERT INTO analysis_jobs (
    id, user_id, posting_id, status, attempt_count, error_code, error_message,
    result_data, created_at, started_at, completed_at, updated_at, stage, stage_message
)
SELECT
    pg_temp.legacy_uuid('analysis-run', run.id),
    pg_temp.legacy_uuid('user', run.user_id),
    pg_temp.legacy_uuid('posting', run.job_posting_id),
    CASE WHEN upper(run.status) = 'COMPLETED' THEN 'SUCCEEDED' ELSE 'FAILED' END::analysis_job_status,
    0,
    CASE
        WHEN upper(run.status) = 'ANALYZING' THEN 'LEGACY_CUTOVER'
        WHEN upper(run.status) = 'FAILED' THEN 'LEGACY_FAILED'
        ELSE NULL
    END,
    CASE WHEN upper(run.status) = 'ANALYZING'
        THEN '기존 버전에서 진행 중이던 분석은 안전한 재요청이 필요합니다.'
        ELSE NULL
    END,
    CASE WHEN run.result_json IS NULL THEN NULL ELSE run.result_json::jsonb END,
    run.created_at AT TIME ZONE 'Asia/Seoul',
    run.created_at AT TIME ZONE 'Asia/Seoul',
    CASE WHEN upper(run.status) = 'COMPLETED' THEN run.updated_at AT TIME ZONE 'Asia/Seoul' ELSE NULL END,
    run.updated_at AT TIME ZONE 'Asia/Seoul',
    'LEGACY_IMPORTED',
    CASE WHEN upper(run.status) = 'COMPLETED' THEN '기존 분석 결과를 가져왔습니다.' ELSE '기존 분석 기록을 가져왔습니다.' END
FROM legacy_analysis_runs run
JOIN legacy_users legacy_user ON legacy_user.id = run.user_id
JOIN legacy_job_postings posting
  ON posting.id = run.job_posting_id
 AND posting.user_id = run.user_id
 AND posting.raw_text IS NOT NULL;

CREATE TEMP TABLE legacy_messages AS
SELECT *
FROM dblink(
    'dbname=jobiss',
    'SELECT id, analysis_id::text, content, created_at, role::text, seq, conversation_id FROM public.conversation_messages'
) AS source(
    id bigint,
    analysis_id text,
    content text,
    created_at timestamp,
    role text,
    seq integer,
    conversation_id bigint
);

INSERT INTO conversation_messages (
    id, user_id, conversation_id, role, kind, content, analysis_job_id, metadata, created_at
)
SELECT
    pg_temp.legacy_uuid('message', message.id),
    pg_temp.legacy_uuid('user', conversation.user_id),
    pg_temp.legacy_uuid('conversation', message.conversation_id),
    CASE WHEN upper(message.role) = 'USER' THEN 'USER' ELSE 'ASSISTANT' END::message_role,
    CASE WHEN upper(message.role) = 'ANALYSIS' THEN 'ANALYSIS_STATUS' ELSE 'TEXT' END::message_kind,
    left(coalesce(message.content, '이전 버전의 분석 상태 메시지입니다.'), 100000),
    analysis.id,
    jsonb_strip_nulls(jsonb_build_object(
        'legacyAnalysisId', message.analysis_id,
        'legacySequence', message.seq,
        'legacyRole', message.role
    )),
    message.created_at AT TIME ZONE 'Asia/Seoul'
FROM legacy_messages message
JOIN legacy_conversations conversation ON conversation.id = message.conversation_id
LEFT JOIN legacy_analysis_runs legacy_analysis
  ON legacy_analysis.analysis_id = message.analysis_id
 AND legacy_analysis.user_id = conversation.user_id
LEFT JOIN analysis_jobs analysis
  ON analysis.id = pg_temp.legacy_uuid('analysis-run', legacy_analysis.id);

CREATE TEMP TABLE legacy_resume_documents AS
SELECT *
FROM dblink(
    'dbname=jobiss',
    'SELECT id, content, created_at, file_key::text, source_type::text, source_url::text, title::text, updated_at, user_id FROM public.resume_documents'
) AS source(
    id bigint,
    content text,
    created_at timestamp,
    file_key text,
    source_type text,
    source_url text,
    title text,
    updated_at timestamp,
    user_id bigint
);

INSERT INTO career_sources (
    id, user_id, source_type, title, source_url, raw_text, status, stage,
    stage_message, created_at, updated_at
)
SELECT
    pg_temp.legacy_uuid('resume', resume.id),
    pg_temp.legacy_uuid('user', resume.user_id),
    CASE WHEN upper(resume.source_type) IN ('TEXT', 'FILE', 'URL') THEN upper(resume.source_type) ELSE 'TEXT' END,
    left(resume.title, 180),
    resume.source_url,
    resume.content,
    'QUEUED',
    'QUEUED',
    '기존 이력 자료를 다시 분석할 예정입니다.',
    resume.created_at AT TIME ZONE 'Asia/Seoul',
    resume.updated_at AT TIME ZONE 'Asia/Seoul'
FROM legacy_resume_documents resume
JOIN legacy_users legacy_user ON legacy_user.id = resume.user_id
WHERE char_length(resume.content) BETWEEN 20 AND 100000;

CREATE TEMP TABLE legacy_evidences AS
SELECT *
FROM dblink(
    'dbname=jobiss',
    'SELECT id, created_at, description, kind::text, label::text, payload::text, resume_document_id, user_id FROM public.evidences'
) AS source(
    id bigint,
    created_at timestamp,
    description text,
    kind text,
    label text,
    payload_json text,
    resume_document_id bigint,
    user_id bigint
);

INSERT INTO evidence (
    id, user_id, evidence_type, title, content, verification_status, created_at, updated_at
)
SELECT
    pg_temp.legacy_uuid('evidence', legacy_evidence.id),
    pg_temp.legacy_uuid('user', legacy_evidence.user_id),
    left(legacy_evidence.kind, 40),
    left(legacy_evidence.label, 180),
    jsonb_strip_nulls(jsonb_build_object(
        'description', legacy_evidence.description,
        'legacyPayload', legacy_evidence.payload_json::jsonb,
        'legacyResumeDocumentId', legacy_evidence.resume_document_id
    )),
    'PENDING',
    legacy_evidence.created_at AT TIME ZONE 'Asia/Seoul',
    legacy_evidence.created_at AT TIME ZONE 'Asia/Seoul'
FROM legacy_evidences legacy_evidence
JOIN legacy_users legacy_user ON legacy_user.id = legacy_evidence.user_id;

CREATE TEMP TABLE legacy_roadmaps AS
SELECT *
FROM dblink(
    'dbname=jobiss',
    'SELECT id, analysis_id::text, created_at, goal_label::text, representative, roadmap_json, route_id::text, user_id FROM public.saved_roadmaps'
) AS source(
    id bigint,
    analysis_id text,
    created_at timestamp,
    goal_label text,
    representative boolean,
    roadmap_json text,
    route_id text,
    user_id bigint
);

WITH ranked AS (
    SELECT
        roadmap.*,
        row_number() OVER (PARTITION BY roadmap.user_id ORDER BY roadmap.created_at, roadmap.id) AS version_number,
        row_number() OVER (
            PARTITION BY roadmap.user_id
            ORDER BY roadmap.representative DESC, roadmap.created_at DESC, roadmap.id DESC
        ) AS publish_rank
    FROM legacy_roadmaps roadmap
    JOIN legacy_users legacy_user ON legacy_user.id = roadmap.user_id
)
INSERT INTO roadmap_versions (
    id, user_id, version_number, status, target_signature, snapshot,
    change_summary, created_at, published_at
)
SELECT
    pg_temp.legacy_uuid('roadmap', ranked.id),
    pg_temp.legacy_uuid('user', ranked.user_id),
    ranked.version_number,
    CASE WHEN ranked.representative AND ranked.publish_rank = 1 THEN 'PUBLISHED' ELSE 'SUPERSEDED' END,
    encode(digest('legacy-roadmap:' || ranked.id::text, 'sha256'), 'hex'),
    CASE WHEN ranked.roadmap_json IS JSON
        THEN ranked.roadmap_json::jsonb
        ELSE jsonb_build_object('legacyText', ranked.roadmap_json)
    END,
    jsonb_strip_nulls(jsonb_build_object(
        'legacyAnalysisId', ranked.analysis_id,
        'legacyRouteId', ranked.route_id,
        'legacyGoalLabel', ranked.goal_label
    )),
    ranked.created_at AT TIME ZONE 'Asia/Seoul',
    CASE WHEN ranked.representative AND ranked.publish_rank = 1
        THEN ranked.created_at AT TIME ZONE 'Asia/Seoul'
        ELSE NULL
    END
FROM ranked;

INSERT INTO legacy_import_audit (source_database, source_counts, imported_counts)
VALUES (
    'jobiss',
    jsonb_build_object(
        'users', (SELECT count(*) FROM legacy_users),
        'jobPostings', (SELECT count(*) FROM legacy_job_postings),
        'conversations', (SELECT count(*) FROM legacy_conversations),
        'messages', (SELECT count(*) FROM legacy_messages),
        'analysisRuns', (SELECT count(*) FROM legacy_analysis_runs),
        'resumeDocuments', (SELECT count(*) FROM legacy_resume_documents),
        'evidences', (SELECT count(*) FROM legacy_evidences),
        'roadmaps', (SELECT count(*) FROM legacy_roadmaps)
    ),
    jsonb_build_object(
        'users', (SELECT count(*) FROM users),
        'jobPostings', (SELECT count(*) FROM job_postings),
        'conversations', (SELECT count(*) FROM conversations),
        'messages', (SELECT count(*) FROM conversation_messages),
        'analysisJobs', (SELECT count(*) FROM analysis_jobs),
        'careerSources', (SELECT count(*) FROM career_sources),
        'evidences', (SELECT count(*) FROM evidence),
        'roadmapVersions', (SELECT count(*) FROM roadmap_versions)
    )
);

DROP EXTENSION dblink;

COMMIT;

SELECT source_database, source_counts, imported_counts, imported_at
FROM legacy_import_audit
WHERE source_database = 'jobiss';
