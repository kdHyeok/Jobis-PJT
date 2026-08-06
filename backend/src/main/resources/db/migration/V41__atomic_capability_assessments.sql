CREATE TABLE atomic_capability_assessment_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    atomic_capability_id uuid NOT NULL,
    status varchar(24) NOT NULL DEFAULT 'IN_PROGRESS'
        CHECK (status IN ('IN_PROGRESS', 'PASSED', 'NEEDS_STUDY', 'ABANDONED', 'REVIEW_REQUESTED')),
    required_question_count integer NOT NULL CHECK (required_question_count BETWEEN 2 AND 3),
    answered_question_count integer NOT NULL DEFAULT 0 CHECK (answered_question_count BETWEEN 0 AND 8),
    average_score integer CHECK (average_score BETWEEN 0 AND 100),
    target_context jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    UNIQUE (id, user_id),
    CONSTRAINT atomic_assessment_capability_owner_fk
        FOREIGN KEY (atomic_capability_id, user_id)
        REFERENCES user_atomic_capabilities(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT atomic_assessment_target_context_check
        CHECK (jsonb_typeof(target_context) = 'object'),
    CONSTRAINT atomic_assessment_completion_check
        CHECK (
            (status = 'IN_PROGRESS' AND completed_at IS NULL)
            OR (status <> 'IN_PROGRESS' AND completed_at IS NOT NULL)
        )
);

CREATE UNIQUE INDEX atomic_assessment_one_active_idx
    ON atomic_capability_assessment_sessions (user_id, atomic_capability_id)
    WHERE status = 'IN_PROGRESS';

CREATE TABLE atomic_capability_assessment_turns (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id uuid NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal BETWEEN 1 AND 8),
    question_id varchar(180) NOT NULL,
    method varchar(20) NOT NULL
        CHECK (method IN ('EXPLAIN', 'IMPLEMENT', 'TEST', 'DEBUG', 'MEASURE', 'DOCUMENT')),
    question jsonb NOT NULL,
    answer_text text,
    grade jsonb,
    score integer CHECK (score BETWEEN 0 AND 100),
    passed boolean,
    created_at timestamptz NOT NULL DEFAULT now(),
    answered_at timestamptz,
    UNIQUE (id, user_id),
    UNIQUE (user_id, session_id, ordinal),
    UNIQUE (user_id, question_id),
    CONSTRAINT atomic_assessment_turn_session_owner_fk
        FOREIGN KEY (session_id, user_id)
        REFERENCES atomic_capability_assessment_sessions(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT atomic_assessment_turn_question_check
        CHECK (jsonb_typeof(question) = 'object'),
    CONSTRAINT atomic_assessment_turn_grade_check
        CHECK (grade IS NULL OR jsonb_typeof(grade) = 'object'),
    CONSTRAINT atomic_assessment_turn_answer_check
        CHECK (
            (answer_text IS NULL AND grade IS NULL AND score IS NULL AND passed IS NULL AND answered_at IS NULL)
            OR (answer_text IS NOT NULL AND grade IS NOT NULL AND score IS NOT NULL AND passed IS NOT NULL AND answered_at IS NOT NULL)
        )
);

CREATE TABLE atomic_capability_assessment_reviews (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id uuid NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED', 'CANCELLED')),
    reason text NOT NULL,
    operator_note text,
    requested_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    resolved_by uuid REFERENCES users(id),
    UNIQUE (id, user_id),
    UNIQUE (user_id, session_id),
    CONSTRAINT atomic_assessment_review_session_owner_fk
        FOREIGN KEY (session_id, user_id)
        REFERENCES atomic_capability_assessment_sessions(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT atomic_assessment_review_resolution_check
        CHECK (
            (status = 'PENDING' AND resolved_at IS NULL AND resolved_by IS NULL)
            OR (status <> 'PENDING' AND resolved_at IS NOT NULL)
        )
);

CREATE INDEX atomic_assessment_sessions_capability_idx
    ON atomic_capability_assessment_sessions (user_id, atomic_capability_id, created_at DESC);
CREATE INDEX atomic_assessment_reviews_pending_idx
    ON atomic_capability_assessment_reviews (requested_at)
    WHERE status = 'PENDING';

CREATE TRIGGER atomic_assessment_sessions_touch_updated_at
BEFORE UPDATE ON atomic_capability_assessment_sessions
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

ALTER TABLE atomic_capability_assessment_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE atomic_capability_assessment_sessions FORCE ROW LEVEL SECURITY;
ALTER TABLE atomic_capability_assessment_turns ENABLE ROW LEVEL SECURITY;
ALTER TABLE atomic_capability_assessment_turns FORCE ROW LEVEL SECURITY;
ALTER TABLE atomic_capability_assessment_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE atomic_capability_assessment_reviews FORCE ROW LEVEL SECURITY;

CREATE POLICY atomic_assessment_sessions_owner_policy ON atomic_capability_assessment_sessions
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());
CREATE POLICY atomic_assessment_turns_owner_policy ON atomic_capability_assessment_turns
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());
CREATE POLICY atomic_assessment_reviews_owner_policy ON atomic_capability_assessment_reviews
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());

CREATE POLICY atomic_assessment_sessions_operator_policy ON atomic_capability_assessment_sessions
    USING (EXISTS (
        SELECT 1 FROM users current_user_record
        WHERE current_user_record.id = app_current_user_id()
          AND current_user_record.account_role = 'OPERATOR'
    ))
    WITH CHECK (EXISTS (
        SELECT 1 FROM users current_user_record
        WHERE current_user_record.id = app_current_user_id()
          AND current_user_record.account_role = 'OPERATOR'
    ));
CREATE POLICY atomic_assessment_turns_operator_policy ON atomic_capability_assessment_turns
    USING (EXISTS (
        SELECT 1 FROM users current_user_record
        WHERE current_user_record.id = app_current_user_id()
          AND current_user_record.account_role = 'OPERATOR'
    ))
    WITH CHECK (EXISTS (
        SELECT 1 FROM users current_user_record
        WHERE current_user_record.id = app_current_user_id()
          AND current_user_record.account_role = 'OPERATOR'
    ));
CREATE POLICY atomic_assessment_reviews_operator_policy ON atomic_capability_assessment_reviews
    USING (EXISTS (
        SELECT 1 FROM users current_user_record
        WHERE current_user_record.id = app_current_user_id()
          AND current_user_record.account_role = 'OPERATOR'
    ))
    WITH CHECK (EXISTS (
        SELECT 1 FROM users current_user_record
        WHERE current_user_record.id = app_current_user_id()
          AND current_user_record.account_role = 'OPERATOR'
    ));

GRANT SELECT, INSERT, UPDATE, DELETE ON
    atomic_capability_assessment_sessions,
    atomic_capability_assessment_turns,
    atomic_capability_assessment_reviews
TO jobiss_app;

REVOKE ALL ON
    atomic_capability_assessment_sessions,
    atomic_capability_assessment_turns,
    atomic_capability_assessment_reviews
FROM PUBLIC;
