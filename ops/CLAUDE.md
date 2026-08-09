# ops 작업자 진입점

@AGENTS.md

@CI_OWNERSHIP.md

## Claude Code

- 이 디렉토리와 `Jenkinsfile` 은 **배포 정책**이다. 고치기 전에 계획을 먼저 제시하고
  승인을 받는다(plan mode). 기능 하나 때문에 파이프라인 정책을 바꾸지 않는다.
- `smoke-compose` 를 손볼 때는 `compose.smoke.yml` 의 볼륨 격리를 반드시 유지한다.
  없으면 `down -v` 가 로컬·서버의 실제 데이터를 지운다.
