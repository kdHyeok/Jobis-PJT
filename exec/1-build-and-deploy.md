# 1. 빌드 및 배포 문서

GitLab 소스를 클론한 뒤 이 문서만으로 빌드·실행·배포가 재현되어야 한다.
포트·환경 변수·이미지 이름은 모두 저장소의 `compose.yaml`, `ops/docker-compose.prod.yml`,
`Jenkinsfile`에서 가져온 실제 값이다.

## 1. 사용 제품과 버전

### 1.1 런타임 (컨테이너 이미지에 고정)

| 구분 | 제품 | 버전 | 출처 |
|---|---|---|---|
| JVM (빌드) | Eclipse Temurin JDK | 17 (`eclipse-temurin:17-jdk-alpine`) | `backend/Dockerfile:1` |
| JVM (실행) | Eclipse Temurin JRE | 17 (`eclipse-temurin:17-jre-alpine`) | `backend/Dockerfile:9` |
| WAS | Spring Boot 내장 Tomcat | Spring Boot 4.1.0 | `backend/build.gradle:3` |
| 빌드 도구 | Gradle Wrapper | 9.5.1 | `backend/gradle/wrapper/gradle-wrapper.properties` |
| Java 언어 레벨 | JavaLanguageVersion | 17 | `backend/build.gradle:14` |
| 웹서버 | nginx (unprivileged) | 1.27-alpine | `frontend/Dockerfile:10` |
| 프론트 빌드 | Node.js | 22-alpine | `frontend/Dockerfile:1` |
| 프론트 프레임워크 | Vue / Vite / TypeScript | 3.5 / 7.0 / 5.7 | `frontend/package.json` |
| AI 서버 | Python | 3.11-slim (`requires-python >=3.11`) | `AI/Dockerfile:1`, `AI/pyproject.toml:9` |
| AI 실행 | uvicorn (`jobis_ai.v2bridge.app:app`) | 컨테이너 내부 8000 | `AI/Dockerfile` |
| AI 의존성 잠금 | uv (`uv.lock`) | `--frozen` 강제 | `AI/ci-checks` |
| 서비스 DB | PostgreSQL | 17-alpine | `compose.yaml:5` |
| RAG DB | pgvector/pgvector | pg16 | `infra/airflow/docker-compose.yml` |
| 데이터 파이프라인 | Apache Airflow | `infra/airflow/` Compose 묶음 | `infra/airflow/docker-compose.yml` |
| 스키마 마이그레이션 | Flyway (Spring Boot 통합) | 서비스 V1~V76, jobrag V1~V3 | `backend/src/main/resources/db/migration/` |

### 1.2 개발 환경

| 구분 | 값 |
|---|---|
| OS | Windows 11 (PowerShell 5.1 기준으로 스크립트 작성) / Linux 배포 서버 |
| 컨테이너 | Docker Desktop, Docker Compose v2 (`docker compose`, 하이픈 없음), Linux containers |
| 백엔드 IDE | IntelliJ IDEA — **팀에서 실제 사용한 버전을 여기에 기재한다** |
| 프론트 IDE | Visual Studio Code — **팀에서 실제 사용한 버전을 여기에 기재한다** |
| CI/CD | Jenkins (`Jenkinsfile`), GitLab (`lab.ssafy.com`) |

> IDE 버전은 저장소에 `.idea/`·`.vscode/` 설정이 커밋되어 있지 않아 소스에서 확인할 수 없다.
> 제출 전에 실제 사용 버전으로 채운다.

### 1.3 권장 자원

- CPU 4코어 이상, Docker Desktop 메모리 10~12GB 이상, 디스크 여유 20GB 이상
- RAG 로컬 임베딩/리랭킹은 컨테이너당 2 CPU를 사용한다(`docker stats`에서 약 200%가 정상)

## 2. 빌드

### 2.1 애플리케이션 (루트 Compose, 프로젝트명 `jobis-app`)

```powershell
docker compose config --quiet     # 환경 변수 해석 검증
docker compose build              # backend / ai / frontend 이미지 빌드
docker compose up -d
docker compose ps
```

정상 상태: `postgres`, `ai`, `backend`가 `healthy`, `frontend`가 `running`.
`frontend`만 호스트 포트(`8088`)를 연다. PostgreSQL과 AI 8000은 내부 네트워크
(`jobiss-internal`)에만 열린다 — 호스트에서 `localhost:8000`에 붙지 않는 것이 정상이다.

