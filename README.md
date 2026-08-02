# JOBISS Service v2 로컬 개발 가이드

이 문서는 서비스 소개보다 **팀원이 같은 개발 환경을 재현하고 직접 기능을 검증하는 방법**에 초점을 둡니다.

현재 브랜치의 실행 구성은 다음과 같습니다.

| 구성 | 기술 | 기본 주소 |
|---|---|---|
| 프론트엔드 | Vue 3, TypeScript, Vite | `http://localhost:5173` |
| 백엔드 | Java 17, Spring Boot | `http://localhost:8080` |
| 로컬 AI 어댑터 | Python 3.12, FastAPI, Claude CLI | `http://localhost:8000` |
| 데이터베이스 | PostgreSQL 17, Flyway, RLS | `localhost:55432` |

> `ai-server/`는 팀의 실제 LangGraph 에이전트인 `AI/`를 대체하는 코드가 아닙니다.
> 백엔드와 AI 사이의 HTTP·JSON 계약을 로컬에서 검증하기 위한 어댑터입니다.
> 실제 AI가 같은 계약을 구현하면 백엔드의 `AI_SERVER_URL`만 변경해 교체할 수 있습니다.

---

## 1. 최초 설치 전 준비물

Windows PowerShell 기준입니다.

| 프로그램 | 요구 버전 | 확인 명령 |
|---|---:|---|
| Git | 최신 안정 버전 | `git --version` |
| Java JDK | 17 이상 | `java --version` |
| Node.js | `20.19+` 또는 `22.12+` | `node --version` |
| Python | 3.12 이상 | `python --version` |
| PostgreSQL | 17 권장 | `& 'C:\Program Files\PostgreSQL\17\bin\postgres.exe' --version` |
| Claude Code CLI | 로그인된 최신 버전 | `claude --version` |

현재 개발에 사용한 버전은 다음과 같습니다.

```text
Java       17.0.19
Node.js    24.18.0
Python     3.12.12
PostgreSQL 17.10
Claude CLI 2.1.220
```

### Java가 여러 버전 설치된 경우

Gradle 실행 전에 Java 17 경로를 지정합니다.

```powershell
$env:JAVA_HOME='C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot'
$env:Path="$env:JAVA_HOME\bin;$env:Path"
java --version
```

IntelliJ에서도 다음 두 곳을 모두 Java 17로 지정해야 합니다.

1. `File → Project Structure → Project SDK`
2. `Settings → Build Tools → Gradle → Gradle JVM`

---

## 2. 저장소 준비

브랜치가 원격에 공유된 이후에는 다음과 같이 받습니다.

```powershell
git fetch origin
git switch feat/be/jobiss-service-v2
```

로컬 비밀값 파일은 Git에 올리지 않습니다.

```text
.env
backend/.env
ai-server/.env
```

예제 파일인 `.env.example`만 저장소에 포함합니다.

---

## 3. 최초 1회 설치

### 3.1 PostgreSQL 준비

이 프로젝트는 기존 MySQL이나 로컬 5432 데이터베이스를 건드리지 않습니다.
프로젝트 전용 PostgreSQL 클러스터를 `.local/postgres-data`에 만들고 `55432` 포트를 사용합니다.

```powershell
cd C:\S15P11C202
powershell -ExecutionPolicy Bypass -File .\scripts\start-local-postgres.ps1
```

정상 출력:

```text
JOBISS PostgreSQL is ready at localhost:55432.
```

스크립트가 자동으로 준비하는 항목:

- 데이터베이스: `jobiss`
- Flyway 역할: `jobiss_migrator`
- 애플리케이션 역할: `jobiss_app`
- 로컬 데이터 디렉터리: `.local/postgres-data`
- 포트: `55432`

기본 로컬 비밀번호는 개발 전용이며 `application.yml`의 기본값과 일치합니다.
운영 환경에서는 절대 사용하지 않습니다.

### 3.2 AI 어댑터 설치

Claude CLI가 설치되어 있고 로그인되어 있는지 먼저 확인합니다.

```powershell
claude --version
claude auth status
```

AI 서버의 가상환경과 의존성을 설치합니다.

