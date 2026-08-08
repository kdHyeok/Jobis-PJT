-- 대화로 수집한 선호·지속 사실을 사용자 프로필에 적재한다 (D141).
--
-- 지금까지 이 둘은 AI 세션(sessions.sqlite3)에만 있었다 — 대화가 끝나면, 혹은 세션이 지워지면
-- 사라진다. "사용자에게서 얻은 데이터는 백엔드 테이블에 적재한다"는 규칙의 나머지 절반이다.
--
-- 새 테이블을 만들지 않는다: user_goal_profiles 가 이미 사용자별(PK user_id) 목표·선호
-- 프로필의 집이고, 선호와 지속 사실은 그 프로필의 일부다. 표 하나가 늘면 조회하는 곳도 늘어난다.
--
-- jsonb 로 두는 이유: 선호는 축이 다섯 개(roles·domains·companies·regions·techStack)이고
-- 지속 사실은 문장 목록이다. 열로 펴면 축이 늘 때마다 마이그레이션이 필요하고, 그 축은
-- AI 쪽 preference_intake 가 정한다 — 스키마를 두 곳에서 정하지 않는다.
-- 대신 **모양은 CHECK 로 고정한다**: 선호는 객체, 사실은 문자열 배열.

ALTER TABLE user_goal_profiles
    ADD COLUMN chat_preferences jsonb,
    ADD COLUMN chat_facts jsonb;

ALTER TABLE user_goal_profiles
    ADD CONSTRAINT user_goal_chat_preferences_shape_check
        CHECK (chat_preferences IS NULL OR jsonb_typeof(chat_preferences) = 'object'),
    ADD CONSTRAINT user_goal_chat_facts_shape_check
        CHECK (chat_facts IS NULL OR jsonb_typeof(chat_facts) = 'array');

COMMENT ON COLUMN user_goal_profiles.chat_preferences IS
    '대화로 수집한 공고 선호 {roles, domains, companies, regions, techStack} (AI preference_intake 산출)';
COMMENT ON COLUMN user_goal_profiles.chat_facts IS
    '대화에서 사용자가 직접 말한 지속 사실(목표·제약·상황) 문장 배열 (AI user_facts 산출)';