### 2.2 데이터 파이프라인 (`infra/airflow`, 프로젝트명 `jobis-data-pipeline`)

`rag-search`는 Compose 서비스지만, Airflow DockerOperator가 실행하는 `rag-ingest`는
별도 이미지다. 둘 다 빌드해야 한다.

```powershell
cd infra\airflow
docker compose build
docker build -t jobis/rag-ingest:latest -f Dockerfile.rag-ingest ..\..
docker compose up -d
```

`jobrag-migrate`와 `airflow-init`은 1회 실행 후 종료되는 작업이므로 `Exited (0)`이 성공이다.

### 2.3 소스 전체 검증 (Docker 없이)

Java 17, Node.js/npm, `uv`가 설치된 개발 환경에서 실행한다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

백엔드 테스트, AI 테스트·구조 검사, 프론트엔드 단위 테스트·프로덕션 빌드·Playwright E2E,
격리 PostgreSQL 검사를 실행한다. 단위 테스트 성공을 실제 LLM API 호출 성공으로 표현하지 않는다.

## 3. 빌드·실행 환경 변수

**환경 파일은 두 개뿐이다.** 두 Compose 파일 모두 `env_file` 지시자가 없고 전부 `${VAR}`
보간이므로, Docker Compose가 각 프로젝트 디렉터리의 `.env`를 자동으로 읽는다.

| 파일 | 대상 | 예제 |
|---|---|---|
| 저장소 루트 `.env` | 애플리케이션 묶음 (`compose.yaml`) | `.env.compose-local.example` |
| `infra/airflow/.env` | Airflow·RAG 묶음 | `infra/airflow/.env.example` |

`AI/.env`, `RAG/.env.example` 등은 Docker 실행 경로에서 사용하지 않는다.
AI 서버의 `AI/src/jobis_ai/config.py`도 저장소 루트 `.env`를 읽는다.

### 3.1 루트 `.env` — 반드시 채워야 하는 값

Compose가 `${VAR:?}`로 강제하므로 비면 기동 자체가 실패한다.

| 변수 | 설명 |
|---|---|
| `POSTGRES_MIGRATOR_PASSWORD` | Flyway 마이그레이션 계정 비밀번호 |
| `POSTGRES_APP_PASSWORD` | 애플리케이션 런타임 계정 비밀번호 (위와 다른 값) |
| `JWT_SECRET` | 최소 32바이트 |
| `AI_SHARED_SECRET` | backend ↔ AI 내부 인증. 두 컨테이너에 같은 값이 주입된다 |
| `ALLOWED_ORIGINS` | 로컬은 `http://localhost:8088` |

### 3.2 루트 `.env` — 실행 모드를 정하는 값

| 변수 | 로컬 기본값 | 설명 |
|---|---|---|
| `LLM_PROVIDER` | `anthropic` | 팀 표준(D140). `openai`(GMS) · `codex`(OAuth) · `claude_code` · `codex_cli` 선택 가능 |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | (키 필요) / `claude-haiku-4-5-20251001` | anthropic 경로. **Docker 에서는 전 티어가 이 한 모델을 쓴다**(아래 3.4) |
| `GMS_KEY` / `LLM_BASE_URL` / `LLM_MODEL` | — / GMS URL / `gpt-4.1-mini` | openai(GMS) 경로 |
| `CODEX_MODEL` 등 | `gpt-5.4` | codex 경로. 컨테이너 안에서 1회 OAuth 로그인 필요 (4.1절) |
| `RAG_PROVIDER` | `null` | RAG 묶음을 띄웠을 때만 `http` |
| `RAG_SEARCH_URL` | `http://host.docker.internal:8765` | 컨테이너에서 호스트의 RAG 검색을 본다 |
| `SPRING_PROFILES_ACTIVE` | `local` | 운영은 `prod` |
| `COOKIE_SECURE` | `false` | HTTP 로컬. HTTPS 운영은 `true` |
| `JOBISS_HTTP_PORT` | `8088` | 프론트 호스트 포트 |
| `AUTH_COOKIE_NAME` | `jobiss_access` | 같은 호스트에 여러 스택을 띄울 때만 변경 |
| `JOBIS_JINA_ENABLED` 등 | `true` | 공고 원문 추출 폴백. 키가 없으면 해당 폴백만 건너뛴다 |
| `CLOVA_API_KEY` / `CLOVA_VLM_URL` | (선택) | 이미지 공고 OCR/VLM |

