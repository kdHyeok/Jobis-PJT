CREATE TABLE legacy_import_audit (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_database varchar(63) NOT NULL UNIQUE,
    source_counts jsonb NOT NULL,
    imported_counts jsonb NOT NULL,
    imported_at timestamptz NOT NULL DEFAULT now(),
    CHECK (jsonb_typeof(source_counts) = 'object'),
    CHECK (jsonb_typeof(imported_counts) = 'object')
);

REVOKE ALL ON legacy_import_audit FROM PUBLIC;
