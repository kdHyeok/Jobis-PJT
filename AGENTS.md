# JOBISS 개발 작업 지침

이 파일은 이 저장소 루트 아래에서 작업하는 모든 사람과 AI 에이전트가
작업을 시작하기 전에 따라야 하는 저장소 규칙이다.

## 작업 원칙

- 기존 작업 트리의 변경은 사용자와 다른 팀원의 작업일 수 있으므로 보존한다.
- 사용자가 명시적으로 요청하지 않으면 Git 커밋, Push, 브랜치 변경을 하지 않는다.
- 수정 전에 관련 프론트엔드, 백엔드, AI 서버와 DB 계약을 함께 확인한다.
- 오류 수정은 사용자에게 보이는 메시지만 바꾸지 말고 실제 예외와 실패 지점을 확인한다.

## Spring JDBC와 PostgreSQL SQL 규칙

- `JdbcClient`와 `NamedParameterJdbcTemplate`에서 이름 있는 파라미터를 사용하는
  SQL에는 전통적인 `?` placeholder를 혼용하지 않는다.
- PostgreSQL JSONB 존재 연산자 `?`, `?|`, `?&`는 Spring이 placeholder로
  해석할 수 있으므로 Java SQL에서 사용하지 않는다.
- JSONB 키 존재 검사는 다음 함수로 작성한다.
  - `jsonb_exists(json_value, key)`
  - `jsonb_exists_any(json_value, keys)`
  - `jsonb_exists_all(json_value, keys)`
- null이 될 수 있는 이름 있는 파라미터를 `:value is null` 또는
  `:value is not null`로 판별하지 않는다. SQL을 분기하거나 null이 아닌 boolean
  파라미터를 별도로 전달하고 값 파라미터에는 명확한 타입의 값을 전달한다.
- 같은 파라미터를 여러 문맥에서 사용할 때 PostgreSQL이 타입을 추론할 것이라고
  가정하지 않는다. 필요하면 SQL 분기 또는 명시적 캐스팅을 사용한다.

## SQL 변경 검증

- SQL을 추가하거나 수정하면 성공 입력뿐 아니라 null 입력, 중복 입력, 캐시 적중,
  캐시 미적중, 동시 요청 경로를 검토한다.
- `SpringJdbcSqlGuardrailTest`를 통과해야 한다.
- DB 동작 변경은 실제 PostgreSQL 통합 테스트로 검증한다. CI에서 Docker가 없어
  Testcontainers 테스트가 건너뛰어졌다면 이를 성공한 통합 검증으로 표현하지 않는다.
- 마이그레이션은 가능하면 실제 PostgreSQL에서 트랜잭션으로 실행 후 롤백하여
  문법과 데이터 변환 결과를 확인한다.

## API 500 진단 순서

1. 브라우저의 일반 오류 문구가 아니라 API 응답 코드와 요청 ID를 확인한다.
2. IntelliJ 또는 서버 로그에서 최초 애플리케이션 예외를 확인한다.
3. PostgreSQL 로그에서 같은 시각의 SQL 오류를 확인한다.
4. 대상 레코드가 생성되지 않았는지, 생성 후 실패했는지 DB 상태를 확인한다.
5. 원인을 재현하는 테스트를 추가한 뒤 수정하고 전체 관련 테스트를 실행한다.
