CREATE OR REPLACE FUNCTION invalidate_current_auth_tokens(p_user_id uuid)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_version bigint;
BEGIN
    IF p_user_id IS DISTINCT FROM app_current_user_id() THEN
        RAISE EXCEPTION 'auth identity owner mismatch';
    END IF;

    UPDATE auth_identities
    SET auth_version = auth_version + 1,
        updated_at = now()
    WHERE user_id = p_user_id
    RETURNING auth_version INTO v_version;

    RETURN COALESCE(v_version, -1);
END;
$$;

REVOKE ALL ON FUNCTION invalidate_current_auth_tokens(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION invalidate_current_auth_tokens(uuid) TO jobiss_app;
