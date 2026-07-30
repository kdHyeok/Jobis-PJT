# JOBIS (잡이스)

특정 IT 채용공고와 사용자의 실제 경험 증거를 비교해 현실적인 준비·지원 경로를 제시하고, 선택한 경로를 로드맵과 캘린더로 만들어 주는 **취업 준비 AI 에이전트** 서비스입니다.

- 서비스 정의와 기능 명세: [_docs/v1-0-0_잡이스_통합_프로젝트_정의서_기능명세서.md](_docs/v1-0-0_잡이스_통합_프로젝트_정의서_기능명세서.md)
- Git 브랜치 전략·MR 규칙: [_docs/Git_협업_가이드.md](_docs/Git_협업_가이드.md)
- Jira 작성 규칙: [_docs/Jira_작성_컨벤션.md](_docs/Jira_작성_컨벤션.md)

---

## 디렉토리 구조

```text
S15P11C202/
├── backend/    # Spring Boot 백엔드 (웹 서비스 본체, 정적 프론트 포함)
│   └── src/main/resources/static/   # 프론트엔드 화면 (HTML/JS)
├── AI/         # AI 에이전트 서버 (멀티에이전트 오케스트레이터 + 웹 브릿지, 안내: AI/README.md)
├── fake-ai/    # 개발용 가짜 AI 서버 (Node.js, WebSocket) — 대화 기능은 없다
├── DATA/       # 채용공고 데이터 수집 (재통합 예정, 안내: DATA/README.md)
├── RAG/        # RAG 기능 개발 격리 디렉토리 (안내: RAG/README.md)
├── _docs/      # 기능 정의서, 협업 가이드 등 산출물 문서
├── _plan/      # 프로젝트 계획 관련 문서
└── _ref/       # 참고 자료 (이미지·영상)
```

> `DATA/`는 구조 정리를 위해 비워둔 상태입니다. 기존 작업물은 아카이브 태그(`archive/data` 등)와 develop 커밋 이력에 보존되어 있습니다. 복원: `git switch -c <브랜치명> archive/<태그명>`

## 브랜치 운영

```text
master   # 배포·시연 가능한 안정 버전 (직접 push 금지)
└── develop   # 통합 개발 브랜치 (모든 작업의 기준)
    ├── feat/<영역>/<기능명>   # 영역: ai / rag / data / be / fe / infra
    ├── fix/<영역>/<수정명>
    └── refactor/<영역>/<작업명>
```

모든 작업은 최신 `develop`에서 분기해 MR로 병합합니다. 자세한 규칙은 [_docs/Git_협업_가이드.md](_docs/Git_협업_가이드.md)를 따릅니다.

---

## 실행 방법

이 브랜치 하나로 프론트·백엔드·AI 가 전부 뜬다. 프론트는 별도 서버가 없고 백엔드가 함께 서빙한다.
**기동 순서는 MySQL → AI(:8000) → 백엔드(:8080)** — 백엔드가 앞의 둘에 의존한다.

준비물: **Java 17**, **MySQL 8**, **Python 3.11+** (+ [uv](https://docs.astral.sh/uv/) 권장)

### 1. DB 만들고 백엔드 설정 채우기

```sql
CREATE DATABASE jobiss CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

DB 접속 정보와 JWT 시크릿은 코드에 기본값이 없다. `backend/.env` 를 만들어 채운다.

```bash
cd backend && cp .env.example .env    # Windows: Copy-Item .env.example .env
```

```properties
DB_URL=jdbc:mysql://localhost:3306/jobiss?serverTimezone=UTC&characterEncoding=UTF-8
DB_USERNAME=root
DB_PASSWORD=본인_비밀번호
JWT_SECRET=32자_이상의_임의_문자열      # openssl rand -base64 48
```

### 2. AI 서버 (:8000) — 백엔드보다 먼저

```bash
cd AI && cp .env.example .env
```

`.env` 에서 LLM 을 **둘 중 하나** 고른다. 기능 차이는 없고 속도·비용만 다르다.

```properties
# (A) Claude Code CLI — 무과금. 그 머신에 claude CLI 가 로그인돼 있어야 한다.
#     느리다(호출마다 CLI 기동). 토큰 스트리밍은 안 되고 완성본이 한 번에 온다.
LLM_PROVIDER=claude_code
EMBED_PROVIDER=null

# (B) SSAFY GMS — 빠르고(턴당 4~10초) 토큰 스트리밍도 된다. GMS 토큰이 과금된다.
LLM_PROVIDER=openai
GMS_KEY=본인_GMS_키
```

띄운다.

```bash
uv run --extra prototype uvicorn jobis_ai.webbridge.app:app --host 127.0.0.1 --port 8000
```

> uv 없이: `python -m venv .venv && source .venv/bin/activate`(Windows: `.venv\Scripts\activate`) →
> `pip install -e ".[prototype]"` → 같은 `uvicorn` 명령.
> `Uvicorn running on http://127.0.0.1:8000` 이 뜨면 준비 완료.
> 확인: `curl http://localhost:8000/health` → `{"status":"ok","engine":"jobis-ai"}`

### 3. 백엔드 (:8080)

`.env` 를 읽으려면 **`local` 프로필**로 띄워야 한다.

```bash
cd backend
gradlew.bat bootRun --args="--spring.profiles.active=local"
# macOS/Linux: ./gradlew bootRun --args='--spring.profiles.active=local'
```

`Started BackendApplication` 이 뜨면 준비 완료.

### 4. 에이전트와 대화하기

`http://localhost:8080/login.html` → 회원가입 → 로그인 → 좌측 **`JOBIS에게 물어보기`**

이력서가 없어도 그냥 말하면 된다. 무엇을 할지는 에이전트가 정한다.

```
저는 신입이에요. 자바 스프링 백엔드 공고 추천해줘. 서울이고 커머스 도메인 관심 있어요.
```

→ 선호를 파악하고 실공고를 URL 과 함께 추천한다(연차가 안 맞는 공고는 제외하고 몇 건 빠졌는지 알려준다).
추천된 URL 을 그대로 붙여넣으면 그 공고 분석으로 이어지고, 이력서까지 주면 적합도까지 판정한다.

### 막히면

| 증상 | 해결 |
|---|---|
| 기동 중 `Could not resolve placeholder 'JWT_SECRET'` | `backend/.env` 가 없거나 `local` 프로필로 안 띄웠다 |
| 기동 중 `Communications link failure` | MySQL 이 꺼져 있거나 `jobiss` DB 가 없다 |
| 기동 중 `Flyway ... checksum mismatch` | 다른 브랜치가 만든 DB 다. `DROP DATABASE jobiss` 후 다시 만든다 |
| 대화에서 `대화 처리 실패(404)` | :8000 에 `fake-ai` 가 떠 있다(`/chat` 이 없다). AI 서버로 교체 |
| `AI 서버에 연결하지 못했어요` | :8000 이 꺼져 있다. AI 서버를 막 재시작했다면 한 번 더 보내본다 |
| 공고 추천이 안 나온다 | `AI/sample_data/db내 공고파일/` 에 공고 JSON 이 있는지 확인 |

AI 서버 상세(제공 API·프로바이더 전환·공고 데이터 위치)는 [AI/README.md](AI/README.md),
백엔드 설정 상세는 [backend/README.md](backend/README.md) 를 본다.
공고 분석(WS)만 볼 거면 `:8000` 에 `fake-ai`(`cd fake-ai && npm install && node server.js`)를 대신 띄워도 된다 — 대화 기능은 빠진다.
