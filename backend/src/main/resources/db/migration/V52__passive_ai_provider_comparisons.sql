CREATE TABLE ai_provider_comparisons (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    legacy_analysis_job_id uuid NOT NULL,
    v3_analysis_job_id uuid NOT NULL,
    source_fingerprint varchar(80) NOT NULL,
    comparison_mode varchar(24) NOT NULL DEFAULT 'PASSIVE_PAIRED'
        CHECK (comparison_mode IN ('PASSIVE_PAIRED', 'FIXTURE')),
    comparison_version varchar(80) NOT NULL,
    status varchar(24) NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'COMPLETED', 'INCOMPARABLE', 'FAILED')),
    metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
    field_diff jsonb NOT NULL DEFAULT '{}'::jsonb,
    warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
    legacy_duration_ms bigint CHECK (legacy_duration_ms IS NULL OR legacy_duration_ms >= 0),
    v3_duration_ms bigint CHECK (v3_duration_ms IS NULL OR v3_duration_ms >= 0),
    review_decision varchar(24) NOT NULL DEFAULT 'PENDING'
        CHECK (review_decision IN (
            'PENDING',
            'LEGACY_BETTER',
            'V3_BETTER',
            'EQUIVALENT',
            'INCONCLUSIVE'
        )),
    review_note text,
    reviewed_by uuid REFERENCES users(id),
    reviewed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    UNIQUE (id, user_id),
    UNIQUE (user_id, legacy_analysis_job_id, v3_analysis_job_id),
    CONSTRAINT ai_provider_comparison_legacy_owner_fk
        FOREIGN KEY (legacy_analysis_job_id, user_id)
        REFERENCES analysis_jobs(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT ai_provider_comparison_v3_owner_fk
        FOREIGN KEY (v3_analysis_job_id, user_id)
        REFERENCES analysis_jobs(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT ai_provider_comparison_metrics_check
        CHECK (jsonb_typeof(metrics) = 'object'),
    CONSTRAINT ai_provider_comparison_diff_check
        CHECK (jsonb_typeof(field_diff) = 'object'),
    CONSTRAINT ai_provider_comparison_warnings_check
        CHECK (jsonb_typeof(warnings) = 'array'),
    CONSTRAINT ai_provider_comparison_completion_check
        CHECK (
            (status = 'PENDING' AND completed_at IS NULL)
            OR (status <> 'PENDING' AND completed_at IS NOT NULL)
        ),
    CONSTRAINT ai_provider_comparison_review_check
        CHECK (
            (review_decision = 'PENDING' AND reviewed_by IS NULL AND reviewed_at IS NULL)
            OR (review_decision <> 'PENDING' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)
        )
);

CREATE INDEX ai_provider_comparisons_review_idx
    ON ai_provider_comparisons (review_decision, created_at DESC);
CREATE INDEX ai_provider_comparisons_fingerprint_idx
    ON ai_provider_comparisons (source_fingerprint, created_at DESC);

ALTER TABLE ai_provider_comparisons ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_provider_comparisons FORCE ROW LEVEL SECURITY;

CREATE POLICY ai_provider_comparisons_owner_policy ON ai_provider_comparisons
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());

CREATE POLICY ai_provider_comparisons_operator_policy ON ai_provider_comparisons
    USING (EXISTS (
        SELECT 1 FROM users current_user_record
        WHERE current_user_record.id = app_current_user_id()
          AND current_user_record.account_role = 'OPERATOR'
    ))
    WITH CHECK (EXISTS (
        SELECT 1 FROM users current_user_record
        WHERE current_user_record.id = app_current_user_id()
          AND current_user_record.account_role = 'OPERATOR'
    ));

GRANT SELECT, INSERT, UPDATE, DELETE ON ai_provider_comparisons TO jobiss_app;
REVOKE ALL ON ai_provider_comparisons FROM PUBLIC;

-- Passive shadow never calls either AI provider. It only returns identifiers for
-- the newest completed legacy and V3 jobs that already share a content hash.
CREATE OR REPLACE FUNCTION find_passive_ai_provider_pairs(p_limit integer DEFAULT 10)
RETURNS TABLE (
    user_id uuid,
    legacy_analysis_job_id uuid,
    v3_analysis_job_id uuid,
    source_fingerprint varchar
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    WITH ranked AS (
        SELECT
            job.user_id,
            job.id AS analysis_job_id,
            job.analysis_provider,
            posting.content_fingerprint,
            row_number() OVER (
                PARTITION BY job.user_id, posting.content_fingerprint, job.analysis_provider
                ORDER BY job.completed_at DESC NULLS LAST, job.created_at DESC
            ) AS provider_rank
        FROM analysis_jobs job
        JOIN job_postings posting
          ON posting.id = job.posting_id
         AND posting.user_id = job.user_id
        WHERE job.status = 'SUCCEEDED'
          AND job.result_data IS NOT NULL
          AND jsonb_typeof(job.result_data) = 'object'
          AND posting.content_fingerprint IS NOT NULL
          AND posting.content_fingerprint <> ''
          AND job.analysis_provider IN ('LEGACY', 'V3')
    ), pairs AS (
        SELECT
            legacy.user_id,
            legacy.analysis_job_id AS legacy_analysis_job_id,
            v3.analysis_job_id AS v3_analysis_job_id,
            legacy.content_fingerprint
        FROM ranked legacy
        JOIN ranked v3
          ON v3.user_id = legacy.user_id
         AND v3.content_fingerprint = legacy.content_fingerprint
         AND v3.analysis_provider = 'V3'
         AND v3.provider_rank = 1
        WHERE legacy.analysis_provider = 'LEGACY'
          AND legacy.provider_rank = 1
          AND NOT EXISTS (
              SELECT 1
              FROM ai_provider_comparisons comparison
              WHERE comparison.user_id = legacy.user_id
                AND comparison.legacy_analysis_job_id = legacy.analysis_job_id
                AND comparison.v3_analysis_job_id = v3.analysis_job_id
          )
        ORDER BY legacy.analysis_job_id, v3.analysis_job_id
        LIMIT greatest(1, least(coalesce(p_limit, 10), 100))
    )
    SELECT
        pairs.user_id,
        pairs.legacy_analysis_job_id,
        pairs.v3_analysis_job_id,
        pairs.content_fingerprint::varchar
    FROM pairs;
$$;

REVOKE ALL ON FUNCTION find_passive_ai_provider_pairs(integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION find_passive_ai_provider_pairs(integer) TO jobiss_app;
