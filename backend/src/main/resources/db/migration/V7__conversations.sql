-- 대화를 1급 객체로 승격.
-- 지금까지 목록에 남는 것은 "분석"뿐이었다. 그래서 공고 없이 시작한 대화는 어디에도 남지 않고,
-- 분석을 시작하면 그 앞의 대화가 화면에서 사라졌다.
-- ChatGPT/Claude 처럼 "대화"가 목록의 단위가 되고, 분석은 그 대화 안에서 일어난 사건이 된다.
--   conversations          : 대화 스레드
--   conversation_messages  : 그 안의 발화. role=ANALYSIS 인 줄이 분석 카드(analysis_id 참조)
--   analysis_runs.conversation_id : 분석이 어느 대화에서 태어났는지
CREATE TABLE conversations (
  id              BIGINT NOT NULL AUTO_INCREMENT,
  conversation_id CHAR(36) NOT NULL,            -- UUID · API 경로 식별자 (analysis_id 와 같은 방식)
  user_id         BIGINT NOT NULL,
  title           VARCHAR(200) NOT NULL,        -- 첫 발화에서 만든 제목
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_conversations_cid (conversation_id),
  KEY idx_conversations_user (user_id, updated_at),
  CONSTRAINT fk_conversations_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- role: USER | ASSISTANT | ANALYSIS
--   USER/ASSISTANT = 말풍선(content 사용)
--   ANALYSIS       = 분석 카드. content 는 비고, analysis_id 로 실제 분석을 참조한다.
--                    분석 진행 내역 자체는 여기 쌓지 않는다 — 분석은 이미 analysis_runs 가 갖고 있고,
--                    다시 열 때 그 결과에서 복원하는 편이 항상 최신이다.
CREATE TABLE conversation_messages (
  id              BIGINT NOT NULL AUTO_INCREMENT,
  conversation_id BIGINT NOT NULL,
  seq             INT NOT NULL,                 -- 대화 내 순서(1부터)
  role            VARCHAR(20) NOT NULL,
  content         MEDIUMTEXT,
  analysis_id     CHAR(36) NULL,                -- role=ANALYSIS 일 때만
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_cm_conv (conversation_id, seq),
  CONSTRAINT fk_cm_conversation FOREIGN KEY (conversation_id) REFERENCES conversations(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

ALTER TABLE analysis_runs ADD COLUMN conversation_id BIGINT NULL;
ALTER TABLE analysis_runs ADD CONSTRAINT fk_runs_conversation
  FOREIGN KEY (conversation_id) REFERENCES conversations(id);

-- 기존 분석 백필 — 목록이 "대화" 기준으로 바뀌므로, 지난 분석도 각자 대화 한 칸을 갖게 한다.
-- conversation_id 에 그 분석의 analysis_id(UUID)를 그대로 써서 별도 매핑 테이블 없이 이어 붙인다.
INSERT INTO conversations (conversation_id, user_id, title, created_at, updated_at)
SELECT r.analysis_id, r.user_id,
       COALESCE(NULLIF(TRIM(CONCAT_WS(' · ', j.company, j.role)), ''), '지난 분석'),
       r.created_at, r.updated_at
FROM analysis_runs r
JOIN job_postings j ON j.id = r.job_posting_id;

UPDATE analysis_runs r
JOIN conversations c ON c.conversation_id = r.analysis_id
SET r.conversation_id = c.id;

INSERT INTO conversation_messages (conversation_id, seq, role, content, analysis_id, created_at)
SELECT r.conversation_id, 1, 'ANALYSIS', NULL, r.analysis_id, r.created_at
FROM analysis_runs r
WHERE r.conversation_id IS NOT NULL;
