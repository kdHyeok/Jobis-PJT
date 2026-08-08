ALTER TABLE user_atomic_capabilities
    ADD COLUMN completion_policy varchar(24) NOT NULL DEFAULT 'ASSESSMENT',
    ADD CONSTRAINT user_atomic_capabilities_completion_policy_check
        CHECK (completion_policy IN ('SELF_CONFIRM', 'ASSESSMENT'));
