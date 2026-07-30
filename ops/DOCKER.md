# JOBIS Docker 전환

서비스 배포를 jar/systemd 방식에서 도커 이미지 방식으로 점진 전환한다.
팀원의 개발 방식은 바뀌지 않는다 — 도커는 CI/CD와 배포 서버 안에서만 쓰인다.

| 단계 | 내용 | 상태 |
|---|---|---|
| 1 | Dockerfile 2개 + compose 작성, 로컬 검증 | ✅ 완료 (2026-07-29) |
| 2 | Jenkinsfile에 이미지 빌드 스테이지 추가 (jar 배포와 병행) | ✅ 완료 (2026-07-30, master #3) |
| 3 | fake-ai·backend를 컨테이너 배포로 교체 | ✅ 이 브랜치 |
| 4 | systemd 유닛 파일·릴리스 디렉토리 제거 | 예정 (3단계 안정화 후) |

## 파일 구성

- `backend/Dockerfile` — Gradle 빌드 → JRE 런타임 2단계 이미지 (non-root 실행)
- `fake-ai/Dockerfile` — node 24 + uv sidecar 의존성 내장 (claude CLI는 `--build-arg WITH_CLAUDE=1`)
- `docker-compose.yml` — 리포 루트. 전체 스택(postgres + fake-ai + backend) 로컬 실행용, **팀원 선택사항**
- Jenkinsfile `Docker images: build` 스테이지 — master 병합 시 `jobis-backend:SHA`, `jobis-fake-ai:SHA` 이미지 빌드.
  Jenkins가 호스트 도커 데몬을 쓰므로(DooD) 빌드 즉시 배포 서버에 존재 — 레지스트리 불필요.
  이미지 태그는 최근 3개만 유지 (릴리스 정리와 동일 정책).
- `ops/docker-compose.prod.yml` — **운영 전용**. 호스트 네트워크 + 호스트 postgres 사용
- `ops/deploy-jobis-container` — 컨테이너 배포 스크립트 (기존 `deploy-jobis`를 대체)

## 운영 배포 구조 (3단계)

컨테이너로 옮기는 것은 **fake-ai와 backend 둘뿐**이다. postgres·nginx·Jenkins는 호스트에 그대로 둔다.

호스트 네트워크(`network_mode: host`)를 쓰는 이유:

- 운영 postgres가 `listen_addresses=localhost`, `pg_hba`도 `127.0.0.1/32`만 허용한다.
  브리지 네트워크에서는 접근 불가(`host.docker.internal` → no response 확인),
  호스트 네트워크에서는 접속 성공(`accepting connections` 확인).
- postgres 설정 변경·재시작이 필요 없고, nginx 프록시 대상(`127.0.0.1:8080`)도 그대로다.
- `/etc/jobis/jobis.env`의 `AGENT_WS_URL=ws://127.0.0.1:8000`도 수정 없이 유효하다.
  (이 ws는 backend→fake-ai 루프백 연결이라 브라우저용 wss 핫픽스와 무관하다. fake-ai는 TLS 미지원.)

codex 자격증명은 API 키가 아니라 OAuth 상태 파일이므로 디렉토리를 읽기·쓰기로 마운트한다
(토큰 갱신 시 파일에 다시 씀). 호스트 ubuntu와 컨테이너 node가 모두 uid 1000이라 권한 조정이 필요 없다.

### 서버 설치 (배포 방식 변경 시 1회, 루트 권한 필요)

```bash
sudo install -o root -g root -m 0755 ops/deploy-jobis-container /usr/local/sbin/deploy-jobis
sudo install -o root -g root -m 0644 ops/docker-compose.prod.yml /opt/jobis/docker-compose.prod.yml
```

Jenkins는 `/usr/local/sbin/deploy-jobis`를 호출할 뿐 스크립트를 전송하지 않으므로,
`ops/` 아래 파일을 고쳤다면 위 설치를 다시 해야 반영된다.

### 롤백

- 이전 SHA 이미지가 남아 있으면(태그 3개 유지) 스크립트가 자동으로 이전 태그로 재기동한다.
- 되돌릴 이미지가 없는 최초 전환 실패 시에는 컨테이너를 내리고 systemd 유닛으로 복귀한다.
- 수동 롤백: `sudo JOBIS_SHA=<이전SHA> docker compose -f /opt/jobis/docker-compose.prod.yml up -d`

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
