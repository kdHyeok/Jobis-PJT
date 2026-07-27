-- 로드맵 저장(생성): 경로별로 AI가 정리한 로드맵을 저장. 대표 지정·목록 뷰는 다음 arc.
CREATE TABLE saved_roadmaps (
  id             BIGINT NOT NULL AUTO_INCREMENT,
  user_id        BIGINT NOT NULL,
  analysis_id    CHAR(36) NOT NULL,                 -- 어떤 분석에서
  route_id       VARCHAR(40) NOT NULL,              -- 어떤 경로(as_is|reinforce)
  goal_label     VARCHAR(200),                      -- 목표 맥락(디딤돌이면 목표 회사·직무), 없으면 NULL
  roadmap_json   TEXT NOT NULL,                     -- 가짜 AI가 생성한 로드맵 JSON
  representative TINYINT(1) NOT NULL DEFAULT 0,      -- 대표 로드맵 여부(다음 arc)
  created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_saved_roadmaps_user (user_id),
  UNIQUE KEY uk_saved_roadmaps (user_id, analysis_id, route_id),
  CONSTRAINT fk_saved_roadmaps_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