### 3.3 `infra/airflow/.env` — 반드시 채워야 하는 값

| 변수 | 생성 방법 |
|---|---|
| `POSTGRES_PASSWORD`, `AIRFLOW_DB_PASSWORD`, `JOBRAG_DB_PASSWORD` | 각각 다른 난수 |
| `AIRFLOW_ADMIN_PASSWORD` | 강한 비밀번호 |
| `AIRFLOW_FERNET_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `DOCKER_GID` | Linux는 `getent group docker \| cut -d: -f3`, Windows Docker Desktop은 `999` |
| `JOBIS_LEGACY_SQLITE_PATH` | 최초 1회 공고 import 원본 경로 |

RAG는 최초 재현 시 비용이 들지 않는 로컬 모델(`RAG_EMBED_PROVIDER=local`,
`RAG_RERANK_PROVIDER=local`, `BAAI/bge-m3`, `BAAI/bge-reranker-v2-m3`, 차원 1024)을 쓴다.
provider나 모델을 바꾸면 기존 벡터를 재사용하지 않고 전량 재임베딩하므로 GMS로 바꿀 때는
키 한도와 과금을 먼저 확인한다.

PowerShell 5.1에서 난수를 만들 때는 `RandomNumberGenerator.Fill()`과 `Convert.ToHexString()`이
없으므로 [RUN.md](../RUN.md) 3장의 `New-SafeSecret` / `New-FernetKey` 함수를 사용한다.

### 3.4 로컬 Docker에서 컨테이너에 전달되지 않는 값

루트 `compose.yaml`은 `environment:` **허용목록** 방식이다(운영 `ops/docker-compose.prod.yml`은
`env_file`로 파일 전체를 넘긴다). 따라서 `.env`에 적어도 로컬 컨테이너에 닿지 않는 값이 있다.
값 자체의 정본은 `.env.production.example`이다.

| 전달되지 않는 값 | 로컬에서의 결과 |
|---|---|
| `ANTHROPIC_MODEL_LIGHT`, `ANTHROPIC_MODEL_ROUTER` | 경량·라우터 티어가 고급 티어(`ANTHROPIC_MODEL`)로 폴백한다. **3티어 구성이 성립하지 않고 한 모델로 전부 돈다** |
| `MAIL_*`, `PASSWORD_RESET_*`, `PUBLIC_APP_URL` | 비밀번호 재설정 링크가 메일이 아니라 서버 로그로 출력된다 |
| `REPOSITORY_TOKEN_ENCRYPTION_KEY`, `SENSITIVE_DATA_*` | 애플리케이션의 로컬 개발용 기본 키가 쓰인다 |
| `GITHUB_APP_*`, `GITLAB_CLIENT_*` | 저장소 연동이 비활성 상태로 동작한다 |
| `ACCESS_TOKEN_SECONDS`, `REFRESH_TOKEN_SECONDS` 등 | 애플리케이션 기본값(2시간 / 14일) |
| `LLM_TEMPERATURE`, `EMBED_PROVIDER`, `MODEL_VERSION`, `CODEX_EFFORT` | AI 기본값(0.3 / `null` / `jarvis-0.1.0` / `low`) |

라우팅 품질이 중요하면 Docker 로컬에서는 `ANTHROPIC_MODEL`에 경량 모델 대신 상위 모델을
지정한다. 티어를 제대로 나누려면 `compose.yaml`의 `ai` 서비스 `environment:`에 위 값을
추가하는 MR이 필요하다(Infra 리뷰 대상 — 루트 AGENTS.md의 CI/CD 소유권 표).

## 4. 배포 시 특이사항

배포 절차의 정본은 [ops/DEPLOYMENT.md](../ops/DEPLOYMENT.md), CI 소유권은
[ops/CI_OWNERSHIP.md](../ops/CI_OWNERSHIP.md)다. 아래는 반드시 알아야 하는 제약이다.

### 4.1 Build Once, Deploy Many

- `develop`에서 커밋 SHA로 태그한 **여섯 이미지**를 빌드·push한다:
  `jobis-ai`, `jobis-backend`, `jobis-frontend`, `jobis-rag-search`, `jobis-rag-ingest`, `jobis-airflow`.
- `master`는 **다시 빌드하지 않는다.** `Master release: verify`가 master 트리와 검증된
  develop 부모 트리가 동일한지 강제한 뒤 이미지를 승격만 한다. 이 원칙을 깨는 변경은 리뷰에서 되돌린다.
- Jenkins와 배포 서버가 다른 Docker 데몬이면 `JOBIS_IMAGE_PREFIX`(끝의 `/` 포함)가 필수다.

### 4.2 운영 포트 고정

운영 `ops/docker-compose.prod.yml`은 backend에 `SERVER_PORT: "8080"`을 명시한다.
애플리케이션 기본 포트가 8380으로 바뀌었을 때 헬스체크가 실패해 릴리스가 롤백된 실측
사고(2026-08-08)가 있어 고정한 값이다. 현재 애플리케이션 기본값도 8080으로 되돌렸다.

### 4.3 운영은 `env_file`, 로컬은 허용목록

- 운영: `env_file: /etc/jobis/jobis-v2.env` — 파일 전체가 backend 컨테이너에 들어간다.
- 로컬: `compose.yaml`은 `environment:` 허용목록 방식이라 일부 값이 컨테이너에 닿지 않는다.
  전체 목록과 영향은 3.4절에 있다.

### 4.4 메모리 상한

Jenkins와 운영이 같은 호스트를 쓴다(가용 메모리 약 2GB·스왑 0). 백엔드 JVM은
`-XX:MaxRAMPercentage=75`로 실행되므로 컨테이너 상한이 곧 힙 상한이다. 상한이 없으면
호스트 전체를 기준으로 힙을 잡아 OOM killer가 운영 컨테이너를 죽인다(2026-08-06 장애).
`ops/docker-compose.prod.yml`의 `mem_limit`와 `ops/compose.smoke.yml`의 스모크 상한을 유지한다.

### 4.5 CI 스모크의 호스트 경로 치환

Jenkins는 DooD(Docker outside of Docker)로 돈다. 중첩 컨테이너의 바인드 마운트는 호스트
데몬이 경로 문자열로 풀기 때문에 `$WORKSPACE`를 그대로 넘기면 데몬이 빈 디렉터리를 만들어
마운트하고, PostgreSQL 초기화 스크립트가 사라져 V1이 `role "jobiss_app" does not exist`로
죽는다(2026-08-09 develop #45). `Jenkinsfile`이 `SMOKE_HOST_ROOT`로 호스트 기준 경로를 넘기고
`ops/smoke-compose`가 기동 전에 이를 검사한다.

### 4.6 마이그레이션 번호 충돌

`backend/src/main/resources/db/migration/`과 `infra/airflow/migrations/`는 **별개 체인**이다.
파일을 추가하기 전에 `origin/develop`의 최신 번호를 확인한다. 번호가 같으면 파일명이 달라도
Flyway가 기동을 거부한다(`Found more than one migration with version N`). 두 마이그레이션이
같은 함수를 `CREATE OR REPLACE` 하면 나중 것이 앞의 수정을 통째로 덮으므로 손으로 병합한다.

### 4.7 데이터 보호

- DB 컨테이너 이미지나 Docker volume은 백업이 아니다. 복구는 PostgreSQL 논리 덤프로 한다.
- 모든 CD 직전에 `/usr/local/sbin/backup-jobis-db <SHA>`가 성공해야 한다.
- `docker compose down -v`는 실제 데이터를 지운다. 일반 재시작 절차에서 사용하지 않는다.
  컨테이너만 멈출 때는 `docker compose stop`을 쓴다.
- 보존해야 하는 볼륨: `data-airflow_jobiss_postgres_data`(서비스 DB),
  `data-airflow_jobiss_ai_state`(AI 세션·Codex OAuth), `airflow_pgdata`, `airflow_airflow-logs`,
  `jobis-crawl-state`, `jobis-crawl-exports`, 모델 캐시(`jobis-hf-cache` 등).

### 4.8 Codex OAuth (운영에서 `LLM_PROVIDER=codex`일 때만)

이미지가 서버 Docker 데몬에 생긴 뒤 1회 로그인한다. 인증 파일 내용을 화면·로그·Git에 남기지 않는다.

```bash
sudo docker run --rm -it --network host \
  --env-file /etc/jobis/jobis-v2.env \
  -e CODEX_OAUTH_STATE_DIR=/var/lib/jobis-ai/codex \
  -v /var/lib/jobis-ai:/var/lib/jobis-ai \
  --entrypoint python jobis-ai:<SHA> \
  -m jobis_ai.codex_oauth_adapter.cli --login