```powershell
cd C:\S15P11C202\ai-server
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

`ai-server/.env`의 기본 로컬 설정:

```dotenv
JOBISS_AI_ENVIRONMENT=local
JOBISS_AI_SHARED_SECRET=local-ai-secret
JOBISS_AI_ANALYSIS_PROVIDER=claude_cli
JOBISS_AI_CLAUDE_CLI_MODEL=sonnet
JOBISS_AI_REQUEST_TIMEOUT_SECONDS=600
JOBISS_AI_PROGRESS_LOG_INTERVAL_SECONDS=10
JOBISS_AI_MAX_CONCURRENCY=2
```

Anthropic API를 사용할 때만 다음 값으로 변경합니다.

```dotenv
JOBISS_AI_ANALYSIS_PROVIDER=anthropic
JOBISS_AI_ANTHROPIC_API_KEY=발급받은_API_KEY
JOBISS_AI_ANTHROPIC_MODEL=claude-sonnet-4-6
```

### 3.3 프론트엔드 설치

```powershell
cd C:\S15P11C202\frontend
npm ci
```

`npm install`보다 잠금 파일을 그대로 재현하는 `npm ci`를 권장합니다.

### 3.4 백엔드 준비

Gradle Wrapper가 필요한 의존성을 자동으로 받으므로 별도의 Gradle 설치는 필요하지 않습니다.

```powershell
cd C:\S15P11C202\backend
.\gradlew.bat test
```

IntelliJ에서는 `C:\S15P11C202\backend`를 Gradle 프로젝트로 열고 다음 클래스를 실행합니다.

```text
com.jobiss.JobissBackendApplication
```

---

## 4. 매일 실행하는 순서

아래 네 프로세스를 각각 다른 터미널에서 실행합니다.

### 터미널 1: PostgreSQL

```powershell
cd C:\S15P11C202
powershell -ExecutionPolicy Bypass -File .\scripts\start-local-postgres.ps1
```

이미 실행 중이면 기존 클러스터를 그대로 사용합니다.

### 터미널 2: AI 어댑터

```powershell
cd C:\S15P11C202\ai-server
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

상태 확인:

```powershell
Invoke-RestMethod http://localhost:8000/health
```

응답의 `provider`가 `claude_cli`인지 확인합니다.

AI 작업 중에는 같은 PowerShell에 아래와 같은 안전한 진행 로그가 10초 간격으로 표시됩니다.

```text
JOBISS_AI_PROGRESS operation=posting_analysis request_id=... phase=final_proposal attempt=1 state=running elapsed_seconds=30.0 timeout_seconds=540.0
```

`started`, `connected`, `generation_started`, `structured_output_started`, `running`, `completed` 상태로 실제 진행 여부를 확인할 수 있습니다. 모델의 비공개 사고 과정, 공고·이력서 원문, 생성 중인 부분 JSON은 로그에 남기지 않습니다.

### 터미널 3: 백엔드

IntelliJ에서 `JobissBackendApplication`을 실행하거나 다음 명령을 사용합니다.

```powershell
$env:JAVA_HOME='C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot'
$env:Path="$env:JAVA_HOME\bin;$env:Path"

cd C:\S15P11C202\backend
.\gradlew.bat bootRun
```

백엔드를 시작하면 Flyway가 자동으로 마이그레이션을 실행합니다.

상태 확인:

```powershell
Invoke-RestMethod http://localhost:8080/api/health
```

### 터미널 4: 프론트엔드

```powershell
cd C:\S15P11C202\frontend
npm run dev
```

브라우저 접속:

```text
http://localhost:5173
```

Vite가 `/api` 요청을 `http://localhost:8080`으로 프록시합니다.

---

## 5. 팀원이 확인해야 할 기본 기능

### 5.1 회원가입과 로그인

1. `http://localhost:5173`에 접속합니다.
2. 새 계정을 만듭니다.
3. 로그인 후 홈 화면으로 이동하는지 확인합니다.
4. 새 계정의 커리어 지도에 공통 기반 단계가 생성됐는지 확인합니다.

### 5.2 자유 대화

1. `AI와 대화`로 이동합니다.
2. 공고를 첨부하지 않고 다음과 같이 입력합니다.

```text
백엔드 개발자로 취업하고 싶은데 지금 무엇부터 정리하면 좋을까요?
```

확인할 내용:

- 사용자 메시지가 AI 응답보다 먼저 즉시 표시됩니다.
- AI 답변은 백그라운드 작업 상태로 표시됩니다.
- 공고가 없어도 대화를 계속할 수 있습니다.

### 5.3 커리어 저장소

다음과 같은 프로젝트 경험을 등록해 봅니다.

```text
Spring Boot와 PostgreSQL로 게시판 API를 개발했습니다.
JUnit으로 서비스 계층 테스트를 작성했고, 느린 목록 조회 쿼리를 측정해 인덱스를 적용했습니다.
Dockerfile과 실행 방법을 작성해 다른 환경에서도 실행할 수 있게 구성했습니다.
```

