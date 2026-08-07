# backend 작업 지침

루트 [AGENTS.md](../AGENTS.md)를 먼저 읽는다. 이 파일은 백엔드에만 해당하는 규칙이다.
특히 루트의 "Spring JDBC와 PostgreSQL SQL 규칙", "SQL 변경 검증", "API 500 진단 순서"는
여기서 반복하지 않으니 그대로 따른다.

## CI에서 이 디렉토리가 책임지는 것

- **고칠 파일**: [ci/test.sh](ci/test.sh) — 백엔드에서 무엇을 검사하는가.
- **고치지 않을 파일**: 루트 `Jenkinsfile` — 실행 이미지, PostgreSQL 컨테이너,
  `DB_*` 환경변수, JUnit 리포트 수집, JAR stash는 뼈대가 책임진다.

`ci/test.sh`의 산출물 계약: `backend/backend.jar`를 남겨야 하고, JUnit XML은
`build/test-results/test`에 있어야 한다. 이 두 경로를 바꾸면 뼈대도 함께 고쳐야 하므로
Infra 리뷰가 필요하다.

## 기능을 추가·수정할 때

1. 기능 코드와 함께 **테스트를 같은 MR에 넣는다.** 기존 CI가 자동으로 실행한다.
   테스트를 추가하려고 `ci/test.sh`나 `Jenkinsfile`을 고칠 일은 없다.
2. DB를 바꿨으면 **마이그레이션을 작성한 사람이 검증까지 한다.** 아래 규칙을 따른다.
3. AI 서버와 주고받는 계약을 바꿨으면 `AI/` 쪽 모델도 같은 MR에서 맞춘다.
4. CI가 깨지면 원인을 만든 사람이 고친다.

## 마이그레이션 규칙

`src/main/resources/db/migration`은 롤백 비용이 가장 큰 곳이다.

- **번호를 새로 붙이기 전에 현재 최대 버전을 확인한다.** 브랜치를 오래 들고 있었다면
  그 사이 develop에 같은 번호가 생겼을 수 있다. 중복 버전이 하나라도 있으면 Flyway가
  `Found more than one migration with version N`으로 **애플리케이션 기동 자체를 거부**한다.
- 다른 브랜치와 번호가 겹치면 **내 것을 뒤로 미룬다.** 이미 develop에 있는 번호를 밀지 않는다.
- 이름이 같고 번호만 다른 마이그레이션을 만들지 않는다. 두 계보가 같은 테이블을 각각
  만들면 병합 시점에 `relation already exists`로 터진다.
- 앞선 마이그레이션이 만든 컬럼에 의존한다면 그 순서가 병합 후에도 유지되는지 본다.
- 검증은 실제 PostgreSQL로 한다. Testcontainers가 Docker 부재로 건너뛰어졌다면
  통합 검증을 통과한 것으로 적지 않는다.

## 계약을 넓힐 때

`AiContracts`의 record에 컴포넌트를 추가하면 **모든 호출부가 깨진다** — 프로덕션 코드뿐
아니라 `src/test`도 포함이다. record는 기본 생성자만 있으므로 인자 개수가 다르면 곧바로
`compileTestJava` 실패다.

- 호출부를 전부 고치거나, `ChatRequest`처럼 **기존 인자 수를 받는 편의 생성자를 함께 추가**한다.
- 넓힌 커밋에서 `./gradlew compileTestJava`까지 돌려 본다. 프로덕션만 고치고 테스트를
  빠뜨리는 것이 이 저장소에서 실제로 CI를 세운 실패 유형이다.
