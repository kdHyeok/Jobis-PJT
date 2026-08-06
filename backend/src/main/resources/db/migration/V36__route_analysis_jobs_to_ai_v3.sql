ALTER TABLE analysis_jobs
    ADD COLUMN analysis_provider varchar(20) NOT NULL DEFAULT 'LEGACY',
    ADD COLUMN ai_contract_version varchar(80),
    ADD CONSTRAINT analysis_jobs_provider_check
        CHECK (analysis_provider IN ('LEGACY', 'V3'));

CREATE INDEX analysis_jobs_provider_status_idx
    ON analysis_jobs (analysis_provider, status, created_at);

ALTER TABLE analysis_jobs
    DROP CONSTRAINT analysis_jobs_question_count_check,
    ADD CONSTRAINT analysis_jobs_question_count_check
        CHECK (question_count BETWEEN 0 AND 10);

ALTER TABLE analysis_questions
    DROP CONSTRAINT analysis_question_options_check,
    DROP CONSTRAINT analysis_question_ordinal_check,
    ALTER COLUMN question_key TYPE varchar(160),
    ADD CONSTRAINT analysis_question_options_check
        CHECK (
            jsonb_typeof(options) = 'array'
            AND (
                (input_type = 'TEXT' AND jsonb_array_length(options) = 0)
                OR
                (input_type = 'CHOICE' AND jsonb_array_length(options) BETWEEN 2 AND 12)
            )
        ),
    ADD CONSTRAINT analysis_question_ordinal_check
        CHECK (ordinal BETWEEN 1 AND 10);

ALTER TABLE ai_v3_analysis_runs
    ADD COLUMN evidence_question_count integer NOT NULL DEFAULT 0,
    ADD CONSTRAINT ai_v3_run_evidence_question_count_check
        CHECK (evidence_question_count BETWEEN 0 AND 3);
