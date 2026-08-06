ALTER TABLE analysis_questions
    ADD COLUMN input_type varchar(10) NOT NULL DEFAULT 'CHOICE';

ALTER TABLE analysis_questions
    DROP CONSTRAINT analysis_question_options_check;

ALTER TABLE analysis_questions
    ADD CONSTRAINT analysis_question_input_type_check
        CHECK (input_type IN ('CHOICE', 'TEXT')),
    ADD CONSTRAINT analysis_question_options_check
        CHECK (
            jsonb_typeof(options) = 'array'
            AND (
                (
                    input_type = 'CHOICE'
                    AND jsonb_array_length(options) BETWEEN 2 AND 4
                )
                OR
                (
                    input_type = 'TEXT'
                    AND jsonb_array_length(options) = 0
                )
            )
        );

ALTER TABLE analysis_questions
    ALTER COLUMN answer_value TYPE varchar(2000);
