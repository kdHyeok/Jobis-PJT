CREATE OR REPLACE FUNCTION purge_expired_operational_data()
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_agent_events integer;
    v_usage integer;
    v_comparisons integer;
    v_refresh integer;
    v_reset integer;
    v_deletion_audit integer;
BEGIN
    DELETE FROM analysis_agent_events WHERE created_at < now() - interval '30 days';
    GET DIAGNOSTICS v_agent_events = ROW_COUNT;
    DELETE FROM ai_usage_hourly WHERE hour_start < now() - interval '30 days';
    GET DIAGNOSTICS v_usage = ROW_COUNT;
    DELETE FROM ai_provider_comparisons
    WHERE created_at < now() - CASE WHEN review_decision = 'PENDING' THEN interval '30 days' ELSE interval '1 year' END;
    GET DIAGNOSTICS v_comparisons = ROW_COUNT;
    DELETE FROM auth_refresh_tokens
    WHERE expires_at < now() - interval '30 days'
       OR revoked_at < now() - interval '30 days';
    GET DIAGNOSTICS v_refresh = ROW_COUNT;
    DELETE FROM password_reset_tokens
    WHERE created_at < now() - interval '30 days';
    GET DIAGNOSTICS v_reset = ROW_COUNT;
    DELETE FROM account_deletion_requests
    WHERE status = 'COMPLETED' AND completed_at < now() - interval '1 year';
    GET DIAGNOSTICS v_deletion_audit = ROW_COUNT;
    RETURN jsonb_build_object(
        'analysisAgentEvents', v_agent_events,
        'aiUsage', v_usage,
        'providerComparisons', v_comparisons,
        'refreshTokens', v_refresh,
        'passwordResetTokens', v_reset,
        'accountDeletionAudits', v_deletion_audit
    );
END;
$$;

REVOKE ALL ON FUNCTION purge_expired_operational_data() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION purge_expired_operational_data() TO jobiss_app;
