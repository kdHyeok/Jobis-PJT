ALTER TABLE chat_reply_jobs
    ADD CONSTRAINT chat_reply_jobs_request_mode_check_v2
    CHECK (
        coalesce(request_context ->> 'mode', 'CAREER_CHAT') IN (
            'AUTO',
            'CAREER_CHAT',
            'POSTING_QA',
            'RESUME_DIAGNOSIS',
            'POSTING_COMPARE',
            'RESUME_COMPARE',
            'INTERVIEW_PREP',
            'COVER_LETTER',
            'APPLICATION_PLAN',
            'JOB_DISCOVERY'
        )
    ) NOT VALID;

ALTER TABLE chat_reply_jobs
    VALIDATE CONSTRAINT chat_reply_jobs_request_mode_check_v2;

ALTER TABLE chat_reply_jobs
    DROP CONSTRAINT chat_reply_jobs_request_mode_check;

ALTER TABLE chat_reply_jobs
    RENAME CONSTRAINT chat_reply_jobs_request_mode_check_v2
    TO chat_reply_jobs_request_mode_check;
