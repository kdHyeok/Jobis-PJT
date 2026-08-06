CREATE OR REPLACE FUNCTION publish_analyzed_posting(
    p_posting_id uuid,
    p_primary_track varchar,
    p_experience_requirement_type varchar,
    p_minimum_experience_months integer,
    p_maximum_experience_months integer
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    owned_posting job_postings%ROWTYPE;
    catalog_id uuid;
BEGIN
    SELECT * INTO owned_posting
    FROM job_postings
    WHERE id = p_posting_id
      AND user_id = app_current_user_id()
      AND company_name IS NOT NULL
      AND role_title IS NOT NULL;
    IF NOT FOUND THEN RAISE EXCEPTION 'owned analyzed posting was not found'; END IF;

    INSERT INTO posting_catalog (
        fingerprint, source_url, company_name, role_title, employment_type,
        experience_text, primary_track, experience_requirement_type,
        minimum_experience_months, maximum_experience_months
    ) VALUES (
        owned_posting.content_fingerprint, owned_posting.source_url,
        owned_posting.company_name, owned_posting.role_title,
        owned_posting.employment_type, owned_posting.experience_text,
        upper(p_primary_track), upper(p_experience_requirement_type),
        p_minimum_experience_months, p_maximum_experience_months
    )
    ON CONFLICT (fingerprint) DO UPDATE SET
        source_url = coalesce(excluded.source_url, posting_catalog.source_url),
        company_name = excluded.company_name,
        role_title = excluded.role_title,
        employment_type = excluded.employment_type,
        experience_text = excluded.experience_text,
        primary_track = excluded.primary_track,
        experience_requirement_type = excluded.experience_requirement_type,
        minimum_experience_months = excluded.minimum_experience_months,
        maximum_experience_months = excluded.maximum_experience_months,
        active = true, last_seen_at = now(), updated_at = now()
    RETURNING id INTO catalog_id;
    DELETE FROM posting_catalog_requirements WHERE posting_catalog_id = catalog_id;
    RETURN catalog_id;
END;
$$;

REVOKE ALL ON FUNCTION publish_analyzed_posting(uuid, varchar, varchar, integer, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION publish_analyzed_posting(uuid, varchar, varchar, integer, integer) TO jobiss_app;
