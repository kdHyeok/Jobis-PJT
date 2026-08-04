-- Authoritative schema for the Airflow-managed jobrag database.
-- pgvector must be available on the PostgreSQL server. The local init-db.sh
-- installs it as postgres before Flyway connects as the jobrag owner.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS job_postings (
    source          TEXT NOT NULL,
    posting_id      TEXT NOT NULL,
    company         TEXT,
    title           TEXT,
    url             TEXT,
    employment_type TEXT,
    experience      TEXT,
    education       TEXT,
    location        TEXT,
    posted_date     TEXT,
    deadline        TEXT,
    deadline_date   DATE,
    detail_text     TEXT,
    text_source     TEXT NOT NULL,
    image_urls      JSONB NOT NULL DEFAULT '[]'::jsonb,
    need_ocr        CHAR(1) NOT NULL,
    collected_at    TIMESTAMPTZ,
    PRIMARY KEY (source, posting_id)
);

CREATE INDEX IF NOT EXISTS idx_job_postings_need_ocr
    ON job_postings (need_ocr);
CREATE INDEX IF NOT EXISTS idx_job_postings_deadline_date
    ON job_postings (deadline_date);

CREATE TABLE IF NOT EXISTS postings (
    uid             TEXT PRIMARY KEY,
    posting_id      TEXT NOT NULL,
    source          TEXT NOT NULL,
    company         TEXT NOT NULL,
    title           TEXT NOT NULL,
    url             TEXT NOT NULL,
    employment_type TEXT,
    exp_min         INT,
    exp_max         INT,
    regions         TEXT[] NOT NULL DEFAULT '{}',
    location_raw    TEXT,
    deadline        TEXT,
    tech            TEXT[] NOT NULL DEFAULT '{}',
    role_category   TEXT,
    needs_review    BOOLEAN NOT NULL DEFAULT false,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    collected_at    TEXT,
    raw             JSONB,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, posting_id)
);

-- The first Flyway run can adopt a database that was created by the old
-- schema.sql path. These statements bring known older installations forward.
ALTER TABLE postings ADD COLUMN IF NOT EXISTS role_category TEXT;
ALTER TABLE postings ADD COLUMN IF NOT EXISTS exp_max INT;

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id        TEXT PRIMARY KEY,
    posting_uid     TEXT NOT NULL REFERENCES postings(uid) ON DELETE CASCADE,
    part            TEXT NOT NULL,
    text            TEXT NOT NULL,
    tokens          INT NOT NULL,
    content_hash    TEXT NOT NULL,
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
