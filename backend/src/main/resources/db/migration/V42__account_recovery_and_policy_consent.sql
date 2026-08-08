ALTER TABLE auth_identities
    ADD COLUMN auth_version bigint NOT NULL DEFAULT 1;

CREATE OR REPLACE FUNCTION update_current_auth_identity(
    p_user_id uuid,
    p_email citext,
    p_password_hash text
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    IF p_user_id IS DISTINCT FROM app_current_user_id() THEN
        RAISE EXCEPTION 'auth identity owner mismatch';
    END IF;

    UPDATE auth_identities
    SET email = COALESCE(p_email, email),
        password_hash = COALESCE(p_password_hash, password_hash),
        auth_version = auth_version + CASE WHEN p_password_hash IS NULL THEN 0 ELSE 1 END,
        updated_at = now()
    WHERE user_id = p_user_id;
END;
$$;

CREATE TABLE account_policy_consents (
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    policy_type varchar(24) NOT NULL CHECK (policy_type IN ('TERMS', 'PRIVACY')),
    policy_version varchar(32) NOT NULL,
    accepted_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, policy_type, policy_version)
);

ALTER TABLE account_policy_consents ENABLE ROW LEVEL SECURITY;
ALTER TABLE account_policy_consents FORCE ROW LEVEL SECURITY;

CREATE POLICY account_policy_consents_owner_policy
ON account_policy_consents
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());

CREATE TABLE password_reset_tokens (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash char(64) NOT NULL UNIQUE,
    expires_at timestamptz NOT NULL,
    used_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (token_hash ~ '^[0-9a-f]{64}$')
);

CREATE INDEX password_reset_tokens_user_recent_idx
    ON password_reset_tokens (user_id, created_at DESC);

CREATE OR REPLACE FUNCTION issue_password_reset_token(
    p_email citext,
    p_token_hash text,
    p_expires_at timestamptz
)
RETURNS TABLE(email text, display_name text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_user_id uuid;
BEGIN
    SELECT identity.user_id
    INTO v_user_id
    FROM auth_identities identity
    WHERE identity.email = p_email
      AND identity.status = 'ACTIVE';

    IF v_user_id IS NULL THEN
        RETURN;
    END IF;

    UPDATE password_reset_tokens
    SET used_at = now()
    WHERE user_id = v_user_id
      AND used_at IS NULL;

    INSERT INTO password_reset_tokens (user_id, token_hash, expires_at)
    VALUES (v_user_id, p_token_hash, p_expires_at);

    RETURN QUERY
    SELECT identity.email::text, app_user.display_name::text
    FROM auth_identities identity
    JOIN users app_user ON app_user.id = identity.user_id
    WHERE identity.user_id = v_user_id;
END;
$$;

CREATE OR REPLACE FUNCTION consume_password_reset_token(
    p_token_hash text,
    p_password_hash text
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_token_id uuid;
    v_user_id uuid;
BEGIN
    SELECT token.id, token.user_id
    INTO v_token_id, v_user_id
    FROM password_reset_tokens token
    WHERE token.token_hash = p_token_hash
      AND token.used_at IS NULL
      AND token.expires_at > now()
    FOR UPDATE;

    IF v_token_id IS NULL THEN
        RETURN false;
    END IF;

    UPDATE auth_identities
    SET password_hash = p_password_hash,
        auth_version = auth_version + 1,
        updated_at = now()
    WHERE user_id = v_user_id
      AND status = 'ACTIVE';

    IF NOT FOUND THEN
        RETURN false;
    END IF;

    UPDATE password_reset_tokens
    SET used_at = now()
    WHERE user_id = v_user_id
      AND used_at IS NULL;

    RETURN true;
END;
$$;

CREATE OR REPLACE FUNCTION current_auth_version(p_user_id uuid)
RETURNS bigint
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT identity.auth_version
    FROM auth_identities identity
    WHERE identity.user_id = p_user_id
      AND identity.status = 'ACTIVE'
$$;

GRANT SELECT, INSERT ON account_policy_consents TO jobiss_app;
REVOKE ALL ON password_reset_tokens FROM PUBLIC, jobiss_app;
REVOKE ALL ON FUNCTION issue_password_reset_token(citext, text, timestamptz) FROM PUBLIC;
REVOKE ALL ON FUNCTION consume_password_reset_token(text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION current_auth_version(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION issue_password_reset_token(citext, text, timestamptz) TO jobiss_app;
GRANT EXECUTE ON FUNCTION consume_password_reset_token(text, text) TO jobiss_app;
GRANT EXECUTE ON FUNCTION current_auth_version(uuid) TO jobiss_app;
REVOKE ALL ON account_policy_consents FROM PUBLIC;
