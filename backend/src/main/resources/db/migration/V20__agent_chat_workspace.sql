ALTER TABLE chat_reply_jobs
    ADD COLUMN request_context jsonb NOT NULL DEFAULT '{"mode":"CAREER_CHAT","postingIds":[],"careerSourceIds":[]}'::jsonb,
    ADD COLUMN progress_events jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN result_data jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE chat_reply_jobs
    ADD CONSTRAINT chat_reply_jobs_request_mode_check
    CHECK (
        coalesce(request_context ->> 'mode', 'CAREER_CHAT') IN (
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
    );

COMMENT ON COLUMN chat_reply_jobs.request_context IS
    '사용자가 명시적으로 선택한 읽기 전용 공고·커리어 자료와 에이전트 작업 모드';
COMMENT ON COLUMN chat_reply_jobs.progress_events IS
    '백엔드 오케스트레이션과 AI가 보고한 사용자 공개 진행 단계';
COMMENT ON COLUMN chat_reply_jobs.result_data IS
    '근거, 확인 질문, 제안 작업, 생성 산출물을 포함한 AI 응답 원본';
