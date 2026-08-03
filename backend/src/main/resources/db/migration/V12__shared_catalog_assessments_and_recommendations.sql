ALTER TABLE competency_catalog
    ADD COLUMN aliases jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN assessment_blueprint jsonb NOT NULL DEFAULT
        '{"requiredKinds":["CONCEPT","CODE","SCENARIO"],"minimumQuestions":3,"maximumQuestions":5,"passScore":75,"minimumQuestionScore":60}'::jsonb,
    ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();

ALTER TABLE competency_catalog
    ADD CONSTRAINT competency_catalog_aliases_array_check
        CHECK (jsonb_typeof(aliases) = 'array'),
    ADD CONSTRAINT competency_catalog_blueprint_object_check
        CHECK (jsonb_typeof(assessment_blueprint) = 'object');

CREATE TRIGGER competency_catalog_touch_updated_at
BEFORE UPDATE ON competency_catalog
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

INSERT INTO competency_catalog (
    canonical_key,
    title,
    domain,
    scope_definition,
    level_definition,
    self_confirmable,
    active
)
SELECT DISTINCT ON (canonical_key)
    canonical_key,
    title,
    domain,
    scope_definition,
    jsonb_build_object(
        '1', '핵심 개념을 설명하고 안내에 따라 적용할 수 있다.',
        '2', '일반적인 개발 문제에 독립적으로 적용할 수 있다.',
        '3', '트레이드오프를 판단하고 장애를 진단할 수 있다.',
        '4', '복잡한 운영 환경을 설계하고 개선할 수 있다.',
        '5', '조직 수준의 기준을 만들고 다른 개발자를 지도할 수 있다.'
    ),
    false,
    true
FROM user_competencies
WHERE roadmap_eligible
ORDER BY canonical_key, created_at
ON CONFLICT (canonical_key) DO NOTHING;

UPDATE user_competencies competency
SET catalog_competency_id = catalog.id
FROM competency_catalog catalog
WHERE competency.catalog_competency_id IS NULL
  AND catalog.canonical_key = competency.canonical_key;

CREATE OR REPLACE FUNCTION upsert_competency_catalog(
    p_canonical_key varchar,
    p_title varchar,
    p_domain varchar,
    p_scope_definition text
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    result_id uuid;
BEGIN
    IF app_current_user_id() IS NULL THEN
        RAISE EXCEPTION 'authenticated user context is required';
    END IF;
    IF p_canonical_key !~ '^[a-z0-9][a-z0-9._:-]{2,159}$' THEN
        RAISE EXCEPTION 'invalid competency canonical key';
    END IF;
    IF nullif(btrim(p_title), '') IS NULL
       OR nullif(btrim(p_scope_definition), '') IS NULL THEN
        RAISE EXCEPTION 'competency title and scope are required';
    END IF;

    INSERT INTO competency_catalog (
        canonical_key,
        title,
        domain,
        scope_definition,
        level_definition,
        self_confirmable,
        active
    )
    VALUES (
        p_canonical_key,
        left(btrim(p_title), 120),
        left(upper(btrim(p_domain)), 40),
        btrim(p_scope_definition),
        jsonb_build_object(
            '1', '핵심 개념을 설명하고 안내에 따라 적용할 수 있다.',
            '2', '일반적인 개발 문제에 독립적으로 적용할 수 있다.',
            '3', '트레이드오프를 판단하고 장애를 진단할 수 있다.',
            '4', '복잡한 운영 환경을 설계하고 개선할 수 있다.',
            '5', '조직 수준의 기준을 만들고 다른 개발자를 지도할 수 있다.'
        ),
        false,
        true
    )
    ON CONFLICT (canonical_key)
    DO UPDATE SET
        scope_definition = CASE
            WHEN length(excluded.scope_definition)
                > length(competency_catalog.scope_definition)
            THEN excluded.scope_definition
            ELSE competency_catalog.scope_definition
        END,
        active = true,
        updated_at = now()
    RETURNING id INTO result_id;

    RETURN result_id;
END;
$$;

CREATE TABLE posting_catalog (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    fingerprint varchar(64) NOT NULL UNIQUE,
    source_url text,
    company_name varchar(160) NOT NULL,
    role_title varchar(200) NOT NULL,
    employment_type varchar(80),
    experience_text varchar(160),
    primary_track varchar(40) NOT NULL,
    experience_requirement_type varchar(20) NOT NULL
        CHECK (experience_requirement_type IN ('NONE', 'REQUIRED', 'PREFERRED')),
    minimum_experience_months integer NOT NULL DEFAULT 0
        CHECK (minimum_experience_months BETWEEN 0 AND 600),
    maximum_experience_months integer
        CHECK (maximum_experience_months BETWEEN 0 AND 600),
    active boolean NOT NULL DEFAULT true,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        maximum_experience_months IS NULL
        OR maximum_experience_months >= minimum_experience_months
    )
);

