-- 경로 비교에서 사용자가 고른 "주 경로" id 저장 (스펙 §11.3). 미선택이면 null.
ALTER TABLE analysis_runs ADD COLUMN selected_route VARCHAR(40) NULL AFTER parent_analysis_id;
