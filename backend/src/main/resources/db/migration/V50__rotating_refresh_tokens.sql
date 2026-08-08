CREATE TABLE auth_refresh_tokens (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    family_id uuid NOT NULL,
    token_hash varchar(64) NOT NULL UNIQUE,
    remember_me boolean NOT NULL DEFAULT false,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    replaced_by uuid REFERENCES auth_refresh_tokens(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    last_used_at timestamptz,
    CHECK (expires_at > created_at)
);

CREATE INDEX auth_refresh_tokens_user_family_idx
    ON auth_refresh_tokens (user_id, family_id);
CREATE INDEX auth_refresh_tokens_expiry_idx
    ON auth_refresh_tokens (expires_at)
    WHERE revoked_at IS NULL;

ALTER TABLE auth_refresh_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_refresh_tokens FORCE ROW LEVEL SECURITY;

CREATE POLICY auth_refresh_tokens_owner_policy ON auth_refresh_tokens
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON auth_refresh_tokens TO jobiss_app;
REVOKE ALL ON auth_refresh_tokens FROM PUBLIC;