CREATE TABLE posting_catalog_requirements (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    posting_catalog_id uuid NOT NULL
        REFERENCES posting_catalog(id) ON DELETE CASCADE,
    catalog_competency_id uuid NOT NULL
        REFERENCES competency_catalog(id),
    relation_kind varchar(24) NOT NULL
        CHECK (relation_kind IN ('REQUIRED', 'PREFERRED', 'RESPONSIBILITY')),
    required_scope text NOT NULL,
    required_level integer NOT NULL CHECK (required_level BETWEEN 1 AND 5),
    confidence numeric(4,3) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (posting_catalog_id, catalog_competency_id, relation_kind)
);

CREATE INDEX posting_catalog_track_experience_idx
    ON posting_catalog (
        primary_track,
        minimum_experience_months,
        last_seen_at DESC
    )
    WHERE active;

CREATE INDEX posting_catalog_requirements_posting_idx
    ON posting_catalog_requirements (posting_catalog_id, relation_kind);

CREATE TRIGGER posting_catalog_touch_updated_at
BEFORE UPDATE ON posting_catalog
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

CREATE OR REPLACE FUNCTION publish_analyzed_posting(
    p_posting_id uuid,
    p_primary_track varchar,
    p_experience_requirement_type varchar,
    p_minimum_experience_months integer,
    p_maximum_experience_months integer
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    owned_posting job_postings%ROWTYPE;
    catalog_id uuid;
    posting_fingerprint varchar(64);
BEGIN
    SELECT *
    INTO owned_posting
    FROM job_postings
    WHERE id = p_posting_id
      AND user_id = app_current_user_id()
      AND company_name IS NOT NULL
      AND role_title IS NOT NULL;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'owned analyzed posting was not found';
    END IF;

    posting_fingerprint := encode(
        digest(
            coalesce(
                nullif(lower(btrim(owned_posting.source_url)), ''),
                lower(
                    coalesce(owned_posting.company_name, '') || '|' ||
                    coalesce(owned_posting.role_title, '') || '|' ||
                    coalesce(owned_posting.experience_text, '') || '|' ||
                    owned_posting.raw_text
                )
            ),
            'sha256'
        ),
        'hex'
    );

    INSERT INTO posting_catalog (
        fingerprint,
        source_url,
        company_name,
        role_title,
        employment_type,
        experience_text,
        primary_track,
        experience_requirement_type,
        minimum_experience_months,
        maximum_experience_months
    )
    VALUES (
        posting_fingerprint,
        owned_posting.source_url,
        owned_posting.company_name,
        owned_posting.role_title,
        owned_posting.employment_type,
        owned_posting.experience_text,
        upper(p_primary_track),
        upper(p_experience_requirement_type),
        p_minimum_experience_months,
        p_maximum_experience_months
    )
    ON CONFLICT (fingerprint)
    DO UPDATE SET
        source_url = coalesce(excluded.source_url, posting_catalog.source_url),
        company_name = excluded.company_name,
        role_title = excluded.role_title,
        employment_type = excluded.employment_type,
        experience_text = excluded.experience_text,
        primary_track = excluded.primary_track,
        experience_requirement_type = excluded.experience_requirement_type,
        minimum_experience_months = excluded.minimum_experience_months,
        maximum_experience_months = excluded.maximum_experience_months,
        active = true,
        last_seen_at = now(),
        updated_at = now()
    RETURNING id INTO catalog_id;

    DELETE FROM posting_catalog_requirements
    WHERE posting_catalog_id = catalog_id;

    RETURN catalog_id;
END;
$$;

CREATE OR REPLACE FUNCTION publish_posting_catalog_requirement(
    p_private_posting_id uuid,
    p_posting_catalog_id uuid,
    p_catalog_competency_id uuid,
    p_relation_kind varchar,
    p_required_scope text,
    p_required_level integer,
    p_confidence numeric
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM job_postings
        WHERE id = p_private_posting_id
          AND user_id = app_current_user_id()
    ) THEN
        RAISE EXCEPTION 'owned posting was not found';
    END IF;

    INSERT INTO posting_catalog_requirements (
        posting_catalog_id,
        catalog_competency_id,
        relation_kind,
        required_scope,
        required_level,
        confidence
    )
    VALUES (
        p_posting_catalog_id,
        p_catalog_competency_id,
        upper(p_relation_kind),
        p_required_scope,
        p_required_level,
        p_confidence
    )
    ON CONFLICT (posting_catalog_id, catalog_competency_id, relation_kind)
    DO UPDATE SET
        required_scope = excluded.required_scope,
        required_level = excluded.required_level,
        confidence = excluded.confidence;
END;
$$;

WITH normalized_postings AS (
    SELECT DISTINCT ON (
        encode(
            digest(
                coalesce(
                    nullif(lower(btrim(posting.source_url)), ''),
                    lower(
                        coalesce(posting.company_name, '') || '|' ||
                        coalesce(posting.role_title, '') || '|' ||
                        coalesce(posting.experience_text, '') || '|' ||
                        posting.raw_text
                    )
                ),
                'sha256'
            ),
            'hex'
        )
    )
        encode(
            digest(
                coalesce(
                    nullif(lower(btrim(posting.source_url)), ''),
                    lower(
                        coalesce(posting.company_name, '') || '|' ||
                        coalesce(posting.role_title, '') || '|' ||
                        coalesce(posting.experience_text, '') || '|' ||
                        posting.raw_text
                    )
                ),
                'sha256'
            ),
            'hex'
        ) AS fingerprint,
        posting.source_url,
        posting.company_name,
        posting.role_title,
        posting.employment_type,
        posting.experience_text,
        profile.primary_track,
        profile.experience_requirement_type,
        profile.minimum_experience_months,
        profile.maximum_experience_months,
        posting.created_at,
        posting.updated_at
    FROM job_postings posting
    JOIN posting_path_profiles profile
      ON profile.posting_id = posting.id
    WHERE posting.company_name IS NOT NULL
      AND posting.role_title IS NOT NULL
      AND posting.archived_at IS NULL
    ORDER BY
        encode(
            digest(
                coalesce(
                    nullif(lower(btrim(posting.source_url)), ''),
                    lower(
                        coalesce(posting.company_name, '') || '|' ||
                        coalesce(posting.role_title, '') || '|' ||
                        coalesce(posting.experience_text, '') || '|' ||
                        posting.raw_text
                    )
                ),
                'sha256'
            ),
            'hex'
        ),
        posting.updated_at DESC
)
INSERT INTO posting_catalog (
    fingerprint,
    source_url,
    company_name,
    role_title,
    employment_type,
    experience_text,
    primary_track,
    experience_requirement_type,
    minimum_experience_months,
    maximum_experience_months,
    first_seen_at,
    last_seen_at
)
SELECT
    fingerprint,
    source_url,
    company_name,
    role_title,
    employment_type,
    experience_text,
    primary_track,
    experience_requirement_type,
    minimum_experience_months,
    maximum_experience_months,
    created_at,
    updated_at
FROM normalized_postings
ON CONFLICT (fingerprint)
DO UPDATE SET
    source_url = coalesce(excluded.source_url, posting_catalog.source_url),
    company_name = excluded.company_name,
    role_title = excluded.role_title,
    employment_type = excluded.employment_type,
    experience_text = excluded.experience_text,
    primary_track = excluded.primary_track,
    experience_requirement_type = excluded.experience_requirement_type,
    minimum_experience_months = excluded.minimum_experience_months,
    maximum_experience_months = excluded.maximum_experience_months,
    active = true,
    last_seen_at = greatest(
        posting_catalog.last_seen_at,
        excluded.last_seen_at
    ),
    updated_at = now();

WITH requirement_backfill AS (
    SELECT DISTINCT ON (
        public_posting.id,
        competency.catalog_competency_id,
        requirement.relation_kind
    )
        public_posting.id AS posting_catalog_id,
        competency.catalog_competency_id,
        requirement.relation_kind,
        requirement.required_scope,
        requirement.required_level,
        requirement.confidence,
        requirement.created_at
    FROM posting_competency_requirements requirement
    JOIN job_postings private_posting
      ON private_posting.id = requirement.posting_id
    JOIN user_competencies competency
      ON competency.id = requirement.competency_id
    JOIN posting_catalog public_posting
      ON public_posting.fingerprint = encode(
          digest(
              coalesce(
                  nullif(lower(btrim(private_posting.source_url)), ''),
                  lower(
                      coalesce(private_posting.company_name, '') || '|' ||
                      coalesce(private_posting.role_title, '') || '|' ||
                      coalesce(private_posting.experience_text, '') || '|' ||
                      private_posting.raw_text
                  )
              ),
              'sha256'
          ),
          'hex'
      )
    WHERE competency.catalog_competency_id IS NOT NULL
      AND requirement.roadmap_eligible
      AND private_posting.archived_at IS NULL
    ORDER BY
        public_posting.id,
        competency.catalog_competency_id,
        requirement.relation_kind,
        requirement.created_at DESC
)
INSERT INTO posting_catalog_requirements (
    posting_catalog_id,
    catalog_competency_id,
    relation_kind,
    required_scope,
    required_level,
    confidence
)
SELECT
    posting_catalog_id,
    catalog_competency_id,
    relation_kind,
    required_scope,
    required_level,
    confidence
FROM requirement_backfill
ON CONFLICT (posting_catalog_id, catalog_competency_id, relation_kind)
DO UPDATE SET
    required_scope = excluded.required_scope,
    required_level = excluded.required_level,
    confidence = excluded.confidence;

CREATE TABLE competency_assessment_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    competency_id uuid NOT NULL,
    target_posting_id uuid,
    required_level integer NOT NULL CHECK (required_level BETWEEN 1 AND 5),
    status varchar(24) NOT NULL
        CHECK (status IN ('IN_PROGRESS', 'PASSED', 'NEEDS_STUDY', 'ABANDONED')),
    question_count integer NOT NULL DEFAULT 0 CHECK (question_count BETWEEN 0 AND 5),
    average_score numeric(5,2),
    achieved_level integer NOT NULL DEFAULT 0 CHECK (achieved_level BETWEEN 0 AND 5),
    confidence numeric(4,3) CHECK (confidence BETWEEN 0 AND 1),
    summary text,
    strengths jsonb NOT NULL DEFAULT '[]'::jsonb,
    gaps jsonb NOT NULL DEFAULT '[]'::jsonb,
    next_actions jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id),
    CONSTRAINT competency_assessment_competency_owner_fk
        FOREIGN KEY (competency_id, user_id)
        REFERENCES user_competencies(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT competency_assessment_posting_owner_fk
        FOREIGN KEY (target_posting_id, user_id)
        REFERENCES job_postings(id, user_id)
        ON DELETE SET NULL (target_posting_id)
);