```

Docker 이미지에는 console script가 설치되지 않으므로 `jobis-codex-oauth` 실행 파일은 없다.
반드시 위와 같이 Python 모듈로 진입한다.

## 5. DB 접속 정보 및 주요 계정·프로퍼티가 정의된 파일 목록

### 5.1 계정·프로퍼티 정의 파일

| 파일 | 역할 |
|---|---|
| `.env.compose-local.example` | 로컬 Docker용 예제. 복사해서 루트 `.env`로 사용 |
| `.env.example` | Docker 없이 `scripts/`로 개별 실행할 때의 예제 |
| `.env.production.example` | 운영 `/etc/jobis/jobis-v2.env`의 정본 예제 (전체 키 목록) |
| `infra/airflow/.env.example` | Airflow·RAG 묶음 예제 |
| `backend/src/main/resources/application.yml` | Spring 프로퍼티와 기본값 정의 |
| `compose.yaml` | 로컬 컨테이너에 실제로 주입되는 값의 허용목록 |
| `ops/docker-compose.prod.yml` | 운영 컨테이너 구성 |
| `infra/postgres/init/` | DB 최초 기동 시 app 역할을 만드는 초기화 스크립트 |
| `backend/src/main/resources/db/migration/` | 서비스 스키마 Flyway 체인 (V1~V76) |
| `infra/airflow/migrations/jobrag/` | RAG 스키마 Flyway 체인 (V1~V3) |

**실제 비밀값이 담긴 파일(`.env`, `infra/airflow/.env`, `/etc/jobis/jobis-v2.env`)은 Git에 올리지 않는다.**

### 5.2 DB 계정 구조

서비스 DB는 권한이 다른 두 계정을 쓴다. 이름은 `.env`로 바꿀 수 있고 기본값은 다음과 같다.

| 계정 | 기본 이름 | 용도 | 관련 변수 |
|---|---|---|---|
| 마이그레이션 | `jobiss_migrator` | Flyway DDL. 컨테이너 superuser | `POSTGRES_MIGRATOR_USER` / `POSTGRES_MIGRATOR_PASSWORD` |
| 애플리케이션 | `jobiss_app` | 런타임 DML | `POSTGRES_APP_USER` / `POSTGRES_APP_PASSWORD` |

| 항목 | 로컬 Docker | 운영 |
|---|---|---|
| DB 이름 | `jobiss` (`POSTGRES_DB`) | `jobiss_v2` |
| 접속 주소 | 컨테이너 내부 `postgres:5432` | `127.0.0.1:5432` (loopback 전용) |
| 호스트 노출 | 없음 | 없음 |
| Spring 접속 URL | `jdbc:postgresql://postgres:5432/jobiss` (compose가 조립) | `DB_URL` |

