CREATE TYPE conversation_status AS ENUM ('ACTIVE', 'ARCHIVED');
CREATE TYPE message_role AS ENUM ('USER', 'ASSISTANT', 'SYSTEM');
CREATE TYPE message_kind AS ENUM (
    'TEXT',
    'POSTING',
    'ANALYSIS_STATUS',
    'EVIDENCE_STATUS'
);

CREATE TABLE conversations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title varchar(160) NOT NULL DEFAULT '새 대화',
    status conversation_status NOT NULL DEFAULT 'ACTIVE',
    context jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_message_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id)
);

CREATE TABLE conversation_messages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id uuid NOT NULL,
    role message_role NOT NULL,
    kind message_kind NOT NULL DEFAULT 'TEXT',
    content text NOT NULL,
    posting_id uuid,
    analysis_job_id uuid,
    client_message_id uuid,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id),
    UNIQUE (conversation_id, client_message_id),
    CONSTRAINT conversation_message_owner_fk
        FOREIGN KEY (conversation_id, user_id)
        REFERENCES conversations(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT conversation_message_posting_owner_fk
        FOREIGN KEY (posting_id, user_id)
        REFERENCES job_postings(id, user_id)
        ON DELETE SET NULL (posting_id),
    CONSTRAINT conversation_message_analysis_owner_fk
        FOREIGN KEY (analysis_job_id, user_id)
        REFERENCES analysis_jobs(id, user_id)
        ON DELETE SET NULL (analysis_job_id),
    CHECK (char_length(content) BETWEEN 1 AND 100000)
);

ALTER TABLE job_postings
    ADD COLUMN conversation_id uuid,
    ADD COLUMN updated_by_user_at timestamptz,
    ADD CONSTRAINT job_posting_conversation_owner_fk
        FOREIGN KEY (conversation_id, user_id)
        REFERENCES conversations(id, user_id)
        ON DELETE SET NULL (conversation_id);

ALTER TABLE evidence
    ADD COLUMN attempt_count integer NOT NULL DEFAULT 0,
    ADD COLUMN error_message text,
    ADD COLUMN completed_at timestamptz,
    ADD CONSTRAINT evidence_verification_status_check
        CHECK (verification_status IN ('PENDING', 'RUNNING', 'VERIFIED', 'NEEDS_WORK', 'REJECTED', 'FAILED'));

