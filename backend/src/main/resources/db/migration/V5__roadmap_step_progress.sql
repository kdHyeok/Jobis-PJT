-- 로드맵 스텝별 진행/재진단: 산출물 링크를 제출하면 가짜 AI가 재진단(요건 충족 여부)한 결과를
-- 스텝 단위로 영속한다. 로드맵 페이지의 "요건 × 증거" 매트릭스가 이 상태로 살아 움직인다.
CREATE TABLE roadmap_step_progress (
  id            BIGINT NOT NULL AUTO_INCREMENT,
  user_id       BIGINT NOT NULL,
  analysis_id   CHAR(36) NOT NULL,                 -- 어떤 분석에서
  route_id      VARCHAR(40) NOT NULL,              -- 어떤 경로(as_is|reinforce)
  step_no       INT NOT NULL,                      -- 로드맵 스텝 번호
  status        VARCHAR(20) NOT NULL,              -- VERIFIED | NEEDS_WORK
  submitted_url VARCHAR(500),                      -- 마지막으로 제출한 산출물 링크
  verdict_json  TEXT,                              -- 가짜 AI 재진단 결과(JSON)
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_step_progress_user (user_id),
  UNIQUE KEY uk_step_progress (user_id, analysis_id, route_id, step_no),
  CONSTRAINT fk_step_progress_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
