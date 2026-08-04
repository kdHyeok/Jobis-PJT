-- 대화 한 턴의 에이전트 진행 타임라인.
--
-- chat_reply_jobs.stage/stage_message 는 한 칸이라 마지막 단계만 남는다. 어느 에이전트가
-- 무슨 도구로 무엇을 했는지 순서대로 보여주려면 기록이 남아야 한다 — 공고 분석 쪽
-- analysis_agent_events 와 같은 구조·같은 RLS 규칙을 쓴다(새 규약을 만들지 않는다).
CREATE TABLE chat_reply_agent_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    chat_reply_job_id uuid NOT NULL,
    sequence integer NOT NULL,
    event_data jsonb NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (chat_reply_job_id, sequence),
    CONSTRAINT chat_reply_agent_event_job_owner_fk
        FOREIGN KEY (chat_reply_job_id, user_id)
        REFERENCES chat_reply_jobs(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT chat_reply_agent_event_sequence_check
        CHECK (sequence BETWEEN 1 AND 10000),
    CONSTRAINT chat_reply_agent_event_data_check
        CHECK (jsonb_typeof(event_data) = 'object')
);

CREATE INDEX chat_reply_agent_events_job_sequence_idx
    ON chat_reply_agent_events (chat_reply_job_id, sequence);

ALTER TABLE chat_reply_agent_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_reply_agent_events FORCE ROW LEVEL SECURITY;

CREATE POLICY chat_reply_agent_events_owner_policy ON chat_reply_agent_events
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON chat_reply_agent_events TO jobiss_app;
REVOKE ALL ON chat_reply_agent_events FROM PUBLIC;
