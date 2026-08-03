CREATE TABLE posting_path_profiles (
    posting_id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    analysis_job_id uuid NOT NULL,
    primary_track varchar(24) NOT NULL,
    experience_requirement_type varchar(16) NOT NULL,
    minimum_experience_months integer NOT NULL DEFAULT 0,
    maximum_experience_months integer,
    experience_source_text text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (posting_id, user_id),
    CONSTRAINT posting_path_profile_track_check
        CHECK (
            primary_track IN (
                'BACKEND',
                'FRONTEND',
                'FULLSTACK',
                'DATA',
                'AI',
                'DEVOPS',
                'CLOUD',
                'SECURITY',
                'GAME',
                'MOBILE'
            )
        ),
    CONSTRAINT posting_path_profile_experience_type_check
        CHECK (
            experience_requirement_type IN (
                'NONE',
                'REQUIRED',
                'PREFERRED'
            )
        ),
    CONSTRAINT posting_path_profile_experience_range_check
        CHECK (
            minimum_experience_months >= 0
            AND (
                maximum_experience_months IS NULL
                OR maximum_experience_months >= minimum_experience_months
            )
        ),
    CONSTRAINT posting_path_profile_posting_owner_fk
        FOREIGN KEY (posting_id, user_id)
        REFERENCES job_postings(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT posting_path_profile_analysis_owner_fk
        FOREIGN KEY (analysis_job_id, user_id)
        REFERENCES analysis_jobs(id, user_id)
        ON DELETE CASCADE
);

WITH latest_analysis AS (
    SELECT DISTINCT ON (posting.id)
        posting.id AS posting_id,
        posting.user_id,
        job.id AS analysis_job_id,
        posting.role_title,
        posting.experience_text,
        posting.parsed_data,
        job.result_data,
        upper(
            coalesce(
                nullif(
                    job.result_data
                        -> 'job'
                        ->> 'primaryTrack',
                    ''
                ),
                nullif(posting.parsed_data ->> 'selectedTrack', '')
            )
        ) AS analyzed_track,
        upper(
            coalesce(
                nullif(
                    job.result_data
                        -> 'job'
                        -> 'experienceRequirement'
                        ->> 'type',
                    ''
                ),
                ''
            )
        ) AS analyzed_experience_type,
        nullif(
            job.result_data
                -> 'job'
                -> 'experienceRequirement'
                ->> 'minimumMonths',
            ''
        ) AS analyzed_minimum_months,
        nullif(
            job.result_data
                -> 'job'
                -> 'experienceRequirement'
                ->> 'maximumMonths',
            ''
        ) AS analyzed_maximum_months,
        nullif(
            job.result_data
                -> 'job'
                -> 'experienceRequirement'
                ->> 'sourceText',
            ''
        ) AS analyzed_experience_source
    FROM job_postings posting
    JOIN analysis_jobs job ON job.posting_id = posting.id
    WHERE job.status = 'SUCCEEDED'
    ORDER BY
        posting.id,
        job.completed_at DESC NULLS LAST,
        job.created_at DESC
),
normalized AS (
    SELECT
        latest.*,
        CASE
            WHEN analyzed_track IN (
                'BACKEND',
                'FRONTEND',
                'FULLSTACK',
                'DATA',
                'AI',
                'DEVOPS',
                'CLOUD',
                'SECURITY',
                'GAME',
                'MOBILE'
            ) THEN analyzed_track
            WHEN coalesce(role_title, '') ~* '(backend|server|백엔드|서버)'
                THEN 'BACKEND'
            WHEN coalesce(role_title, '') ~* '(frontend|프론트엔드)'
                THEN 'FRONTEND'
            WHEN coalesce(role_title, '') ~* '(data|데이터)'
                THEN 'DATA'
            WHEN coalesce(role_title, '') ~* '(machine learning|ai|머신러닝)'
                THEN 'AI'
            WHEN coalesce(role_title, '') ~* '(devops|sre|인프라|클라우드)'
                THEN 'DEVOPS'
            WHEN coalesce(role_title, '') ~* '(security|보안)'
                THEN 'SECURITY'
            WHEN coalesce(role_title, '') ~* '(game|게임)'
                THEN 'GAME'
            WHEN coalesce(role_title, '') ~* '(android|ios|mobile|모바일)'
                THEN 'MOBILE'
            ELSE 'BACKEND'
        END AS primary_track,
        CASE
            WHEN analyzed_minimum_months IS NOT NULL
                THEN analyzed_minimum_months::integer
            WHEN upper(
                coalesce(
                    parsed_data ->> 'selectedExperienceLevel',
                    parsed_data ->> 'selectedCareerStage',
                    ''
                )
            )
                IN ('ENTRY', 'NEW', 'JUNIOR', '신입')
                THEN 0
            WHEN coalesce(experience_text, '') ~ '([0-9]+)'
                THEN (
                    regexp_match(
                        experience_text,
                        '([0-9]+)'
                    )
                )[1]::integer * 12
            ELSE 0
        END AS minimum_months
    FROM latest_analysis latest
)
INSERT INTO posting_path_profiles (
    posting_id,
    user_id,
    analysis_job_id,
    primary_track,
    experience_requirement_type,
    minimum_experience_months,
    maximum_experience_months,
    experience_source_text
)
SELECT
    posting_id,
    user_id,
    analysis_job_id,
    primary_track,
    CASE
        WHEN minimum_months = 0 THEN 'NONE'
        WHEN analyzed_experience_type IN ('REQUIRED', 'PREFERRED')
            THEN analyzed_experience_type
        WHEN coalesce(experience_text, '') LIKE '%우대%'
            THEN 'PREFERRED'
        ELSE 'REQUIRED'
    END,
    minimum_months,
    CASE
        WHEN analyzed_maximum_months IS NOT NULL
            THEN analyzed_maximum_months::integer
        WHEN coalesce(experience_text, '')
            ~ '[0-9]+[^0-9]+([0-9]+)'
            THEN (
                regexp_match(
                    experience_text,
                    '[0-9]+[^0-9]+([0-9]+)'
                )
            )[1]::integer * 12
        ELSE NULL
    END,
    coalesce(
        analyzed_experience_source,
        nullif(experience_text, ''),
        '경력 제한 없음'
    )
FROM normalized;

UPDATE posting_competency_requirements requirement
SET
    roadmap_eligible = true,
    roadmap_domain = 'CAREER',
    roadmap_stage = 'EXPERIENCE',
    verification_method = coalesce(
        requirement.verification_method,
        '경력 자료와 재직 기간으로 확인'
    )
FROM posting_path_profiles profile, user_competencies competency
WHERE profile.posting_id = requirement.posting_id
  AND competency.id = requirement.competency_id
  AND profile.experience_requirement_type = 'REQUIRED'
  AND profile.minimum_experience_months > 0
  AND requirement.relation_kind = 'REQUIRED'
  AND competency.competency_kind = 'EXPERIENCE';

UPDATE user_competencies competency
SET
    roadmap_eligible = true,
    verification_method = coalesce(
        competency.verification_method,
        '경력 자료와 재직 기간으로 확인'
    )
WHERE competency.competency_kind = 'EXPERIENCE'
  AND EXISTS (
    SELECT 1
    FROM posting_competency_requirements requirement
    JOIN posting_path_profiles profile
      ON profile.posting_id = requirement.posting_id
    WHERE requirement.competency_id = competency.id
      AND profile.experience_requirement_type = 'REQUIRED'
      AND profile.minimum_experience_months > 0
      AND requirement.relation_kind = 'REQUIRED'
);

UPDATE graph_change_sets change_set
SET proposal = jsonb_set(
    change_set.proposal,
    '{competencies}',
    coalesce(
        (
            SELECT jsonb_agg(
                CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM posting_competency_requirements requirement
                        JOIN user_competencies competency
                          ON competency.id = requirement.competency_id
                        JOIN posting_path_profiles profile
                          ON profile.posting_id = requirement.posting_id
                        WHERE requirement.analysis_job_id =
                            change_set.analysis_job_id
                          AND competency.canonical_key =
                            item ->> 'canonicalKey'
                          AND competency.competency_kind = 'EXPERIENCE'
                          AND profile.experience_requirement_type = 'REQUIRED'
                          AND profile.minimum_experience_months > 0
                          AND requirement.relation_kind = 'REQUIRED'
                    ) THEN item || jsonb_build_object(
                        'roadmapEligible',
                        true,
                        'verificationMethod',
                        coalesce(
                            item ->> 'verificationMethod',
                            '경력 자료와 재직 기간으로 확인'
                        )
                    )
                    ELSE item
                END
                ORDER BY ordinal
            )
            FROM jsonb_array_elements(
                coalesce(
                    change_set.proposal -> 'competencies',
                    '[]'::jsonb
                )
            ) WITH ORDINALITY AS competency(item, ordinal)
        ),
        '[]'::jsonb
    )
);

CREATE INDEX posting_path_profiles_user_track_idx
    ON posting_path_profiles (
        user_id,
        primary_track,
        minimum_experience_months
    );

CREATE TRIGGER posting_path_profiles_touch_updated_at
BEFORE UPDATE ON posting_path_profiles
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

ALTER TABLE posting_path_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE posting_path_profiles FORCE ROW LEVEL SECURITY;

CREATE POLICY posting_path_profiles_owner_policy ON posting_path_profiles
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON posting_path_profiles TO jobiss_app;
REVOKE ALL ON posting_path_profiles FROM PUBLIC;
