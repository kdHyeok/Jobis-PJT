ALTER TYPE analysis_job_status
    ADD VALUE IF NOT EXISTS 'WAITING_FOR_INPUT';

ALTER TABLE analysis_jobs
    ADD COLUMN question_count integer NOT NULL DEFAULT 0,
    ADD CONSTRAINT analysis_jobs_question_count_check
        CHECK (question_count BETWEEN 0 AND 3);

CREATE TABLE analysis_questions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    analysis_job_id uuid NOT NULL,
    question_key varchar(80) NOT NULL,
    question_text text NOT NULL,
    reason text NOT NULL,
    options jsonb NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'PENDING',
    answer_value varchar(120),
    ordinal integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    answered_at timestamptz,
    UNIQUE (id, user_id),
    UNIQUE (analysis_job_id, ordinal),
    UNIQUE (analysis_job_id, question_key),
    CONSTRAINT analysis_question_job_owner_fk
        FOREIGN KEY (analysis_job_id, user_id)
        REFERENCES analysis_jobs(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT analysis_question_text_check
        CHECK (char_length(question_text) BETWEEN 1 AND 1000),
    CONSTRAINT analysis_question_reason_check
        CHECK (char_length(reason) BETWEEN 1 AND 1000),
    CONSTRAINT analysis_question_options_check
        CHECK (
            jsonb_typeof(options) = 'array'
            AND jsonb_array_length(options) BETWEEN 2 AND 4
        ),
    CONSTRAINT analysis_question_status_check
        CHECK (status IN ('PENDING', 'ANSWERED')),
    CONSTRAINT analysis_question_answer_check
        CHECK (
            (status = 'PENDING' AND answer_value IS NULL AND answered_at IS NULL)
            OR
            (status = 'ANSWERED' AND answer_value IS NOT NULL AND answered_at IS NOT NULL)
        ),
    CONSTRAINT analysis_question_ordinal_check
        CHECK (ordinal BETWEEN 1 AND 3)
);

CREATE INDEX analysis_questions_job_created_idx
    ON analysis_questions (analysis_job_id, ordinal);

ALTER TABLE analysis_questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis_questions FORCE ROW LEVEL SECURITY;

CREATE POLICY analysis_questions_owner_policy ON analysis_questions
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON analysis_questions TO jobiss_app;
REVOKE ALL ON analysis_questions FROM PUBLIC;
