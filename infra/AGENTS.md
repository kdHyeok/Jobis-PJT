# infra 작업 지침 — 여기는 뼈대다

루트 [AGENTS.md](../AGENTS.md) 를 먼저 읽는다. 소유권 규칙은
[ops/CI_OWNERSHIP.md](../ops/CI_OWNERSHIP.md) 를 따른다.

이 디렉토리(Airflow 파이프라인, 이미지, 마이그레이션)는 배포·운영 뼈대다. 변경은 MR 로
제안하고 Infra 담당 리뷰를 받는다.

## Airflow 마이그레이션

`infra/airflow/migrations/jobrag/` 는 백엔드(`backend/src/main/resources/db/migration/`)
와 **별개의 Flyway 체인**이다. 번호를 서로 맞출 필요는 없지만, 각 체인 안에서는
`origin/develop` 의 최신 번호를 확인하고 그 다음 번호를 쓴다. 같은 번호가 둘이면
파일명이 달라도 Flyway 가 기동을 거부한다.

## DAG 를 추가할 때

`dags/` 에 파일을 추가하면 CI 의 Infra 단계가 문법을 검사한다. 무거운 의존성(torch,
pgvector 등)은 DAG 모듈 최상단에서 import 하지 않는다 — 스케줄러가 DAG 를 파싱할 때마다
끌어오게 되고, CI 의 가벼운 환경에서는 import 자체가 실패한다.
