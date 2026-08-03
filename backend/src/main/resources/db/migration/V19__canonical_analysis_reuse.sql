-- Make existing private observations display the representative catalog name.
CREATE TABLE posting_analysis_leases (
    content_fingerprint varchar(64) NOT NULL,
    clarification_fingerprint varchar(64) NOT NULL,
    owner_analysis_job_id uuid NOT NULL REFERENCES analysis_jobs(id) ON DELETE CASCADE,
    lease_until timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (content_fingerprint, clarification_fingerprint)
);

CREATE TRIGGER posting_analysis_leases_touch_updated_at
BEFORE UPDATE ON posting_analysis_leases
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

GRANT SELECT, INSERT, UPDATE, DELETE ON posting_analysis_leases TO jobiss_app;

UPDATE job_postings posting
SET
    company_name = catalog.company_name,
    role_title = catalog.role_title
FROM posting_catalog catalog
WHERE posting.canonical_posting_id = catalog.id
  AND (
      posting.company_name IS DISTINCT FROM catalog.company_name
      OR posting.role_title IS DISTINCT FROM catalog.role_title
  );

-- Keep old completed result payloads consistent with the representative name.
UPDATE analysis_jobs job
SET result_data = jsonb_set(
    jsonb_set(
        job.result_data,
        '{job,companyName}',
        to_jsonb(catalog.company_name),
        true
    ),
    '{job,roleTitle}',
    to_jsonb(catalog.role_title),
    true
)
FROM job_postings posting
JOIN posting_catalog catalog ON catalog.id = posting.canonical_posting_id
WHERE job.posting_id = posting.id
  AND job.status = 'SUCCEEDED'
  AND job.result_data ? 'job';

-- Re-index successful legacy analyses with semantic clarification values.
-- This merges model vocabulary variants such as junior/entry/new_grad.
WITH normalized_answers AS (
    SELECT DISTINCT
        question.analysis_job_id,
        CASE
            WHEN lower(question.question_key) ~ '(track|role|position)'
                THEN 'target_track'
            WHEN lower(question.question_key) ~ '(career|experience|seniority|level)'
                THEN 'career_stage'
            ELSE lower(question.question_key)
        END AS normalized_key,
        CASE
            WHEN lower(question.question_key) ~ '(track|role|position)'
                 AND lower(question.answer_value) ~ '(backend|back_end|server)'
                THEN 'backend'
            WHEN lower(question.question_key) ~ '(track|role|position)'
                 AND lower(question.answer_value) ~ '(frontend|front_end)'
                THEN 'frontend'
            WHEN lower(question.question_key) ~ '(track|role|position)'
                 AND lower(question.answer_value) ~ '(fullstack|full_stack)'
                THEN 'fullstack'
            WHEN lower(question.question_key) ~ '(career|experience|seniority|level)'
                 AND lower(question.answer_value) ~ '(entry|junior|new_grad|newcomer|fresher)'
                THEN 'entry'
            WHEN lower(question.question_key) ~ '(career|experience|seniority|level)'
                 AND lower(question.answer_value) ~ '(irrelevant|not_required)'
                THEN 'experience_irrelevant'
            WHEN lower(question.question_key) ~ '(career|experience|seniority|level)'
                 AND lower(question.answer_value) ~ '(experienced|senior|career)'
                THEN 'experienced'
            ELSE lower(question.answer_value)
        END AS normalized_value
    FROM analysis_questions question
    WHERE question.status = 'ANSWERED'
), contexts AS (
    SELECT
        job.id AS analysis_job_id,
        posting.content_fingerprint,
        encode(
            digest(
                coalesce(
                    string_agg(
                        answer.normalized_key || '=' || answer.normalized_value,
                        '|' ORDER BY answer.normalized_key, answer.normalized_value
                    ),
                    ''
                ),
                'sha256'
            ),
            'hex'
        ) AS clarification_fingerprint,
        jsonb_build_object(
            'job', job.result_data -> 'job',
            'competencyProposal', job.result_data -> 'competencyProposal'
        ) AS normalized_analysis,
        job.completed_at
    FROM analysis_jobs job
    JOIN job_postings posting ON posting.id = job.posting_id
    LEFT JOIN normalized_answers answer
      ON answer.analysis_job_id = job.id
    WHERE job.status = 'SUCCEEDED'
      AND posting.content_fingerprint IS NOT NULL
      AND job.result_data ? 'job'
      AND job.result_data ? 'competencyProposal'
    GROUP BY
        job.id,
        posting.content_fingerprint,
        job.result_data,
        job.completed_at
), latest_contexts AS (
    SELECT DISTINCT ON (content_fingerprint, clarification_fingerprint)
        content_fingerprint,
        clarification_fingerprint,
        normalized_analysis
    FROM contexts
    ORDER BY
        content_fingerprint,
        clarification_fingerprint,
        completed_at DESC NULLS LAST,
        analysis_job_id
)
INSERT INTO posting_analysis_cache (
    content_fingerprint,
    clarification_fingerprint,
    normalized_analysis
)
SELECT
    content_fingerprint,
    clarification_fingerprint,
    normalized_analysis
FROM latest_contexts
ON CONFLICT (content_fingerprint, clarification_fingerprint)
DO UPDATE SET
    normalized_analysis = excluded.normalized_analysis,
    last_used_at = now();

-- Canonicalize display names already stored in shared cache payloads.
WITH canonical_display AS (
    SELECT DISTINCT ON (content_fingerprint)
        content_fingerprint,
        company_name,
        role_title
    FROM posting_catalog
    WHERE content_fingerprint IS NOT NULL
      AND moderation_status <> 'MERGED'
    ORDER BY content_fingerprint, updated_at DESC
)
UPDATE posting_analysis_cache cache
SET normalized_analysis = jsonb_set(
    jsonb_set(
        cache.normalized_analysis,
        '{job,companyName}',
        to_jsonb(display.company_name),
        true
    ),
    '{job,roleTitle}',
    to_jsonb(display.role_title),
    true
)
FROM canonical_display display
WHERE display.content_fingerprint = cache.content_fingerprint
  AND cache.normalized_analysis ? 'job';
