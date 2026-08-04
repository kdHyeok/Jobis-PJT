# JOBISS 배포 전환 및 운영 런북

이 문서는 특정 AI 도구에 의존하지 않는 배포 정본이다. 사람, Codex, Claude 등 어떤
작업자도 아래 파일과 검증 결과를 기준으로 같은 절차를 수행한다.

## 1. 정본과 배포 게이트

운영 애플리케이션은 커밋 SHA로 태그한 세 이미지다.

| 이미지 | 프로세스 | 호스트 포트 |
|---|---|---:|
| `jobis-ai:<SHA>` | `AI/src/jobis_ai/v2bridge/app.py` | 8000 |
| `jobis-backend:<SHA>` | Spring Boot API | 8080 |
| `jobis-frontend:<SHA>` | Vue 정적 파일 + API 프록시 | 8088 |

PostgreSQL, TLS를 종료하는 호스트 Nginx, Jenkins, Airflow/RAG는 첫 컨테이너 전환에서
호스트의 기존 구성을 유지한다. 운영 Compose가 `network_mode: host`를 쓰는 이유는
PostgreSQL과 RAG의 loopback 계약을 넓히지 않기 위해서다.

브랜치 게이트는 다음과 같다.

1. 기능 브랜치: 전체 소스 CI
2. `develop`: 전체 CI + 세 Docker 이미지 빌드 검증, 배포 없음
3. `master`: 같은 CI와 이미지 빌드가 성공한 뒤 운영 CD

`master` 직접 push는 금지하고 protected branch와 MR 승인으로만 이동한다. 운영 배포는
동시에 하나만 실행되어야 하며 Jenkins의 `disableConcurrentBuilds()`가 이를 보장한다.

Jenkins와 배포 서버가 다른 Docker daemon이면 `JOBIS_IMAGE_PREFIX` registry가 필수다.
동일 daemon 구성에서만 이 값을 비워 로컬 SHA 태그를 직접 사용할 수 있다.

## 2. 데이터 보호 원칙

DB 컨테이너 이미지나 Docker volume 자체는 데이터 백업이 아니다. 애플리케이션 이미지는
SHA 태그로 되돌리고, 데이터는 PostgreSQL custom-format 논리 덤프로 복구한다.

- 모든 CD 직전에 `/usr/local/sbin/backup-jobis-db <SHA>`가 성공해야 한다.
- 덤프와 checksum은 저장소/운영 디스크와 다른 마운트에 둔다.
- 매일 백업하고 월 1회 `restore-jobis-db-test`로 실제 복구한다.
- 복구는 운영 DB를 덮지 않고 새 DB 또는 격리 컨테이너에서 먼저 검증한다.
- Flyway 마이그레이션은 이전 애플리케이션과 양립 가능한 expand/contract 순서로 작성한다.

Airflow/jobrag DB는 별도 정본인 `infra/airflow/BACKUP_RESTORE.md`를 따른다.

## 3. 로컬 구현 검증

Windows PowerShell:

```powershell
./scripts/check.ps1
Copy-Item .env.compose-local.example .env
# .env의 비밀값과 사용할 LLM provider를 설정
docker compose config
docker compose build
docker compose up -d
curl.exe -fsS http://127.0.0.1:8088/api/auth/csrf
docker compose down
```

Docker가 없는 환경의 정적 검증은 최소 증거일 뿐 실제 Compose 기동 성공으로 표현하지 않는다.

## 4. 배포 서버 1회 준비

### 4.1 파일과 영속 경로

```bash
sudo bash ops/prepare-jobis-server "$(pwd)"
```

이 명령은 배포 사용자, root 소유 실행 파일, sudo 최소 권한, systemd unit, 영속 경로와
Nginx 후보 조각을 설치한다. 기존 레거시 `/etc/jobis/jobis.env`와 활성 Nginx 설정은 덮어쓰지 않고,
timer도 자동 활성화하지 않는다.

새 스택 전용 `/etc/jobis/jobis-v2.env`는 `.env.production.example`을 기준으로 서버에서 직접
작성한다. 레거시 env는 원본 컨테이너 복구용으로 그대로 보존한다.
저장소에 복사하거나 출력하지 않는다.

```bash
sudo chown root:root /etc/jobis/jobis-v2.env
sudo chmod 0600 /etc/jobis/jobis-v2.env
```

