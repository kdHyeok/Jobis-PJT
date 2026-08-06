CREATE TABLE account_deletion_requests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL UNIQUE,
    account_fingerprint char(64) NOT NULL,
    status varchar(16) NOT NULL DEFAULT 'QUEUED'
        CHECK (status IN ('QUEUED', 'PURGING', 'COMPLETED', 'FAILED')),
    requested_at timestamptz NOT NULL DEFAULT now(),
    purge_after timestamptz NOT NULL DEFAULT now() + interval '1 hour',
    completed_at timestamptz,
    last_error text,
    CHECK (account_fingerprint ~ '^[0-9a-f]{64}$')
);

CREATE INDEX account_deletion_requests_due_idx
    ON account_deletion_requests (purge_after)
    WHERE status IN ('QUEUED', 'FAILED');

CREATE OR REPLACE FUNCTION delete_current_account(p_user_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_fingerprint text;
    v_anonymous_email citext;
BEGIN
    IF p_user_id IS DISTINCT FROM app_current_user_id() THEN
        RAISE EXCEPTION 'account owner mismatch';
    END IF;

    SELECT encode(digest(identity.email::text || ':' || p_user_id::text, 'sha256'), 'hex')
    INTO v_fingerprint
    FROM auth_identities identity
    WHERE identity.user_id = p_user_id
      AND identity.status = 'ACTIVE'
    FOR UPDATE;

    IF v_fingerprint IS NULL THEN
        RAISE EXCEPTION 'active account not found';
    END IF;

    v_anonymous_email := ('withdrawn+' || p_user_id::text || '@deleted.invalid')::citext;

    INSERT INTO account_deletion_requests (
        user_id, account_fingerprint, status, requested_at, purge_after
    ) VALUES (
        p_user_id, v_fingerprint, 'QUEUED', now(), now() + interval '1 hour'
    )
    ON CONFLICT (user_id) DO UPDATE
    SET status = 'QUEUED',
        requested_at = now(),
        purge_after = now() + interval '1 hour',
        completed_at = NULL,
        last_error = NULL;

    UPDATE auth_refresh_tokens
    SET revoked_at = coalesce(revoked_at, now())
    WHERE user_id = p_user_id;

    UPDATE auth_identities
    SET email = v_anonymous_email,
        password_hash = encode(digest(gen_random_uuid()::text, 'sha256'), 'hex'),
        status = 'WITHDRAWN',
        auth_version = auth_version + 1,
        updated_at = now()
    WHERE user_id = p_user_id;

    UPDATE users
    SET email = v_anonymous_email,
        display_name = '탈퇴한 사용자',
        status = 'WITHDRAWN',
        updated_at = now()
    WHERE id = p_user_id;
END;
$$;

CREATE OR REPLACE FUNCTION purge_due_withdrawn_accounts(p_limit integer DEFAULT 25)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_request record;
    v_count integer := 0;
BEGIN
    FOR v_request IN
        SELECT request.id, request.user_id
        FROM account_deletion_requests request
        WHERE request.status IN ('QUEUED', 'FAILED')
          AND request.purge_after <= now()
        ORDER BY request.purge_after
        FOR UPDATE SKIP LOCKED
        LIMIT greatest(1, least(coalesce(p_limit, 25), 100))
    LOOP
        BEGIN
            UPDATE account_deletion_requests
            SET status = 'PURGING', last_error = NULL
            WHERE id = v_request.id;

            DELETE FROM users
            WHERE id = v_request.user_id
              AND status = 'WITHDRAWN';

            UPDATE account_deletion_requests
            SET status = 'COMPLETED', completed_at = now(), last_error = NULL
            WHERE id = v_request.id;
            v_count := v_count + 1;
        EXCEPTION WHEN OTHERS THEN
            UPDATE account_deletion_requests
            SET status = 'FAILED', last_error = left(SQLERRM, 2000)
            WHERE id = v_request.id;
        END;
    END LOOP;
    RETURN v_count;
END;
$$;

REVOKE ALL ON account_deletion_requests FROM PUBLIC, jobiss_app;
REVOKE ALL ON FUNCTION delete_current_account(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION purge_due_withdrawn_accounts(integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION delete_current_account(uuid) TO jobiss_app;
GRANT EXECUTE ON FUNCTION purge_due_withdrawn_accounts(integer) TO jobiss_app;

ALTER TABLE job_postings DROP CONSTRAINT IF EXISTS job_postings_raw_text_check;
ALTER TABLE job_postings ADD CONSTRAINT job_postings_raw_text_check
    CHECK (char_length(raw_text) BETWEEN 20 AND 200000);
ALTER TABLE career_sources DROP CONSTRAINT IF EXISTS career_sources_raw_text_check;
ALTER TABLE career_sources ADD CONSTRAINT career_sources_raw_text_check
    CHECK (char_length(raw_text) BETWEEN 20 AND 200000);
