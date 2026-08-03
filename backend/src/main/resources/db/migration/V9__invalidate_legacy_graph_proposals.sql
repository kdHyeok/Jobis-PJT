UPDATE analysis_jobs j
SET
    status = 'FAILED',
    stage = 'FAILED',
    stage_message = '새 역량 기반 분석 계약으로 다시 분석이 필요합니다.',
    error_code = 'ANALYSIS_CONTRACT_UPGRADED',
    error_message = '기존 그래프 변경안은 새 로드맵 버전 구조와 호환되지 않습니다. 다시 분석해 주세요.',
    attempt_count = 0,
    worker_id = NULL,
    locked_until = NULL
FROM graph_change_sets c
WHERE c.analysis_job_id = j.id
  AND c.status = 'PROPOSED'
  AND j.status = 'SUCCEEDED'
  AND NOT EXISTS (
      SELECT 1
      FROM posting_competency_requirements r
      WHERE r.analysis_job_id = j.id
  );
