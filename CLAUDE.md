# JOBIS 프로젝트 — 로컬 서버 실행 지침

프론트엔드는 별도 서버가 없고 백엔드(Spring Boot)가 `backend/src/main/resources/static/`의 HTML/JS를 함께 서빙한다.
**기동 순서: MySQL → AI 서버(웹 브릿지) → backend** (백엔드가 앞의 둘에 의존).

## 환경 주의사항 (WSL)

Claude Code는 WSL에서 돌지만 **WSL 안에는 node/java/mysql이 없다.** 전부 Windows 실행파일을 사용할 것.

- Node: `/mnt/c/Program Files/nodejs/node.exe`
- JDK 17: `C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot` (gradlew 실행 시 `JAVA_HOME` 지정 필요)
- MySQL 8.4: `C:\Program Files\MySQL\MySQL Server 8.4` (Windows 서비스 미등록 — 아래 스크립트로 수동 기동)
- **WSL에서 `curl localhost:8080`은 Windows 프로세스에 닿지 않는다.** 확인은 `powershell.exe`로 할 것.

## 1. MySQL (포트 3306)

```bash
# 백그라운드로 실행 (run_in_background)
cmd.exe /c "C:\Users\SSAFY\jobiss-mysql-start.bat"
```

- 데이터 디렉토리: `C:\Users\SSAFY\jobiss-mysql-data` (root 비밀번호 `ssafy`, DB `jobiss` 이미 생성됨)
- 로그에 `ready for connections` 뜨면 준비 완료
- 최초 초기화가 필요하면: `C:\Users\SSAFY\jobiss-mysql-init.bat` → start → `C:\Users\SSAFY\jobiss-mysql-setup.bat`

## 2. AI 서버 (포트 8000, WebSocket + HTTP) — 웹 브릿지 또는 fake-ai 중 하나만

포트 8000에는 둘 중 **하나만** 띄운다. 대화 페이지(`/chat` `/chat/stream`)를 쓰려면 **웹 브릿지가 필수**다
— fake-ai에는 `/chat`이 없어서 채팅하면 `대화 처리 실패(404)`가 난다.

### 2-a. 웹 브릿지 (진짜 AI, 권장)

소스는 `feat/ai/web-bridge` 브랜치에만 있어서 **worktree**로 꺼내둠: `/mnt/c/Users/SSAFY/Desktop/S15P11C202-ai`
(`git worktree add /mnt/c/Users/SSAFY/Desktop/S15P11C202-ai feat/ai/web-bridge`로 생성.
`.env`(GMS_KEY)와 `sessions.sqlite3`는 원본 `AI/`에서 복사해둠.)

```bash
# 백그라운드로 실행 (uv가 의존성 자동 설치)
cmd.exe /c "cd /d C:\Users\SSAFY\Desktop\S15P11C202-ai\AI&& set PYTHONUTF8=1&& C:\Users\SSAFY\.local\bin\uv.exe run --with fastapi,uvicorn,websockets uvicorn jobis_ai.webbridge.app:app --host 127.0.0.1 --port 8000"
```

- 로그에 `Uvicorn running on http://127.0.0.1:8000` 뜨면 준비 완료
- 확인: `powershell.exe -NoProfile -Command "(Invoke-WebRequest -UseBasicParsing http://localhost:8000/health).Content"` → `{"status":"ok","engine":"jobis-ai"}`
- 주의: 원본 `AI/.venv-win`은 langsmith 패키지가 깨져 있어 직접 uvicorn.exe 실행은 실패한다 — 반드시 uv로 실행할 것

### 2-b. fake-ai (분석 WS + /extract 만 필요할 때)

```bash
# 백그라운드로 실행
cd /mnt/c/Users/SSAFY/Desktop/S15P11C202/fake-ai && "/mnt/c/Program Files/nodejs/node.exe" server.js
```

- 로그에 `가짜 AI 서버 대기 중 … ws://localhost:8000` 뜨면 준비 완료

## 3. 백엔드 (포트 8080)

```bash
# 백그라운드로 실행
cd /mnt/c/Users/SSAFY/Desktop/S15P11C202/backend && cmd.exe /c "set JAVA_HOME=C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot&& gradlew.bat bootRun"
```

- 로그에 `Started BackendApplication` 뜨면 준비 완료 (약 30초~1분)
- MySQL이 안 떠 있으면 `Communications link failure`로 실패한다

## 4. 확인

```bash
powershell.exe -NoProfile -Command "(Invoke-WebRequest -UseBasicParsing http://localhost:8080/login.html).StatusCode"
# → 200 이면 정상
```

접속: `http://localhost:8080/login.html`
