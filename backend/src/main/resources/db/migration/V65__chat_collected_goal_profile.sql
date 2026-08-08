-- 대화에서 수집한 선호·사실·준비기간·주당 가용시간을 세션 블롭 밖(도메인 테이블)에도
-- 영속한다 — 로드맵 스케줄링과 다음 대화가 세션 없이도 이 정보를 쓸 수 있게.
-- persistence_map.py 가 선언한 user_goal_profiles 투영의 실제 구현이다.
alter table user_goal_profiles
    add column if not exists chat_preferences jsonb,
    add column if not exists chat_facts jsonb,
    add column if not exists preparation_period_weeks integer
        check (preparation_period_weeks is null
               or preparation_period_weeks between 1 and 260),
    add column if not exists available_hours_per_week integer
        check (available_hours_per_week is null
               or available_hours_per_week between 1 and 168);
