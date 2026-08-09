# infra 작업자 진입점

@AGENTS.md

@../ops/CI_OWNERSHIP.md

## Claude Code

- 이 디렉토리는 배포·파이프라인 뼈대다. 고치기 전에 계획을 먼저 제시하고 승인을 받는다(plan mode).
- Airflow 마이그레이션은 백엔드와 별개 체인이다. 각 체인 안에서 `origin/develop` 의
  최신 번호를 확인하고 그 다음 번호를 쓴다.