CREATE TABLE evidence_verification_queue (
    evidence_id uuid PRIMARY KEY,
    user_id uuid NOT NULL,
    available_at timestamptz NOT NULL DEFAULT now(),
    locked_until timestamptz,
    worker_id varchar(120),
    attempt_count integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE career_nodes
    ADD COLUMN scope_fingerprint varchar(64)
        GENERATED ALWAYS AS (
            encode(
                digest(
                    lower(regexp_replace(coalesce(scope_definition, ''), '\s+', ' ', 'g')),
                    'sha256'
                ),
                'hex'
            )
        ) STORED;

ALTER TABLE career_nodes
    DROP CONSTRAINT career_nodes_graph_id_canonical_key_key;

CREATE UNIQUE INDEX career_nodes_active_identity_idx
    ON career_nodes (graph_id, canonical_key, level, scope_fingerprint)
    WHERE archived_at IS NULL;

CREATE INDEX conversations_user_recent_idx
    ON conversations (user_id, last_message_at DESC);
CREATE INDEX conversation_messages_conversation_created_idx
    ON conversation_messages (conversation_id, created_at, id);
CREATE INDEX job_postings_user_active_created_idx
    ON job_postings (user_id, created_at DESC)
    WHERE archived_at IS NULL;
CREATE INDEX evidence_verification_queue_available_idx
    ON evidence_verification_queue (available_at, locked_until, created_at);

CREATE TRIGGER conversations_touch_updated_at
BEFORE UPDATE ON conversations
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

CREATE OR REPLACE FUNCTION touch_conversation_from_message()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    UPDATE conversations
    SET
        last_message_at = NEW.created_at,
        title = CASE
            WHEN title = '새 대화' AND NEW.role = 'USER'
            THEN left(regexp_replace(NEW.content, '\s+', ' ', 'g'), 80)
            ELSE title
        END
    WHERE id = NEW.conversation_id
      AND user_id = NEW.user_id;
    RETURN NEW;
END;
$$;

CREATE TRIGGER conversation_messages_touch_conversation
AFTER INSERT ON conversation_messages
FOR EACH ROW EXECUTE FUNCTION touch_conversation_from_message();

CREATE OR REPLACE FUNCTION enqueue_evidence_verification()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    INSERT INTO evidence_verification_queue (evidence_id, user_id)
    VALUES (NEW.id, NEW.user_id)
    ON CONFLICT (evidence_id)
    DO UPDATE SET
        available_at = now(),
        locked_until = NULL,
        worker_id = NULL;
    RETURN NEW;
END;
$$;

CREATE TRIGGER evidence_enqueue_verification
AFTER INSERT ON evidence
FOR EACH ROW EXECUTE FUNCTION enqueue_evidence_verification();

CREATE OR REPLACE FUNCTION claim_evidence_verification(p_worker_id varchar)
RETURNS TABLE (
    id uuid,
    user_id uuid,
    attempt_count integer
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    RETURN QUERY
    WITH candidate AS (
        SELECT q.evidence_id
        FROM evidence_verification_queue q
        WHERE
            q.available_at <= now()
            AND (q.locked_until IS NULL OR q.locked_until < now())
            AND q.attempt_count < 3
        ORDER BY q.created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    ),
    claimed AS (
        UPDATE evidence_verification_queue q
        SET
            worker_id = p_worker_id,
            locked_until = now() + interval '5 minutes',
            attempt_count = q.attempt_count + 1
        FROM candidate c
        WHERE q.evidence_id = c.evidence_id
        RETURNING q.evidence_id, q.user_id, q.attempt_count
    )
    SELECT c.evidence_id, c.user_id, c.attempt_count
    FROM claimed c;
END;
$$;

CREATE OR REPLACE FUNCTION finish_evidence_verification(
    p_evidence_id uuid,
    p_user_id uuid
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    IF p_user_id IS DISTINCT FROM app_current_user_id() THEN
        RAISE EXCEPTION 'evidence owner mismatch';
    END IF;

    DELETE FROM evidence_verification_queue
    WHERE evidence_id = p_evidence_id
      AND user_id = p_user_id;
END;
$$;

CREATE OR REPLACE FUNCTION requeue_evidence_verification(
    p_evidence_id uuid,
    p_user_id uuid
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    IF p_user_id IS DISTINCT FROM app_current_user_id() THEN
        RAISE EXCEPTION 'evidence owner mismatch';
    END IF;

    INSERT INTO evidence_verification_queue (evidence_id, user_id)
    VALUES (p_evidence_id, p_user_id)
    ON CONFLICT (evidence_id)
    DO UPDATE SET
        available_at = now(),
        locked_until = NULL,
        worker_id = NULL;
END;
$$;

ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations FORCE ROW LEVEL SECURITY;
ALTER TABLE conversation_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_messages FORCE ROW LEVEL SECURITY;

CREATE POLICY conversations_owner_policy ON conversations
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());
CREATE POLICY conversation_messages_owner_policy ON conversation_messages
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());

REVOKE ALL ON evidence_verification_queue FROM PUBLIC;
REVOKE ALL ON FUNCTION claim_evidence_verification(varchar) FROM PUBLIC;
REVOKE ALL ON FUNCTION finish_evidence_verification(uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION requeue_evidence_verification(uuid, uuid) FROM PUBLIC;

GRANT SELECT, INSERT, UPDATE, DELETE ON
    conversations,
    conversation_messages
TO jobiss_app;
GRANT EXECUTE ON FUNCTION claim_evidence_verification(varchar) TO jobiss_app;
GRANT EXECUTE ON FUNCTION finish_evidence_verification(uuid, uuid) TO jobiss_app;
GRANT EXECUTE ON FUNCTION requeue_evidence_verification(uuid, uuid) TO jobiss_app;

REVOKE ALL ON conversations, conversation_messages FROM PUBLIC;
