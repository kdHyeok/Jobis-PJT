# RUN — 로컬 실행 가이드 (PostgreSQL 버전)

이 브랜치(`feat/be/postgres-staged-roadmap`)를 로컬에서 직접 돌려보는 안내입니다.
프론트(HTML/JS)는 `backend/src/main/resources/static/` 에 번들되어 백엔드가 함께 서빙합니다.

> 참고: `backend/README.md` 는 이전 MySQL 기준 안내입니다. **이 브랜치는 PostgreSQL 기준**이라 아래를 따르세요.

## 준비물
- **Java 17**
- **PostgreSQL** (14+ 권장)
- **Node.js** (가짜 AI 서버용)
- AI provider 중 하나:
  - 로그인된 **`claude` CLI**, 또는
  - **`uv`로 설치·실행한 Codex OAuth adapter** (`codex-openai-server`, 기본 8001)

## 1. DB 만들기
PostgreSQL 에 접속해서 롤·DB만 만든다. (테이블은 실행 시 Hibernate `ddl-auto: update` 가 자동 생성)
```sql
CREATE ROLE jobiss LOGIN PASSWORD 'ssafy';
CREATE DATABASE jobiss OWNER jobiss;
```

## 2. 로컬 환경 파일 준비 (.env)
DB 접속정보·JWT 시크릿은 코드에 없으므로 `.env` 로 주입한다. `backend` 폴더에서:
```bash
cp .env.example .env     # Windows PowerShell: Copy-Item .env.example .env
```
그다음 `.env` 값을 채운다:
```dotenv
DB_URL=jdbc:postgresql://localhost:5432/jobiss
DB_USERNAME=jobiss
DB_PASSWORD=ssafy
JWT_SECRET=32자_이상의_임의_문자열
```
> **JWT_SECRET 은 반드시 32자(256비트) 이상.** 짧으면 서버가 시작되지 않는다.
> 생성 — PowerShell: `[Convert]::ToBase64String((1..48 | ForEach-Object { Get-Random -Maximum 256 }))`
> / macOS·Linux: `openssl rand -base64 48`
> `.env` 는 Git에 올리지 않는다(`.gitignore` 처리됨).

## 3. 가짜 AI 서버 실행 (별도 터미널)

> **진짜 멀티에이전트로 대화하려면** 이 절 대신 [AI/docs/에이전트-로컬-세팅.md](AI/docs/에이전트-로컬-세팅.md) 를 따른다
> — fake-ai 자리를 진짜 에이전트가 대신하고, 공고 URL 수집·적합도 분석·자소서까지 실제 동작을 볼 수 있다.

Claude(기본값):
```powershell
cd fake-ai
$env:LLM_PROVIDER = "claude"
npm install
node server.js
```

GPT/Codex는 `fake-ai` 안에 포함된 adapter를 사용한다. 최초 한 번 같은 디렉터리에서
uv 환경 구성과 OAuth 로그인을 수행한다.

```powershell
cd fake-ai
uv python install 3.11
uv sync --python 3.11 --managed-python --extra server
uv run --managed-python --extra server codex-oauth --login
npm install

$env:LLM_PROVIDER = "codex"
$env:CODEX_BASE_URL = "http://127.0.0.1:8001"
$env:CODEX_MODEL = "gpt-5.4"
$env:CODEX_REASONING_EFFORT = "medium"
$env:CODEX_TIMEOUT_MS = "200000"
node server.js
```

별도 sidecar 명령은 필요 없다. `node server.js`가 로컬 Codex sidecar를 자동 기동한다.
상세 설정은 [fake-ai/README.md](fake-ai/README.md)를 참고한다.

## 4. 백엔드 실행 — **local 프로필 필수** (.env 를 읽어야 함)
```bash
cd backend
.\gradlew.bat bootRun --args="--spring.profiles.active=local"
# macOS/Linux: ./gradlew bootRun --args='--spring.profiles.active=local'
```
IntelliJ 로 실행 시: Run 설정의 **Active profiles 에 `local`** 을 넣는다.

## 5. 접속
```
http://localhost:8080/login.html
```
회원가입 → 로그인 → 커리어 저장소에 이력서 등록 → 공고 원문 붙여넣고 분석 → 보강 경로에서 "로드맵 생성" → "단계별로 진행하기" 로 단계형 로드맵 확인.

## 실행 순서 요약
1. PostgreSQL 켜기 → 롤·DB 생성
2. `backend/.env` 채우기
3. 가짜 AI: `cd fake-ai && node server.js`
4. 백엔드: `cd backend && gradlew.bat bootRun --args="--spring.profiles.active=local"`
5. 브라우저: `http://localhost:8080/login.html`

## 메모
- DB 스키마는 Hibernate 가 엔티티에서 생성한다(`ddl-auto: update`, Flyway off). Postgres 용 Flyway·RLS 는 추후 정리.
- `fake-ai`의 외부 HTTP/WebSocket 계약은 유지하며 내부 LLM만 `claude` 또는 `codex`로 선택한다.
