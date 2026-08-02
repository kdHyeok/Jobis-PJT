# JOBIS 프로젝트 — 로컬 서버 실행 지침 (서비스 v2)

이 브랜치는 **서비스 v2 풀스택**이다: Vue 프론트(5173) + Spring 백엔드(8080) + AI v2bridge(8000) + PostgreSQL(55432) + RAG 검색 서버(8765, 선택).
**기동 순서: PostgreSQL → (RAG 서버) → AI(v2bridge) → backend → frontend.** 팀원용 상세 가이드는 루트 `README.md` 참고.

> 구버전(MySQL + 정적 HTML + webbridge) 지침은 이 브랜치에서 폐기됐다. MySQL은 더 이상 쓰지 않는다.

## 환경 주의사항 (WSL)

Claude Code는 WSL에서 돌지만 **WSL 안에는 node/java/postgres가 없다.** 전부 Windows 실행파일을 사용할 것.

- Node: `/mnt/c/Program Files/nodejs/node.exe`
- JDK 17: `C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot` (gradlew 실행 시 `JAVA_HOME` 지정 필요)
- PostgreSQL 17: `C:\Program Files\PostgreSQL\17`
- uv: `C:\Users\SSAFY\.local\bin\uv.exe`
- **WSL에서 `curl localhost:8080`은 Windows 프로세스에 닿지 않는다.** 확인은 `powershell.exe`로 할 것.

## 1. PostgreSQL (포트 55432)

```bash
# 최초 1회 또는 안 떠 있을 때 (초기화·롤 생성까지 자동, idempotent)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\SSAFY\Desktop\S15P11C202-rag\scripts\start-local-postgres.ps1"
```

- 데이터 디렉토리: 저장소 루트 `.local/postgres-data` (git 무시됨), 로그: `.local/postgres.log`
- DB `jobiss`, 계정 `jobiss_migrator`/`jobiss_migrator_dev`, `jobiss_app`/`jobiss_app_dev` — 백엔드 기본값과 일치해서 `.env` 불필요
- 로그에 `database system is ready to accept connections` 뜨면 준비 완료

## 2. AI 서버 — v2bridge (포트 8000)

**이 체크아웃의 `AI/`에서 띄운다.** v2 백엔드는 v2 계약(`/v1/chat` 등)을 쓰므로 webbridge/fake-ai가 아니라 **v2bridge**여야 한다.

사전 준비: `AI/.env`(git 무시됨)에 최소 한 줄 — `LLM_PROVIDER=claude_code` (로그인된 Claude CLI 사용, 키 불필요).

```bash
# 백그라운드로 실행 (uv가 의존성 자동 설치)
cmd.exe /c "cd /d C:\Users\SSAFY\Desktop\S15P11C202-rag\AI&& set PYTHONUTF8=1&& C:\Users\SSAFY\.local\bin\uv.exe run --with fastapi,uvicorn uvicorn jobis_ai.v2bridge.app:app --host 127.0.0.1 --port 8000"
```

- 확인: `powershell.exe -NoProfile -Command "(Invoke-WebRequest -UseBasicParsing http://localhost:8000/health).Content"`
  → `{"status":"ok","service":"jobis-ai-v2bridge","engine":"jobis-ai","provider":"claude_code"}`
- 공유 시크릿은 양쪽 기본값(`local-ai-secret`)이 일치하므로 설정 불필요

## 2.5 RAG 검색 서버 (포트 8765, 선택 — D89)

공고 추천·대안 공고를 **의미 검색**(하이브리드+리랭킹)으로 바꿔 주는 독립 서비스.
**미기동이어도 AI 는 정상 동작한다** — 경고와 함께 키워드 검색(LocalPostings)으로 폴백.

- 데이터: **WSL 안의 PostgreSQL 16**(포트 5432, `jobrag` DB, pgvector) — 55432(서비스 DB)와 별개.
  비어 있으면 `pg_restore -h 127.0.0.1 -p 5432 -U jobrag -d jobrag --no-owner --clean --if-exists RAG\rag_tool_handoff\rag_server\db_dump\jobrag.dump` (계정 jobrag/jobrag_local_dev)
