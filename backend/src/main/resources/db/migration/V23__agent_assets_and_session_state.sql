-- 에이전트 자산의 집을 PostgreSQL 에 만든다 (작업로그/0803-무상태-전환-계획.md §1).
--
-- 지금까지 이 자산들은 AI 세션(sessions.sqlite3)에만 살아 있었다. PostgreSQL 은 처음부터
-- 정한 DB이고 SQLite 는 에이전트 검증용 임시였으므로, 대화가 만든 것들이 여기 남아야 한다.
-- **삭제하지 않는다** — 기존 열·테이블은 그대로 두고 옆에 더한다.

-- 1) 판정 산출물(엔진 형식) --------------------------------------------------------
-- analysis_jobs.result_data 는 **v2 계약 형식**(job·evaluation·competencyProposal)이다.
-- 엔진 형식(fitGrade·gaps·roadmap·judgmentSummary)을 그 안에 섞으면 백엔드 파서가 읽는
-- 계약이 흐려지므로 옆 칼럼에 둔다. 이 값이 있으면 채팅과 분석 작업이 **같은 판정**을 본다
-- (지금은 세션이 갈려 같은 공고·이력서로 판정이 두 번 돈다).
ALTER TABLE analysis_jobs
    ADD COLUMN engine_result jsonb;

COMMENT ON COLUMN analysis_jobs.engine_result IS
    'AI 엔진 형식 판정 결과(fitGrade·gaps·roadmap·judgmentSummary) — result_data(v2 형식)의 짝';

-- 2) 준비 예산 ------------------------------------------------------------------
ALTER TABLE user_goal_profiles
    ADD COLUMN preparation_period_weeks integer,
    ADD COLUMN available_hours_per_week integer;

ALTER TABLE user_goal_profiles
    ADD CONSTRAINT user_goal_preparation_weeks_check
        CHECK (preparation_period_weeks IS NULL
               OR preparation_period_weeks BETWEEN 1 AND 260),
    ADD CONSTRAINT user_goal_available_hours_check
        CHECK (available_hours_per_week IS NULL
               OR available_hours_per_week BETWEEN 1 AND 168);

-- 3) 정규화 프로필 --------------------------------------------------------------
-- 이력서 원문에서 파생한 **캐시**다. career_fragments/career_nodes 는 사용자가 확정한
-- 커리어 모델이라 층이 다르다 — 파생 추정본을 거기 섞으면 확정본과 뒤섞인다.
CREATE TABLE ai_user_profiles (
    user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    profile jsonb NOT NULL,
    source_fingerprint varchar(64),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ai_user_profile_shape_check CHECK (jsonb_typeof(profile) = 'object')
);

COMMENT ON TABLE ai_user_profiles IS
    'AI 가 이력서에서 뽑은 정규화 프로필(파생 캐시) — 확정 커리어 모델(career_*)과 층이 다르다';

-- 4) 대화 산출물 ----------------------------------------------------------------
CREATE TABLE posting_recommendations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id uuid REFERENCES conversations(id) ON DELETE SET NULL,
    recommendations jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT posting_recommendations_shape_check
        CHECK (jsonb_typeof(recommendations) = 'array')
);

CREATE TABLE coverletter_drafts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id uuid REFERENCES conversations(id) ON DELETE SET NULL,
    posting_id uuid,
    draft jsonb NOT NULL,
    -- 생성물은 초안까지다(AGENTS.md §2-8: 최종 확정은 사람) — 상태를 값으로 못 박는다.
    status varchar(40) NOT NULL DEFAULT 'draft_pending_review',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT coverletter_draft_shape_check CHECK (jsonb_typeof(draft) = 'object'),
    CONSTRAINT coverletter_draft_owner_fk
        FOREIGN KEY (posting_id, user_id) REFERENCES job_postings(id, user_id)
        ON DELETE SET NULL (posting_id)
);

