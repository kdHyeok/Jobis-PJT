ALTER TABLE analysis_questions
    ADD COLUMN related_requirement_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN absence_scope varchar(24) NOT NULL DEFAULT 'NONE',
    ADD COLUMN answer_status varchar(24) NOT NULL DEFAULT 'PROVIDED';

ALTER TABLE analysis_questions
    ADD CONSTRAINT analysis_question_requirement_ids_check
        CHECK (jsonb_typeof(related_requirement_ids) = 'array'),
    ADD CONSTRAINT analysis_question_absence_scope_check
        CHECK (absence_scope IN ('NONE', 'GENERAL_EXPERIENCE', 'REQUIREMENTS')),
    ADD CONSTRAINT analysis_question_answer_status_check
        CHECK (answer_status IN ('PROVIDED', 'CONFIRMED_ABSENT', 'SKIPPED')),
    ADD CONSTRAINT analysis_question_confirmed_absence_scope_check
        CHECK (answer_status <> 'CONFIRMED_ABSENT' OR absence_scope <> 'NONE');

-- V23까지 생성된 자유 서술 질문도 재시도 시 의미를 잃지 않도록 보정한다.
-- 분석용 TEXT 질문은 현재 경험 근거 확인 질문뿐이며, 포괄 질문만 별도 범위로 구분한다.
UPDATE analysis_questions
SET absence_scope = CASE
    WHEN question_text LIKE '%프로젝트%'
         AND (question_text LIKE '%업무 경험%' OR question_text LIKE '%한 가지%')
        THEN 'GENERAL_EXPERIENCE'
    ELSE 'REQUIREMENTS'
END
WHERE input_type = 'TEXT';

UPDATE analysis_questions
SET answer_status = 'CONFIRMED_ABSENT'
WHERE status = 'ANSWERED'
  AND input_type = 'TEXT'
  AND absence_scope <> 'NONE'
  AND regexp_replace(lower(trim(answer_value)), '[[:space:][:punct:]]+', '', 'g') IN (
      '없습니다',
      '따로없습니다',
      '경험없습니다',
      '경험이없습니다',
      '관련경험없습니다',
      '프로젝트경험없습니다',
      '업무경험없습니다',
      '해본적없습니다',
      '한적없습니다',
      '없어요',
      '따로없어요',
      '경험없어요',
      '경험이없어요',
      '해본적없어요',
      '없음',
      '아니요'
  );
