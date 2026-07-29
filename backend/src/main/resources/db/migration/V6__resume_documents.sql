-- 이력서 원문 보관.
-- 지금까지는 파편화 후 조각만 남고 원문이 사라져, 다시 쓰려면 매번 붙여넣어야 했다.
-- 원문을 남기면 (1) 재사용 (2) 조각이 어느 원문에서 왔는지 추적 (3) 갱신 이력이 가능해진다.
CREATE TABLE resume_documents (
  id          BIGINT NOT NULL AUTO_INCREMENT,
  user_id     BIGINT NOT NULL,
  title       VARCHAR(150) NOT NULL,          -- 사용자가 붙이는 이름 (예: "2026 상반기 이력서")
  source_type VARCHAR(20)  NOT NULL,          -- TEXT | GITHUB | FILE
  content     MEDIUMTEXT   NOT NULL,          -- 원문 그대로
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_resume_documents_user (user_id),
  CONSTRAINT fk_resume_documents_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 조각이 어느 원문에서 나왔는지 (없으면 NULL = 직접 추가한 조각).
-- FK 대신 느슨한 참조: 원문을 지워도 조각은 살아남아야 한다(조각이 곧 커리어 증거이므로).
ALTER TABLE evidences ADD COLUMN resume_document_id BIGINT NULL;