CREATE TABLE interview_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id uuid REFERENCES conversations(id) ON DELETE SET NULL,
    -- {asked, answers, usedTopics} — 여러 턴에 걸친 진행 상태. 대화 이력에서 재파싱하는
    -- 것보다 정직하다(파싱은 표현이 바뀌면 조용히 깨진다).
    state jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT interview_session_shape_check CHECK (jsonb_typeof(state) = 'object')
);

CREATE TABLE application_plans (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id uuid REFERENCES conversations(id) ON DELETE SET NULL,
    posting_id uuid,
    plan jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT application_plan_shape_check CHECK (jsonb_typeof(plan) = 'object'),
    CONSTRAINT application_plan_owner_fk
        FOREIGN KEY (posting_id, user_id) REFERENCES job_postings(id, user_id)
        ON DELETE SET NULL (posting_id)
);

-- 5) 세션 잔여 상태 --------------------------------------------------------------
-- 도메인 자산이 아니면서 턴을 넘겨야 하는 것들: pendingRequest(남은 턴 카운터가 있어 대화
-- 이력으로 복원할 수 없다) · unsupported_requests(계측 누적). **여기에 도메인 자산을 넣지
-- 않는다** — 그러면 같은 사실이 두 곳에 남는다(그게 이 전환이 피하려는 것이다).
CREATE TABLE agent_session_state (
    conversation_id uuid PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    state jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT agent_session_state_shape_check CHECK (jsonb_typeof(state) = 'object')
);

COMMENT ON TABLE agent_session_state IS
    'AI 세션의 잔여 상태(도메인 자산이 아닌 것만) — 대화 맥락이 SQLite 없이 이어지게 한다';

-- 6) RLS — 기존 테이블들과 같은 규약 ------------------------------------------------
ALTER TABLE ai_user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_user_profiles FORCE ROW LEVEL SECURITY;
ALTER TABLE posting_recommendations ENABLE ROW LEVEL SECURITY;
ALTER TABLE posting_recommendations FORCE ROW LEVEL SECURITY;
ALTER TABLE coverletter_drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE coverletter_drafts FORCE ROW LEVEL SECURITY;
ALTER TABLE interview_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE interview_sessions FORCE ROW LEVEL SECURITY;
ALTER TABLE application_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE application_plans FORCE ROW LEVEL SECURITY;
ALTER TABLE agent_session_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_session_state FORCE ROW LEVEL SECURITY;

CREATE POLICY ai_user_profiles_owner_policy ON ai_user_profiles
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());
CREATE POLICY posting_recommendations_owner_policy ON posting_recommendations
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());
CREATE POLICY coverletter_drafts_owner_policy ON coverletter_drafts
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());
CREATE POLICY interview_sessions_owner_policy ON interview_sessions
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());
CREATE POLICY application_plans_owner_policy ON application_plans
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());
CREATE POLICY agent_session_state_owner_policy ON agent_session_state
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON ai_user_profiles TO jobiss_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON posting_recommendations TO jobiss_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON coverletter_drafts TO jobiss_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON interview_sessions TO jobiss_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON application_plans TO jobiss_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON agent_session_state TO jobiss_app;

REVOKE ALL ON ai_user_profiles FROM PUBLIC;
REVOKE ALL ON posting_recommendations FROM PUBLIC;
REVOKE ALL ON coverletter_drafts FROM PUBLIC;
REVOKE ALL ON interview_sessions FROM PUBLIC;
REVOKE ALL ON application_plans FROM PUBLIC;
REVOKE ALL ON agent_session_state FROM PUBLIC;

CREATE INDEX posting_recommendations_user_created_idx
    ON posting_recommendations (user_id, created_at DESC);
CREATE INDEX coverletter_drafts_user_created_idx
    ON coverletter_drafts (user_id, created_at DESC);
CREATE INDEX application_plans_user_created_idx
    ON application_plans (user_id, created_at DESC);
