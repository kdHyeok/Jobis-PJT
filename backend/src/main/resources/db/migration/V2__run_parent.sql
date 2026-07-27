-- 재분석 세션의 부모(원래 분석) 링크. 대체 공고 재분석이면 원래 분석의 analysis_id(UUID)를 담는다.
-- NULL = 독립(최상위) 분석. FK는 걸지 않음(부모가 지워져도 자식은 남고, 그때는 최상위로 표시).
ALTER TABLE analysis_runs
  ADD COLUMN parent_analysis_id CHAR(36) NULL AFTER job_posting_id;
