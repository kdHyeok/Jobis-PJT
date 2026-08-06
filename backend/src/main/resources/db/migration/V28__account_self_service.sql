ALTER TABLE posting_duplicate_candidates
    DROP CONSTRAINT posting_duplicate_candidates_resolved_by_fkey,
    ADD CONSTRAINT posting_duplicate_candidates_resolved_by_fkey
        FOREIGN KEY (resolved_by) REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE operator_action_audit
    ALTER COLUMN operator_user_id DROP NOT NULL,
    DROP CONSTRAINT operator_action_audit_operator_user_id_fkey,
    ADD CONSTRAINT operator_action_audit_operator_user_id_fkey
        FOREIGN KEY (operator_user_id) REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE competency_assessment_sessions
    DROP CONSTRAINT competency_assessment_sessions_reviewed_by_fkey,
    ADD CONSTRAINT competency_assessment_sessions_reviewed_by_fkey
        FOREIGN KEY (reviewed_by) REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE assessment_review_actions
    DROP CONSTRAINT assessment_review_actions_operator_user_id_fkey,
    ADD CONSTRAINT assessment_review_actions_operator_user_id_fkey
        FOREIGN KEY (operator_user_id) REFERENCES users(id) ON DELETE SET NULL;

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
        updated_at = now()
    WHERE user_id = p_user_id;
END;
$$;

CREATE OR REPLACE FUNCTION delete_current_account(p_user_id uuid)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    IF p_user_id IS DISTINCT FROM app_current_user_id() THEN
        RAISE EXCEPTION 'account owner mismatch';
    END IF;
    DELETE FROM users WHERE id = p_user_id;
END;
$$;

REVOKE ALL ON FUNCTION update_current_auth_identity(uuid, citext, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION delete_current_account(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION update_current_auth_identity(uuid, citext, text) TO jobiss_app;
GRANT EXECUTE ON FUNCTION delete_current_account(uuid) TO jobiss_app;
