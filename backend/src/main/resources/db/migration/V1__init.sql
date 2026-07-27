-- JOBISS 초기 스키마 (Golden Path) · MySQL 8 · utf8mb4
-- 설계 근거: §C DB 스키마

-- 1. 사용자 (인증)
CREATE TABLE users (
  id            BIGINT NOT NULL AUTO_INCREMENT,
  email         VARCHAR(255) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  name          VARCHAR(100) NOT NULL,
  job_title     VARCHAR(100),
  status        VARCHAR(50),
  completeness  INT NOT NULL DEFAULT 0,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_users_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2. 내 커리어 저장소 자료
CREATE TABLE evidences (
  id          BIGINT NOT NULL AUTO_INCREMENT,
  user_id     BIGINT NOT NULL,
  kind        VARCHAR(20) NOT NULL,            -- project|github|portfolio|stack|edu|cert
  label       VARCHAR(255) NOT NULL,
  description TEXT,
  status      VARCHAR(20) NOT NULL DEFAULT 'pending', -- ok|partial|missing|pending
  payload     JSON,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_evidences_user (user_id),
  CONSTRAINT fk_evidences_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3. 공고 (샘플 = user_id NULL·code 있음 / 사용자 입력 = user_id 있음)
CREATE TABLE job_postings (
  id          BIGINT NOT NULL AUTO_INCREMENT,
  code        VARCHAR(50),                     -- 'cloudwave' (샘플만)
  user_id     BIGINT,
  source_type VARCHAR(20) NOT NULL,            -- sample|url|raw|file
  company     VARCHAR(100),
  role        VARCHAR(150),
  career      VARCHAR(50),
  due         VARCHAR(30),
  url         VARCHAR(500),
  stack       JSON,
  raw_text    TEXT,
  parsed      JSON,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_job_postings_code (code),
  KEY idx_job_postings_user (user_id),
  CONSTRAINT fk_job_postings_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 4. 분석 실행 (Run)
CREATE TABLE analysis_runs (
  id             BIGINT NOT NULL AUTO_INCREMENT,
  analysis_id    CHAR(36) NOT NULL,            -- UUID · API 경로 & AI 계약 공용 식별자 (백엔드 발급)
  user_id        BIGINT NOT NULL,
  job_posting_id BIGINT NOT NULL,
  status         VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                 -- PENDING|ANALYZING|AWAITING_ANSWERS|FINALIZING|COMPLETED|FAILED
  engine         VARCHAR(10) NOT NULL DEFAULT 'mock',   -- mock|rule|ai
  created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_runs_analysis_id (analysis_id),
  KEY idx_runs_user (user_id),
  CONSTRAINT fk_runs_user FOREIGN KEY (user_id) REFERENCES users(id),
  CONSTRAINT fk_runs_job  FOREIGN KEY (job_posting_id) REFERENCES job_postings(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 5. 이번 분석에 선택한 자료 (N:N)
CREATE TABLE run_evidences (
  run_id      BIGINT NOT NULL,
  evidence_id BIGINT NOT NULL,
  PRIMARY KEY (run_id, evidence_id),
  CONSTRAINT fk_re_run      FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE,
  CONSTRAINT fk_re_evidence FOREIGN KEY (evidence_id) REFERENCES evidences(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 6. 추가 질문
CREATE TABLE analysis_questions (
  id             BIGINT NOT NULL AUTO_INCREMENT,
  run_id         BIGINT NOT NULL,
  seq            INT NOT NULL,
  field          VARCHAR(50) NOT NULL,         -- project_role|performance_metric|cert_edu
  title          TEXT NOT NULL,
  why            TEXT,
  default_answer TEXT,
  effect         VARCHAR(255),
  PRIMARY KEY (id),
  KEY idx_questions_run (run_id),
  CONSTRAINT fk_questions_run FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 7. 질문 답변
CREATE TABLE analysis_answers (
  id          BIGINT NOT NULL AUTO_INCREMENT,
  run_id      BIGINT NOT NULL,
  question_id BIGINT NOT NULL,
  answer_text TEXT,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_answers_question (question_id),
  CONSTRAINT fk_answers_run      FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE,
  CONSTRAINT fk_answers_question FOREIGN KEY (question_id) REFERENCES analysis_questions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 8. 분석 결과 (§B 계약 통째로)
CREATE TABLE analysis_results (
  id         BIGINT NOT NULL AUTO_INCREMENT,
  run_id     BIGINT NOT NULL,
  result     JSON NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_results_run (run_id),
  CONSTRAINT fk_results_run FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 9. 산출물 제출
CREATE TABLE submissions (
  id         BIGINT NOT NULL AUTO_INCREMENT,
  run_id     BIGINT NOT NULL,
  github_url VARCHAR(500),
  deploy_url VARCHAR(500),
  note       TEXT,
  status     VARCHAR(20) NOT NULL DEFAULT 'DRAFT',   -- DRAFT|VALIDATING|REVIEWED
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_submissions_run (run_id),
  CONSTRAINT fk_submissions_run FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 10. 피드백 리포트
CREATE TABLE feedback_reports (
  id            BIGINT NOT NULL AUTO_INCREMENT,
  submission_id BIGINT NOT NULL,
  report        JSON NOT NULL,
  reviewed_at   DATETIME,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_feedback_submission (submission_id),
  CONSTRAINT fk_feedback_submission FOREIGN KEY (submission_id) REFERENCES submissions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