확인할 내용:

- 원본 자료가 즉시 저장됩니다.
- AI가 기술·프로젝트·성과를 검토 가능한 조각으로 제안합니다.
- 사용자가 선택한 조각만 확정됩니다.
- 검색·정렬·수정·병합·보관·복원·삭제가 동작합니다.

### 5.4 혼합 직무 공고의 추가 질문

다음처럼 프론트엔드와 백엔드가 섞인 공고를 등록합니다.

```text
웹 개발자 채용

프론트엔드 또는 백엔드 개발자를 모집합니다.

프론트엔드 우대:
- TypeScript, React, Next.js 경험
- 웹 접근성과 성능 개선 경험

백엔드 우대:
- Java 또는 Kotlin
- Spring Boot, JPA, REST API 경험
- PostgreSQL과 Docker 사용 경험

신입·경력 모두 지원 가능합니다.
```

예상 흐름:

1. 공고 분석이 백그라운드에서 시작됩니다.
2. AI가 목표 트랙에 따라 결과가 달라진다고 판단합니다.
3. `프론트엔드 / 백엔드 / 둘 다 / 미정`과 같은 선택형 질문이 표시됩니다.
4. 질문은 한 번에 하나만 나타납니다.
5. 답변하면 같은 분석 작업이 다시 `QUEUED` 상태로 들어갑니다.
6. 답변을 반영해 분석이 계속됩니다.

질문은 공고 상세 화면과 대화 화면 중 어느 쪽에서도 답할 수 있습니다.

### 5.5 분석 완료와 커리어 지도 반영

분석 완료까지 로컬 Claude CLI 기준 수십 초에서 수 분이 걸릴 수 있습니다.
단일 AI 호출 제한은 10분이며 화면을 나가도 작업은 계속됩니다.
화면을 나가도 작업은 계속됩니다.

확인할 내용:

- 완료 알림이 도착합니다.
- `지금 지원 / 보강 후 지원 / 대체 공고 우선` 중 하나가 표시됩니다.
- 필수·우대 요구사항이 분리됩니다.
- 기존 노드 재사용과 새 노드 제안이 구분됩니다.
- 사용자가 승인하기 전에는 커리어 지도가 변경되지 않습니다.
- 승인한 변경안만 지도에 병합됩니다.

---

## 6. 전체 자동 검증

최초 설치가 끝난 뒤 루트에서 한 번에 실행할 수 있습니다.

```powershell
$env:JAVA_HOME='C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot'
$env:Path="$env:JAVA_HOME\bin;$env:Path"

cd C:\S15P11C202
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

검증 항목:

- 백엔드 Gradle 테스트
- AI 서버 Pytest
- AI 서버 Ruff 린트
- 프론트엔드 TypeScript 검사
- 프론트엔드 프로덕션 빌드

성공 시 다음 문구가 출력됩니다.

```text
All available JOBISS checks passed.
```

---

## 7. 종료 방법

프론트엔드·백엔드·AI 서버는 각 터미널에서 `Ctrl+C`로 종료합니다.

PostgreSQL은 다음 스크립트로 종료합니다.

```powershell
cd C:\S15P11C202
powershell -ExecutionPolicy Bypass -File .\scripts\stop-local-postgres.ps1
```

---

## 8. 선택 사항: Docker Compose

로컬 Claude CLI는 컨테이너 내부에서 사용하지 않습니다.
Docker Compose 실행은 Anthropic API 키가 있을 때 사용합니다.

저장소에는 기존 서비스용 `docker-compose.yml`과 v2용 `compose.yaml`이 함께 있으므로,
반드시 `compose.yaml`을 명시합니다.

```powershell
cd C:\S15P11C202
Copy-Item .env.compose-local.example .env
```

`.env`에서 비밀번호와 `ANTHROPIC_API_KEY`를 변경한 뒤 실행합니다.

```powershell
docker compose -f compose.yaml up --build
```

접속 주소:

```text
http://localhost:8088
```

---

## 9. 환경 변수

로컬 기본값으로 실행할 때는 백엔드 환경 변수를 따로 설정하지 않아도 됩니다.

주요 백엔드 환경 변수:

| 변수 | 로컬 기본값 |
|---|---|
| `DB_URL` | `jdbc:postgresql://localhost:55432/jobiss` |
| `DB_MIGRATOR_USER` | `jobiss_migrator` |
| `DB_APP_USER` | `jobiss_app` |
| `AI_SERVER_URL` | `http://localhost:8000` |
| `AI_SHARED_SECRET` | `local-ai-secret` |
| `AI_HTTP_TIMEOUT_SECONDS` | `660` |
| `ALLOWED_ORIGINS` | `http://localhost:5173` |