Airflow·RAG DB는 별도다: Airflow 메타 DB `airflow`(`AIRFLOW_DB_*`), 벡터 DB `jobrag`
(`JOBRAG_DB_*`, `JOBRAG_PG_DSN`, `JOBRAG_FLYWAY_URL`).

### 5.3 DB 덤프 복원

`exec/jobis-db-dump.sql`은 실행 중인 서비스 DB(PostgreSQL 17)의 plain SQL 덤프이며
`--clean --if-exists`로 생성했다. 빈 DB에 복원한다.

```powershell
docker compose up -d postgres
Get-Content exec\jobis-db-dump.sql | docker compose exec -T postgres psql -U jobiss_migrator -d jobiss
```

복원은 운영 DB를 덮지 않고 새 DB 또는 격리 컨테이너에서 먼저 검증한다.

## 6. 실행 확인

```powershell
Invoke-RestMethod http://localhost:8088/api/health | ConvertTo-Json -Depth 10
(Invoke-WebRequest -UseBasicParsing http://localhost:8088).StatusCode
docker compose ps -a
docker compose logs --tail 100 ai backend frontend
```

RAG까지 띄웠다면 `http://localhost:8765/health`의 `status=ok`, `warm=true`,
`corpus_chunks > 0`을 확인한다. `corpus_chunks=0`이면 서버는 살아 있으나 색인이 없는 것이다.

AI health가 HTTP 200이라는 것은 프로세스가 준비됐다는 뜻일 뿐이다. 실제 LLM 호출 성공은
분석·대화 완주로 따로 확인한다. 스트리밍 HTTP 200도 연결이 열렸다는 뜻일 뿐이므로 최종
완료 이벤트나 UI 완료 상태까지 본다.
