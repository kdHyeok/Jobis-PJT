CREATE OR REPLACE FUNCTION current_account_deletion_receipt(p_user_id uuid)
RETURNS TABLE (
    request_id uuid,
    deletion_status varchar,
    requested_at timestamptz,
    purge_after timestamptz
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT request.id, request.status, request.requested_at, request.purge_after
    FROM account_deletion_requests request
    WHERE request.user_id = p_user_id
      AND p_user_id = app_current_user_id()
$$;

REVOKE ALL ON FUNCTION current_account_deletion_receipt(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION current_account_deletion_receipt(uuid) TO jobiss_app;
