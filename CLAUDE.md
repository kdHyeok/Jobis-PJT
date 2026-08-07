# AI 작업자 안내

@AGENTS.md

규약의 정본은 [AGENTS.md](AGENTS.md)다. 위 import로 함께 읽히므로 여기에 규칙을 복제하지
않는다. 배포 작업은 [ops/DEPLOYMENT.md](ops/DEPLOYMENT.md)를 따른다.

현재 정본 AI 서버는 `AI/src/jobis_ai/v2bridge/app.py`다. `fake-ai`, 별도 `ai-server`,
MySQL/Hibernate 자동 스키마, 옛 WebSocket 실행법을 현행 계약으로 사용하지 않는다.

디렉토리별 규칙은 각 폴더의 `AGENTS.md`에 있다 — `backend/`, `frontend/`, `AI/`, `RAG/`, `ops/`.
그 폴더에서 작업할 때 함께 읽는다.

## Claude Code

도구에 따라 **규칙이 달라지지는 않는다.** 아래는 같은 규칙을 Claude Code에서 어떻게
실행하는지에 대한 것이다.

- 다음 경로를 바꿀 때는 계획을 먼저 확인받는다(plan mode). 되돌리는 비용이 크거나 팀 전체에
  영향을 준다.
  - `backend/src/main/resources/db/migration/` — 마이그레이션은 롤백이 가장 비싸다.
    번호를 붙이기 전에 현재 최대 버전과 develop 쪽 번호를 함께 확인한다.
  - `Jenkinsfile`, `ops/`, `infra/`, `compose.yaml` — CI/CD 뼈대와 배포 정책.
  - `.gitlab/CODEOWNERS`
- 커밋, push, 브랜치 변경은 사용자가 명시적으로 요청할 때만 한다(AGENTS.md "작업 원칙").
- 검증하지 않은 것을 통과했다고 적지 않는다. Docker가 없어 Testcontainers가 건너뛰어졌다면
  "통합 검증 통과"가 아니다. 실행한 명령과 결과를 그대로 보고한다.
- 서비스 CI를 확인할 때는 CI와 **같은 명령**을 쓴다 — `bash <서비스>/ci/test.sh`.
  이 스크립트들은 Linux 컨테이너 기준이라 Windows 셸에서 그대로 돌지 않을 수 있다.
  그럴 때는 안쪽 명령(`./gradlew ...`, `npm run build`)을 직접 실행하고 그 사실을 밝힌다.
