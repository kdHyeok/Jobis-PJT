# ops 작업 지침 (Infra 소유)

루트 [AGENTS.md](../AGENTS.md)를 먼저 읽고, 배포 절차는 [DEPLOYMENT.md](DEPLOYMENT.md)를 따른다.

## 이 디렉토리의 지위

`ops/`, `infra/`, `compose.yaml`, 루트 `Jenkinsfile`은 **CI/CD 뼈대와 배포 정책**이다.
기능 개발자가 자기 기능을 통과시키려고 단독으로 바꾸지 않는다. 변경은 MR + Infra 리뷰다
(`.gitlab/CODEOWNERS`).

기능 개발자가 CI에서 고칠 곳은 자기 서비스의 `<서비스>/ci/test.sh`와 테스트 코드다.

## 뼈대를 바꿔야 하는 경우

다음은 정당한 변경 사유다. MR로 올리고 Infra 리뷰를 받는다.

- 통합 테스트에 새 인프라 의존성이 필요하다 (Redis, 메시지 브로커 등)
  → `Jenkinsfile`의 서비스 컨테이너 블록에 추가한다. 서비스 스크립트 안에서
  `docker run`으로 몰래 띄우지 않는다. 그러면 정리·포트 충돌·동시성 책임이 사라진다.
- 새 서비스가 생겨 스테이지가 필요하다
- 실행 이미지의 언어 버전을 올려야 한다
- 게이트 배치를 바꿔야 한다 (기능 브랜치 ↔ develop ↔ master)

## 바꾸지 말아야 할 불변식

- **Build Once, Deploy Many.** master에서 다시 빌드하지 않는다. develop에서 검증한
  불변 SHA 태그 이미지를 `pull → tag → push`로 승격만 한다. 프로덕션에서
  `./gradlew build`를 다시 도는 형태로 되돌리지 않는다.
- **`Master release: verify`의 트리 동일성 검사.** master 머지가 2-parent인지,
  두 번째 부모가 `origin/develop`의 조상인지, `git diff --quiet`로 트리가 동일한지를
  강제한다. 프로덕션 설정 검증(`verify-release-config.py`, compose config, nginx `-t`)이
  `Infra: static validation`(= master 아님)에만 있는데도 안전한 이유가 **전적으로 이 검사**다.
  이 검사를 완화하면 그 보장이 함께 사라진다.
- **배포 스크립트의 실행 비트.** `Infra: static validation`이 `test -x`로 확인한다.
  실행 비트가 빠지면 배포가 시작 직후 멈춘다.
- **은퇴한 경로 재도입 금지.** `ai-server`, `fake-ai`, `AGENT_WS_URL`, `AGENT_HTTP_URL`을
  배포 경로에서 다시 참조하면 CI가 실패한다.

## 셸 스크립트 규칙

- 새 스크립트를 추가하면 `Infra: static validation`의 `bash -n` 목록에도 넣는다.
- `set -euo pipefail`을 쓴다.
- Jenkins 자신이 컨테이너다. 호스트 Docker 데몬에는 컨테이너 전용 `$WORKSPACE` 경로가
  없으므로 raw bind mount 대신 `--volumes-from`으로 같은 체크아웃을 공유한다.