CREATE TABLE competency_assessment_turns (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id uuid NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal BETWEEN 1 AND 5),
    question_kind varchar(24) NOT NULL
        CHECK (question_kind IN ('CONCEPT', 'CODE', 'SCENARIO', 'FOLLOW_UP')),
    prompt text NOT NULL,
    code_snippet text,
    answer_text text,
    score integer CHECK (score BETWEEN 0 AND 100),
    verdict varchar(16) CHECK (verdict IN ('PASS', 'PARTIAL', 'FAIL')),
    feedback text,
    covered_criteria jsonb NOT NULL DEFAULT '[]'::jsonb,
    gaps jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    answered_at timestamptz,
    UNIQUE (id, user_id),
    UNIQUE (session_id, ordinal),
    CONSTRAINT competency_assessment_turn_session_owner_fk
        FOREIGN KEY (session_id, user_id)
        REFERENCES competency_assessment_sessions(id, user_id)
        ON DELETE CASCADE
);

CREATE UNIQUE INDEX competency_assessments_one_active_idx
    ON competency_assessment_sessions (user_id, competency_id)
    WHERE status = 'IN_PROGRESS';

CREATE INDEX competency_assessments_user_recent_idx
    ON competency_assessment_sessions (user_id, created_at DESC);

CREATE TRIGGER competency_assessment_sessions_touch_updated_at
BEFORE UPDATE ON competency_assessment_sessions
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