`.env.production.example`의 `DB_*` 이름은 Spring Boot와 백업 스크립트가 함께 쓰는 계약이다.
`JOBIS_IMAGE_PREFIX`에는 trailing slash까지 포함한다. 별도 배포 서버를 쓰면 root Docker
사용자가 최소 pull 권한의 deploy token으로 registry에 한 번 로그인한다.

```bash
sudo docker login registry.example.com
```

비밀번호나 token을 저장소, 배포 env, 로그에 기록하지 않는다. 로그인 결과는 root 전용
Docker credential store로 관리한다.

Jenkins SSH 공개키는 `jobis-deploy`의 `authorized_keys`에 설치하되 개인키는 Jenkins credential
store 밖으로 복사하거나 출력하지 않는다.

필수 값은 DB 연결/두 DB 사용자, JWT/AI 공유 비밀, HTTPS origin, LLM provider,
RAG 주소, 별도 백업 경로다.

### 4.2 Codex OAuth 초기화

`LLM_PROVIDER=codex`이면 이미지가 서버 Docker 데몬에 만들어진 뒤 한 번 로그인한다. 인증
파일의 내용을 화면이나 로그에 출력하지 않는다.

```bash
sudo docker run --rm -it --network host \
  --env-file /etc/jobis/jobis-v2.env \
  -e CODEX_OAUTH_STATE_DIR=/var/lib/jobis-ai/codex \
  -v /var/lib/jobis-ai:/var/lib/jobis-ai \
  --entrypoint python \
  jobis-ai:<검증할-SHA> \
  -m jobis_ai.codex_oauth_adapter.cli --login

sudo test -s /var/lib/jobis-ai/codex/auth.json
```

### 4.3 최초 백업과 복구 훈련

기존 `jobiss`와 신규 `jobiss_v2`는 한 DB에 덮어쓰지 않는다. 먼저 레거시 env로 `jobiss`를
백업하고 `legacy` 프로필로 복원한다.

```bash
sudo env \
  JOBIS_ENV_FILE=/etc/jobis/jobis.env \
  JOBIS_BACKUP_DIR=/mnt/jobis-backups/legacy-db \
  JOBIS_BACKUP_REQUIRE_SEPARATE_FILESYSTEM=false \
  /usr/local/sbin/backup-jobis-db manual

sudo env \
  JOBIS_ENV_FILE=/etc/jobis/jobis.env \
  JOBIS_BACKUP_DIR=/mnt/jobis-backups/legacy-db \
  JOBIS_RESTORE_PROFILE=legacy \
  /usr/local/sbin/restore-latest-jobis-db-test
```

위 `false`는 별도 디스크가 붙기 전 사전 백업만 허용한다. release 감사에서는 별도 파일시스템이
아니면 반드시 실패한다. develop에서 만든 세 SHA 이미지가 서버 Docker daemon에 생기고 별도
백업 파일시스템이 연결된 뒤, 다음 명령이 레거시 프로세스를 멈추지 않은 채 Flyway V27 적용,
빈 v2 백업, 트랜잭션 이관, 이관 후 백업·복원, timer 활성화를 한 번에 수행한다.

```bash
sudo /usr/local/sbin/prepare-jobis-v2-release <develop에서 검증한-40자리-SHA>
```

이관 대상은 사용자/인증 해시, 사용자 소유 공고, 대화·메시지, 분석 기록·결과, 이력 자료,
증거, 저장 로드맵이다. 소유자 없는 샘플 공고는 옮기지 않고 기존 `jobiss`에 보존한다.
`legacy_import_audit` 레코드가 없으면 SHA를 받은 predeploy 감사가 실패한다.

신규 DB의 일반 백업·복원 명령은 다음과 같다.

```bash
sudo /usr/local/sbin/backup-jobis-db manual
sudo /usr/local/sbin/restore-jobis-db-test \
  /mnt/jobis-backups/service-db/<생성된-dump>.dump
```

매일 백업과 월 1회 격리 복원 훈련은 설치된 systemd timer로 실행한다.

```bash
sudo systemctl enable --now jobis-db-backup.timer jobis-db-restore-drill.timer
sudo systemctl list-timers 'jobis-db-*'
```

### 4.4 호스트 Nginx

