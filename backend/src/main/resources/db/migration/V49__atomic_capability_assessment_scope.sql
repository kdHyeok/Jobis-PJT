ALTER TABLE user_atomic_capabilities
    ADD COLUMN objective text,
    ADD COLUMN excluded_scope jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD CONSTRAINT user_atomic_capabilities_excluded_scope_check
        CHECK (jsonb_typeof(excluded_scope) = 'array');