운영 환경에서는 루트의 `.env.production.example`을 참고하고 모든 비밀값을 교체합니다.

---

## 10. 자주 발생하는 문제

### Gradle이 Java 11로 실행됨

```text
Gradle requires JVM 17 or later
```

PowerShell의 `JAVA_HOME`뿐 아니라 IntelliJ의 Gradle JVM도 Java 17로 변경합니다.

### Node 버전이 낮음

Vite 7은 Node `20.19+` 또는 `22.12+`가 필요합니다.

```powershell
node --version
```

버전을 올린 뒤 `frontend/node_modules`를 다시 설치합니다.

### AI provider가 `unconfigured`로 표시됨

1. `ai-server/.env`가 존재하는지 확인합니다.
2. `JOBISS_AI_ANALYSIS_PROVIDER=claude_cli`인지 확인합니다.
3. `claude auth status`를 확인합니다.
4. AI 서버를 재시작합니다.

### Claude CLI timeout

공고 전체 분석과 그래프 생성은 오래 걸릴 수 있습니다.

- AI 단일 호출 제한: 600초
- 백엔드 AI HTTP 제한: 660초
- DB 작업 점유 시간: 15분
- 질문 판단과 최종 분석은 분리되어 실행
- 화면을 나가도 백그라운드 작업은 유지

AI 서버 PowerShell의 `JOBISS_AI_PROGRESS` 로그에서 마지막 상태와 경과 시간을 확인합니다. `running`은 기본 10초 간격이며 `JOBISS_AI_PROGRESS_LOG_INTERVAL_SECONDS`로 조정할 수 있습니다. 반복해서 실패하면 AI 서버 로그의 오류 코드와 백엔드의 `analysis_jobs.error_message`를 함께 확인합니다.

### 포트 충돌

```powershell
Get-NetTCPConnection -State Listen -LocalPort 55432,8000,8080,5173 |
    Select-Object LocalPort,OwningProcess
```

다른 팀원의 프로세스를 임의로 종료하지 말고 어떤 프로그램인지 먼저 확인합니다.

기존 `C:\jobiss-service`를 동시에 실행해야 한다면 새 저장소는 다음 대체 포트를 사용할 수 있습니다.

```powershell
# PostgreSQL
cd C:\S15P11C202
powershell -ExecutionPolicy Bypass -File .\scripts\start-local-postgres.ps1 -Port 55433

# AI 어댑터
cd C:\S15P11C202\ai-server
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8001

# 백엔드: 아래 변수는 백엔드를 실행할 터미널 또는 IntelliJ 실행 구성에 지정
$env:DB_URL='jdbc:postgresql://localhost:55433/jobiss'
$env:AI_SERVER_URL='http://localhost:8001'
$env:SERVER_PORT='8081'
$env:ALLOWED_ORIGINS='http://localhost:5174'

cd C:\S15P11C202\backend
.\gradlew.bat bootRun

# 프론트엔드
cd C:\S15P11C202\frontend
npm run dev -- --port 5174
```

이 경우 접속 주소는 `http://localhost:5174`이고 백엔드 상태 주소는
`http://localhost:8081/api/health`입니다.

### PostgreSQL 연결 실패

기존 MySQL DB나 다른 PostgreSQL DB를 사용하지 말고 프로젝트 스크립트를 다시 실행합니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-local-postgres.ps1
```

로그는 `.local/postgres.log`에 기록됩니다.

---

## 11. 기존 팀 디렉터리와의 관계

| 디렉터리 | 이 브랜치에서의 취급 |
|---|---|
| `AI/` | 기존 LangGraph 실제 에이전트. 수정하지 않음 |
| `fake-ai/` | 기존 WebSocket 가짜 서버. 수정하지 않음 |
| `DATA/` | 기존 수집 코드 유지 |
| `RAG/` | 기존 pgvector/RAG 코드 유지 |
| `ai-server/` | v2 백엔드 계약을 시험하는 로컬 어댑터 |
| `frontend/` | v2 Vue 웹앱 |
| `backend/` | v2 Spring 백엔드 |

세부 계약과 운영 규칙:

- `_docs/service-v2/architecture.md`
- `_docs/service-v2/api-contract.md`
- `_docs/service-v2/operations.md`
- `_docs/Git_협업_가이드.md`
