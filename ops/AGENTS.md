# ops 작업 지침 — 여기는 뼈대다

루트 [AGENTS.md](../AGENTS.md) 를 먼저 읽는다.

이 디렉토리와 `Jenkinsfile`·`infra/`·`compose.yaml` 은 **파이프라인 뼈대와 배포 정책**이다.
기능 개발자가 자기 기능에 맞춰 단독으로 바꾸지 않는다. 변경은 MR 로 제안하고 Infra
담당 리뷰를 받는다(`.gitlab/CODEOWNERS`).

- 소유권·게이트 구성·advisory 목록: [CI_OWNERSHIP.md](CI_OWNERSHIP.md)
- 배포 절차: [DEPLOYMENT.md](DEPLOYMENT.md)
- Jenkins 설정: [JENKINS_SETUP.md](JENKINS_SETUP.md)

## 여기 스크립트를 고칠 때

- 모두 `bash -n` 문법 검사와 실행 비트 확인을 CI 가 한다. 새 스크립트를 추가하면
  `Jenkinsfile` 의 Infra 단계 목록에도 넣는다.
- `smoke-compose` 는 실제 볼륨을 건드리면 안 된다. 격리는 `compose.smoke.yml` 이
  볼륨 이름을 갈아끼워 담당한다 — 이 오버라이드 없이 `down -v` 를 돌리면 로컬·서버
  데이터가 지워진다. 스크립트가 그 파일의 존재를 강제하는 이유다.
- 스모크는 `local` 프로파일로 돈다. `prod` 프로파일은 설정 검증기가 localhost origin 을
  거부한다. 운영 설정 검증은 `verify-release-config.py` 와 백엔드 테스트가 따로 한다.