- 최초 1회: `RAG\rag_tool_handoff\rag_server` 에서 `uv venv .venv` 후 requirements 의 패키지 직접 설치
  (uv 가 따옴표 줄을 못 읽음), `.env` 에 `PG_DSN=postgresql://jobrag:jobrag_local_dev@127.0.0.1:5432/jobrag`

### ⚠ WSL 이 내려가지 않게 먼저 붙잡는다 (2026-08-01 — 이거 없으면 기동이 실패한다)

WSL VM 은 **유휴 60초면 자동 종료된다.** RAG 서버는 기동 시 모델 로딩에 수십 초~수 분을 쓰고
그 사이 DB 를 안 건드리므로, WSL 이 내려가 커넥션이 끊기고 startup 이 죽는다
(`AdminShutdown` / `ConnectionTimeout` / `10053 connection abort` — 셋 다 같은 원인).

```bash
# ① 한 번만: %USERPROFILE%\.wslconfig 에 (-1 은 안 먹는다 — 밀리초 정수로)
#    [wsl2]
#    vmIdleTimeout=2000000000
# ② 매 세션: WSL 에 붙은 프로세스를 하나 띄워 둔다 (앵커)
wsl.exe -u root -e sleep 100000 &
# ③ postgres 확인 (systemd 가 자동 기동한다)
wsl.exe -u root -e pg_isready -h 127.0.0.1 -p 5432
```

진단 과정·오진 3회는 `AI/docs/troubleshooting.md` (2026-08-01 항목).

```bash
# 백그라운드로 실행 (최초 기동은 모델 다운로드 ~6.5GB + warmup ~15분, 이후 warmup 수십 초)
cmd.exe /c "cd /d C:\Users\SSAFY\Desktop\S15P11C202-rag\RAG\rag_tool_handoff\rag_server&& set PYTHONUTF8=1&& .venv\Scripts\python.exe -m uvicorn webapp.tool_server:app --host 127.0.0.1 --port 8765"
```

- 확인: `curl http://127.0.0.1:8765/health` → `{"status":"ok","warm":true}`
- AI 연결: `AI/.env` 의 `RAG_PROVIDER=http` + `RAG_SEARCH_URL=http://127.0.0.1:8765` (이미 설정됨)

## 3. 백엔드 (포트 8080)

```bash
# 백그라운드로 실행 — 프로필 지정 없음 (application.yml 기본값이 로컬 Postgres/AI를 가리킴)
cd /mnt/c/Users/SSAFY/Desktop/S15P11C202-rag/backend && cmd.exe /c "set JAVA_HOME=C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot&& gradlew.bat bootRun"
```

- 로그에 `Started JobissBackendApplication` 뜨면 준비 완료
- Flyway가 55432의 `jobiss` DB에 자동 마이그레이션한다 — PostgreSQL이 먼저 떠 있어야 한다

## 4. 프론트엔드 (포트 5173, Vite dev)

```bash
# 최초 1회: cd /mnt/c/Users/SSAFY/Desktop/S15P11C202-rag/frontend && cmd.exe /c "\"C:\Program Files\nodejs\npm.cmd\" install"  ← cmd 따옴표 문제 시 node.exe로 npm-cli.js 직접 실행
# 백그라운드로 실행
cd /mnt/c/Users/SSAFY/Desktop/S15P11C202-rag/frontend && "/mnt/c/Program Files/nodejs/node.exe" node_modules/vite/bin/vite.js
```

- `Local: http://localhost:5173` 뜨면 준비 완료 (출력에 ANSI 컬러 코드가 섞여 있어 grep 시 주의)
- Vite가 `/api`를 8080으로 프록시한다 — 브라우저는 **5173으로만** 접속

## 5. 확인

```bash
powershell.exe -NoProfile -Command "(Invoke-WebRequest -UseBasicParsing http://localhost:5173/api/auth/csrf).Content"
# → {"token":"...","headerName":"X-XSRF-TOKEN"} 이면 프록시·백엔드·csrf 전부 정상
```

접속: `http://localhost:5173` (회원가입 → 로그인 → 에이전트 대화)