ALTER TABLE competency_assessment_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE competency_assessment_sessions FORCE ROW LEVEL SECURITY;
ALTER TABLE competency_assessment_turns ENABLE ROW LEVEL SECURITY;
ALTER TABLE competency_assessment_turns FORCE ROW LEVEL SECURITY;

CREATE POLICY competency_assessment_sessions_owner_policy
ON competency_assessment_sessions
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());

CREATE POLICY competency_assessment_turns_owner_policy
ON competency_assessment_turns
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());

ALTER TABLE ai_usage_hourly
    DROP CONSTRAINT ai_usage_hourly_usage_kind_check,
    ADD CONSTRAINT ai_usage_hourly_usage_kind_check
        CHECK (
            usage_kind IN (
                'CHAT',
                'ANALYSIS',
                'EVIDENCE',
                'CAREER',
                'ASSESSMENT'
            )
        );

GRANT SELECT ON competency_catalog, posting_catalog, posting_catalog_requirements
TO jobiss_app;

GRANT SELECT, INSERT, UPDATE, DELETE ON
    competency_assessment_sessions,
    competency_assessment_turns
TO jobiss_app;

REVOKE ALL ON posting_catalog, posting_catalog_requirements FROM PUBLIC;
REVOKE ALL ON competency_assessment_sessions, competency_assessment_turns FROM PUBLIC;
REVOKE ALL ON FUNCTION upsert_competency_catalog(varchar, varchar, varchar, text)
FROM PUBLIC;
REVOKE ALL ON FUNCTION publish_analyzed_posting(uuid, varchar, varchar, integer, integer)
FROM PUBLIC;
REVOKE ALL ON FUNCTION publish_posting_catalog_requirement(
    uuid,
    uuid,
    uuid,
    varchar,
    text,
    integer,
    numeric
)
FROM PUBLIC;

GRANT EXECUTE ON FUNCTION upsert_competency_catalog(
    varchar,
    varchar,
    varchar,
    text
) TO jobiss_app;
GRANT EXECUTE ON FUNCTION publish_analyzed_posting(
    uuid,
    varchar,
    varchar,
    integer,
    integer
) TO jobiss_app;
GRANT EXECUTE ON FUNCTION publish_posting_catalog_requirement(
    uuid,
    uuid,
    uuid,
    varchar,
    text,
    integer,
    numeric
) TO jobiss_app;
