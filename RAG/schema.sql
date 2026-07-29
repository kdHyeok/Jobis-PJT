-- jobrag pgvector 스키마. CREATE EXTENSION vector 필요.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS postings (
    uid             TEXT PRIMARY KEY,                -- "{source}:{posting_id}"
    posting_id      TEXT NOT NULL,                   -- 소스 내에서만 유일
    source          TEXT NOT NULL,
    company         TEXT NOT NULL,
    title           TEXT NOT NULL,
    url             TEXT NOT NULL,
    employment_type TEXT,
    exp_min         INT,              -- 신입=0, 무관/미상=NULL
    exp_max         INT,              -- 범위 공고("3-8년")의 상한. 상한 없음(미상/개방)=NULL
    regions         TEXT[] NOT NULL DEFAULT '{}',  -- 계층 확장("서울","서울 강남구")
    location_raw    TEXT,             -- 파싱 실패 추적용 원문
    deadline        TEXT,
    tech            TEXT[] NOT NULL DEFAULT '{}',
    role_category   TEXT,              -- 12종 직군 enum, 룰 분류 실패 시 NULL(미분류)
    needs_review    BOOLEAN NOT NULL DEFAULT false,
    is_active       BOOLEAN NOT NULL DEFAULT true,   -- 배치에서 사라지면 false (삭제 금지 — 평가 재현성)
    collected_at    TEXT,
    raw             JSONB,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, posting_id)
);

-- 기존 DB에는 CREATE TABLE IF NOT EXISTS가 닿지 않으므로 별도로 추가
ALTER TABLE postings ADD COLUMN IF NOT EXISTS role_category TEXT;
ALTER TABLE postings ADD COLUMN IF NOT EXISTS exp_max INT;

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id        TEXT PRIMARY KEY,
    posting_uid     TEXT NOT NULL REFERENCES postings(uid) ON DELETE CASCADE,
    part            TEXT NOT NULL,          -- full | split
    text            TEXT NOT NULL,
    tokens          INT NOT NULL,
    content_hash    TEXT NOT NULL,          -- 재임베딩 스킵 판단 키
    forced_split    BOOLEAN NOT NULL DEFAULT false,
    needs_review    BOOLEAN NOT NULL DEFAULT false,
    embedding       VECTOR(1024),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_chunks_posting_uid ON chunks (posting_uid);
CREATE INDEX IF NOT EXISTS idx_postings_tech_gin ON postings USING gin (tech);
CREATE INDEX IF NOT EXISTS idx_postings_regions_gin ON postings USING gin (regions);
CREATE INDEX IF NOT EXISTS idx_postings_exp_min ON postings (exp_min);
CREATE INDEX IF NOT EXISTS idx_postings_role_category ON postings (role_category);
CREATE INDEX IF NOT EXISTS idx_postings_active ON postings (is_active);
CREATE INDEX IF NOT EXISTS idx_postings_source ON postings (source);
