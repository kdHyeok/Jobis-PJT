ALTER TABLE competency_assessment_sessions
    ADD COLUMN retained_scores jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE competency_assessment_sessions
    ADD CONSTRAINT competency_assessment_retained_scores_object
    CHECK (jsonb_typeof(retained_scores) = 'object');
