-- 일반 대화("JOBIS에게 물어보기") 영속화.
-- 분석(analysis_runs)은 공고 하나를 판정하는 긴 작업이고, 이쪽은 자유 대화다.
-- 사이드바의 대화 목록과 새로고침 후 이어보기가 이 두 표에서 나온다.
CREATE TABLE conversations (
  id          BIGINT NOT NULL AUTO_INCREMENT,
  user_id     BIGINT NOT NULL,
  title       VARCHAR(120) NOT NULL,             -- 첫 발화에서 만든 제목(사용자가 목록에서 알아볼 이름)
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_conversations_user (user_id, updated_at),
  CONSTRAINT fk_conversations_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 한 대화의 발화들. agents 는 그 턴에 실제로 실행된 에이전트(오케스트레이터 가시화용).
CREATE TABLE conversation_messages (
  id              BIGINT NOT NULL AUTO_INCREMENT,
  conversation_id BIGINT NOT NULL,
  role            VARCHAR(16) NOT NULL,          -- USER | ASSISTANT
  content         TEXT NOT NULL,
  agents          VARCHAR(200),                  -- 쉼표로 이은 에이전트 이름(ASSISTANT 턴만)
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_conv_messages (conversation_id, id),
  CONSTRAINT fk_conv_messages_conv FOREIGN KEY (conversation_id) REFERENCES conversations(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
