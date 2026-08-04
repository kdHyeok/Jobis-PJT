-- PostgreSQL-backed OCR work queue for both daily and legacy postings.
ALTER TABLE job_postings
    ADD COLUMN ocr_status TEXT,
    ADD COLUMN ocr_attempt_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN ocr_last_error TEXT,
    ADD COLUMN ocr_next_retry_at TIMESTAMPTZ,
    ADD COLUMN ocr_lease_until TIMESTAMPTZ,
    ADD COLUMN ocr_worker_id TEXT,
    ADD COLUMN ocr_last_attempt_at TIMESTAMPTZ,
    ADD COLUMN ocr_updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

UPDATE job_postings
SET ocr_status = CASE
        WHEN need_ocr = 'O' AND jsonb_array_length(image_urls) > 0 THEN 'pending'
        WHEN need_ocr = 'O' THEN 'dead'
        WHEN text_source = 'ocr' THEN 'succeeded'
        ELSE 'not_required'
    END,
    ocr_last_error = CASE
        WHEN need_ocr = 'O' AND jsonb_array_length(image_urls) = 0
        THEN 'missing_image_urls'
        ELSE ocr_last_error
    END;

ALTER TABLE job_postings
    ALTER COLUMN ocr_status SET NOT NULL,
    ADD CONSTRAINT job_postings_need_ocr_check
        CHECK (need_ocr IN ('O', 'X')),
    ADD CONSTRAINT job_postings_ocr_status_check
        CHECK (ocr_status IN (
            'not_required', 'pending', 'processing',
            'retry_wait', 'succeeded', 'dead'
        )),
    ADD CONSTRAINT job_postings_ocr_attempt_count_check
        CHECK (ocr_attempt_count >= 0);

-- Old/manual INSERT statements may not know the new ocr_status column yet.
-- Normalize omitted status values and need_ocr transitions at the DB boundary.
CREATE OR REPLACE FUNCTION normalize_job_postings_ocr_status()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.ocr_status IS NULL THEN
        NEW.ocr_status := CASE
            WHEN NEW.need_ocr = 'O' AND jsonb_array_length(NEW.image_urls) > 0 THEN 'pending'
            WHEN NEW.need_ocr = 'O' THEN 'dead'
            WHEN NEW.text_source = 'ocr' THEN 'succeeded'
            ELSE 'not_required'
        END;
    ELSIF TG_OP = 'UPDATE'
          AND NEW.need_ocr IS DISTINCT FROM OLD.need_ocr
          AND NEW.ocr_status IS NOT DISTINCT FROM OLD.ocr_status THEN
        NEW.ocr_status := CASE
            WHEN NEW.need_ocr = 'O' AND jsonb_array_length(NEW.image_urls) > 0 THEN 'pending'
            WHEN NEW.need_ocr = 'O' THEN 'dead'
            WHEN NEW.text_source = 'ocr' THEN 'succeeded'
            ELSE 'not_required'
        END;
        NEW.ocr_last_error := CASE
            WHEN NEW.need_ocr = 'O' AND jsonb_array_length(NEW.image_urls) = 0
            THEN 'missing_image_urls'
            ELSE NULL
        END;
        NEW.ocr_next_retry_at := NULL;
        NEW.ocr_lease_until := NULL;
        NEW.ocr_worker_id := NULL;
        NEW.ocr_updated_at := now();
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS job_postings_normalize_ocr_status ON job_postings;
CREATE TRIGGER job_postings_normalize_ocr_status
BEFORE INSERT OR UPDATE OF need_ocr, ocr_status ON job_postings
FOR EACH ROW
EXECUTE FUNCTION normalize_job_postings_ocr_status();

CREATE INDEX idx_job_postings_ocr_queue
    ON job_postings (source, ocr_status, ocr_next_retry_at, collected_at)
    WHERE need_ocr = 'O';
