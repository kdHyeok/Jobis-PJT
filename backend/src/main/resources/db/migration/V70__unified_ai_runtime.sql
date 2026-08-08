-- The verified career workflow now runs inside the same JOBIS AI process as
-- chat. Keep historical LEGACY rows reproducible, but label every verified
-- source-backed analysis with the product-neutral UNIFIED provider value.
ALTER TABLE analysis_jobs
    DROP CONSTRAINT analysis_jobs_v3_source_pair_check;

DROP INDEX IF EXISTS analysis_jobs_v3_snapshot_once_idx;

ALTER TABLE analysis_jobs
    DROP CONSTRAINT analysis_jobs_provider_check;

UPDATE analysis_jobs
SET analysis_provider = 'UNIFIED'
WHERE analysis_provider = 'V3';

ALTER TABLE analysis_jobs
    ADD CONSTRAINT analysis_jobs_provider_check
        CHECK (analysis_provider IN ('LEGACY', 'UNIFIED')),
    ADD CONSTRAINT analysis_jobs_v3_source_pair_check
        CHECK (
            (v3_source_id IS NULL AND v3_snapshot_id IS NULL)
            OR
            (
                analysis_provider = 'UNIFIED'
                AND v3_source_id IS NOT NULL
                AND v3_snapshot_id IS NOT NULL
            )
        );

CREATE UNIQUE INDEX analysis_jobs_v3_snapshot_once_idx
    ON analysis_jobs (user_id, v3_snapshot_id)
    WHERE analysis_provider = 'UNIFIED' AND v3_snapshot_id IS NOT NULL;
