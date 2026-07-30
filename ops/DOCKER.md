# JOBIS Docker 전환

서비스 배포를 jar/systemd 방식에서 도커 이미지 방식으로 점진 전환한다.
팀원의 개발 방식은 바뀌지 않는다 — 도커는 CI/CD와 배포 서버 안에서만 쓰인다.

| 단계 | 내용 | 상태 |
|---|---|---|
| 1 | Dockerfile 2개 + compose 작성, 로컬 검증 | ✅ 완료 (2026-07-29) |
| 2 | Jenkinsfile에 이미지 빌드 스테이지 추가 (jar 배포와 병행) | ✅ 이 브랜치 |
| 3 | fake-ai → backend 순서로 컨테이너 배포 교체 | 예정 |
| 4 | systemd 유닛·릴리스 디렉토리 방식 폐기 | 예정 |

## 파일 구성

- `backend/Dockerfile` — Gradle 빌드 → JRE 런타임 2단계 이미지 (non-root 실행)
- `fake-ai/Dockerfile` — node 24 + uv sidecar 의존성 내장 (claude CLI는 `--build-arg WITH_CLAUDE=1`)
- `docker-compose.yml` — 리포 루트. 전체 스택(postgres + fake-ai + backend) 로컬 실행용, **팀원 선택사항**
- Jenkinsfile `Docker images: build` 스테이지 — master 병합 시 `jobis-backend:SHA`, `jobis-fake-ai:SHA` 이미지 빌드.
  Jenkins가 호스트 도커 데몬을 쓰므로(DooD) 빌드 즉시 배포 서버에 존재 — 레지스트리 불필요.
  이미지 태그는 최근 3개만 유지 (릴리스 정리와 동일 정책).

## 팀원 사용법 (선택)

```bash
docker compose up -d --build
# → http://localhost:8080/login.html
```

포트가 겹치면: `BACKEND_PORT=18080 FAKE_AI_PORT=18000 docker compose up -d`

기존 방식(IDE에서 bootRun, node server.js 직접 실행)은 그대로 유효 — 이 파일들은 아무것도 강제하지 않는다.

## 검증 기록 (2026-07-29, 배포 서버에서)

- 두 이미지 빌드 성공, compose 전체 스택 기동
- backend `/health` 200, `login.html` 200, Flyway 마이그레이션 정상 (Started in 9.4s)
- fake-ai `/extract` 정상 응답 (LLM_DISABLED=1)
- Jenkinsfile 스테이지의 빌드·태그 정리 명령을 동일 조건으로 서버에서 실행 확인
- fake-ai `init: true` 적용 전후 컨테이너 종료 시간: 10초(SIGTERM 무시 후 SIGKILL) → 0초

## 3단계 전 결정할 것

- fake-ai `server.js`에 SIGTERM 핸들러 추가 (WebSocket·codex sidecar 정상 종료).
  `init: true`는 프로세스가 시그널을 받게만 해주고, 진행 중인 작업을 정리하지는 않는다 —
  backend(Spring Boot graceful shutdown)와 격을 맞추려면 앱 레벨 처리가 필요하다
- 프로덕션 fake-ai의 claude CLI 폴백: `WITH_CLAUDE=1` 빌드 + 인증 방식(API 키 env) 결정
- 운영 postgres는 호스트 유지 → 컨테이너 backend에서 호스트 DB 접근 방법(`--add-host=host.docker.internal:host-gateway` 등) 확정
- systemd 서비스와 컨테이너의 포트 충돌 없는 교체 순서 (fake-ai:8000 먼저, backend:8080 다음)
