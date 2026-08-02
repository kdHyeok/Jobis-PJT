# JOBISS v2 — 처음 세팅 & 수동 실행 가이드

이 브랜치를 풀 받은 팀원이 **진짜 멀티에이전트(AI/ v2bridge)로 브라우저 대화까지** 돌리는 최단 경로다.
모든 명령은 **Windows PowerShell** 기준이고, 저장소 위치는 본인 경로로 바꿔 읽는다 (예: `C:\Users\SSAFY\Desktop\S15P11C202-rag`).

> 루트 `README.md`는 같은 스택을 임시 어댑터(`ai-server/`) 기준으로 설명한다.
> 진짜 에이전트로 쓰려면 README §3.2·§4의 AI 부분만 이 문서로 바꾸면 되고 나머지는 동일하다.

---

## 1. 필수 프로그램 (설치 안 된 것만, 최초 1회)

| 프로그램 | 버전 | 설치 확인 |
|---|---|---|
| Git | 최신 | `git --version` |
| Java JDK | 17 | `java --version` |
| Node.js | 20.19+ 또는 22.12+ | `node --version` |
| PostgreSQL | 17 권장 | `& 'C:\Program Files\PostgreSQL\17\bin\postgres.exe' --version` |
| **uv** | 최신 | `uv --version` — 없으면: `irm https://astral.sh/uv/install.ps1 | iex` |
| **Claude Code CLI** | 로그인 상태 | `claude --version` 후 아무 명령이나 실행해 로그인 확인 |

- Python은 따로 설치 안 해도 된다 — uv가 알아서 받는다. (README의 `ai-server` 경로를 쓸 때만 Python 3.12 필요)
- Java가 여러 버전이면 README §1 "Java가 여러 버전 설치된 경우" 참고 (`JAVA_HOME` 지정).

## 2. 최초 1회 설정

저장소 루트에서 순서대로. 전부 **한 번만** 하면 된다.

### 2-1. 프로젝트 전용 PostgreSQL 초기화 (포트 55432)

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-local-postgres.ps1
```

`JOBISS PostgreSQL is ready at localhost:55432.` 가 뜨면 끝.
DB(`jobiss`)·계정(`jobiss_migrator`, `jobiss_app`)·데이터 디렉터리(`.local/postgres-data`)를 스크립트가 전부 만든다.
기존에 깔린 MySQL이나 5432 PostgreSQL은 건드리지 않는다.

### 2-2. AI 환경 파일 — `AI\.env` 생성 (git에 없음)

`AI` 폴더에 `.env` 파일을 만들고 **한 줄**만 넣는다:

```dotenv
LLM_PROVIDER=claude_code
```

- 로그인된 Claude CLI를 쓰므로 **API 키가 필요 없다.** 메인 모델 `sonnet`, 경량 호출 `haiku`가 기본값.
- 선택(공고 URL 수집 품질용): `JINA_API_KEY=…`, `CLOVA_API_KEY=…` — 없어도 대화·분석은 된다.

### 2-3. 프론트엔드 의존성 설치

```powershell
cd frontend
npm ci
```

### 2-4. 그 외 설정할 것 — **없음**

백엔드 `.env` 불필요: DB 접속정보·JWT·AI 주소·공유 시크릿(`local-ai-secret`) 전부
`application.yml` 로컬 기본값이 위 구성과 맞물려 있다. (전체 목록은 README §9)

---

## 3. 서버 켜기 (매번, 터미널 4개)

**순서 중요: PostgreSQL → AI → 백엔드 → 프론트.** 각 터미널은 저장소 루트에서 시작한다고 가정.

### 터미널 1 — PostgreSQL (55432)

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-local-postgres.ps1
```

이미 떠 있으면 그대로 "ready" 만 출력하고 끝난다. (이 터미널은 닫아도 된다 — 백그라운드 서비스로 돈다)

### 터미널 2 — AI 에이전트 v2bridge (8000)

```powershell
cd AI
$env:PYTHONUTF8 = "1"
uv run --with fastapi,uvicorn uvicorn jobis_ai.v2bridge.app:app --host 127.0.0.1 --port 8000
```

- 첫 실행은 의존성 받느라 1~2분 걸린다. `Uvicorn running on http://127.0.0.1:8000` 이 뜨면 준비 완료.
- 확인: 브라우저에서 `http://localhost:8000/health` → `"service":"jobis-ai-v2bridge"` 가 보여야 한다.
  `webbridge`나 fake-ai를 8000에 띄우면 안 된다 — v2 백엔드는 v2bridge 계약(`/v1/chat`)만 안다.

### 터미널 3 — 백엔드 (8080)

```powershell
cd backend
$env:JAVA_HOME = 'C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot'   # 본인 JDK17 경로
.\gradlew.bat bootRun
```

- `Started JobissBackendApplication` 이 뜨면 준비 완료 (10초~1분).
- PostgreSQL이 먼저 떠 있어야 한다. 안 떠 있으면 connection refused로 죽는다.

### 터미널 4 — 프론트엔드 (5173)

```powershell
cd frontend
npm run dev
```

`Local: http://localhost:5173` 이 뜨면 준비 완료.

### 접속

브라우저에서 **http://localhost:5173** → 회원가입 → 로그인 → 대화 시작.
(8080이 아니라 5173으로 접속한다 — Vite가 `/api`를 백엔드로 프록시한다.)

---

## 4. 서버 끄기

- 터미널 2·3·4: 각 창에서 `Ctrl+C`
- PostgreSQL:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop-local-postgres.ps1
```

---

## 5. 뭔가 안 될 때

| 증상 | 원인/해결 |
|---|---|
| 로그인 시 "보안 토큰을 준비하지 못했습니다" | 8080에 v2 백엔드가 아닌 다른(구버전) 백엔드가 떠 있음 — 끄고 이 브랜치 `backend`에서 다시 |
| 대화가 계속 "처리 중" | 8000에 v2bridge가 아닌 것이 떠 있거나 Claude CLI 미로그인 — `/health` 응답의 `service` 확인 |
| 백엔드가 DB 연결 실패로 죽음 | 터미널 1(PostgreSQL) 먼저 실행 |
| Gradle이 Java 11로 돎 | `$env:JAVA_HOME` 지정 후 재실행 (README §10) |
| 포트 충돌 | `Get-NetTCPConnection -State Listen -LocalPort 8000,8080,5173,55432` 로 점유 프로세스 확인 후 종료 |

그 외는 README §10 "자주 발생하는 문제" 참고.