기존 TLS/Jenkins location은 보존한다. 1회 설치 명령은 기존 앱의 8080 proxy 한 줄만 제어용
include로 바꾸고, 활성 대상은 그대로 8080에 둔다. 원본 Nginx 파일은 timestamp 백업으로
보존한다.

```bash
sudo /usr/local/sbin/install-jobis-nginx-control
```

Jenkins의 `/jenkins/` location이 있다면 `/`보다 구체적인 별도 location으로 계속 유지한다.

환경, SSH 키, Docker/Compose, DB 두 계정, 백업 디스크, Nginx와 timer를 한 번에 감사한다.
값은 출력하지 않는다.

```bash
sudo /usr/local/sbin/audit-jobis-server
```

모든 `[FAIL]`을 해소한 뒤 최초 백업·복원 훈련과 CD로 진행한다. 이미지가 registry에 push된
뒤에는 40자리 SHA를 넘겨 세 이미지의 실제 가용성까지 다시 확인한다.

```bash
sudo /usr/local/sbin/audit-jobis-server <40자리-SHA> predeploy
```

## 5. develop → master → CD

1. 기능 브랜치 CI와 로컬 검증 결과를 MR에 기록한다.
2. `develop` MR 병합 후 Jenkins에서 모든 단계와 세 이미지 build/push 성공을 확인한다.
   최초 전환이면 해당 SHA로 `prepare-jobis-v2-release`를 실행해 데이터 준비를 완료한다.
3. `develop`을 `master`로 보내는 release MR에서 변경 파일, Flyway, env 추가값, 백업과
   롤백 방법을 재검토한다.
4. `master` 병합 후 Jenkins가 registry의 세 `<GIT_COMMIT>` 이미지를 빌드하고 push한다.
5. Jenkins는 SSH로 `audit-jobis-server <GIT_COMMIT> predeploy`를 통과시킨 뒤
   `sudo /usr/local/sbin/deploy-jobis <GIT_COMMIT>`를 호출한다.
6. 서버 스크립트가 이미지 pull/존재 확인 → DB 백업 → 기존 서비스 중지 → Compose 전환 → 세 계층
   smoke test → `postdeploy` 서버 감사 → `.deployed-sha` 기록 순으로 수행한다.
7. 어느 단계든 실패하면 직전 세 이미지 SHA로 재기동한다. 최초 전환에만 기존 systemd
   서비스가 최후 폴백이다.

## 6. 배포 후 검증

```bash
cat /opt/jobis/.deployed-sha
sudo docker ps --filter name=jobis-

curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8080/api/health
curl -fsS http://127.0.0.1:8088/
curl -fsS http://127.0.0.1:8088/api/auth/csrf

sudo docker logs --tail 100 jobis-ai
sudo docker logs --tail 100 jobis-backend
sudo docker logs --tail 100 jobis-frontend
```

AI health는 단순 HTTP 200뿐 아니라 `service=jobis-ai-v2bridge`여야 한다. 백엔드 health는
DB `select 1`까지 포함한다. 외부 HTTPS 도메인에서도 `/`와 `/api/auth/csrf`를 다시 확인한다.
실 LLM 기능 검증은 테스트 계정으로 채팅/분석 작업 하나를 만들고, 백엔드 작업 상태와 AI
로그에서 같은 요청이 완료된 것을 확인한다.

## 7. 롤백과 장애 처리

애플리케이션 롤백:

```bash
sudo -u jobis-deploy sudo /usr/local/sbin/deploy-jobis <직전-40자리-SHA>
```

DB 장애는 이미지 롤백과 분리한다. 현재 DB를 먼저 추가 백업하고, 검증된 덤프를 새 DB로
복구한 후 `DB_URL`을 전환한다. 운영 DB에 즉시 `pg_restore --clean`을 실행하지 않는다.

진단 순서:

1. `docker compose -f /opt/jobis/docker-compose.prod.yml ps`
2. `docker logs jobis-ai/jobis-backend/jobis-frontend`
3. `ss -lntp`로 8000/8080/8088 확인
4. AI health → backend health → frontend proxy → 외부 HTTPS 순서로 확인
5. 백엔드 500이면 요청 ID, 최초 애플리케이션 예외, PostgreSQL 로그와 DB 상태를 확인

두 번 이상의 정상 컨테이너 릴리스와 롤백 훈련을 확인한 뒤에만 서버의
`jobis-fake-ai.service`, `jobis.service`와 옛 릴리스 디렉터리를 제거한다.
