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
├── fake-ai/    # 개발용 가짜 AI 서버 (Node.js, WebSocket)
├── AI/         # AI 에이전트 개발 (재통합 예정, 안내: AI/README.md)
├── DATA/       # 채용공고 데이터 수집 (재통합 예정, 안내: DATA/README.md)
├── RAG/        # RAG 기능 개발 격리 디렉토리 (안내: RAG/README.md)
├── _docs/      # 기능 정의서, 협업 가이드 등 산출물 문서
├── _plan/      # 프로젝트 계획 관련 문서
└── _ref/       # 참고 자료 (이미지·영상)
```

> `AI/`, `DATA/`는 구조 정리를 위해 비워둔 상태입니다. 기존 작업물은 아카이브 태그(`archive/ai_agent_jy`, `archive/data` 등)와 develop 커밋 이력에 보존되어 있습니다. 복원: `git switch -c <브랜치명> archive/<태그명>`

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

### 준비물

- Java 17
- Node.js 18+
- MySQL 8

### 1. DB 생성

MySQL에 접속해서 데이터베이스만 만든다. (테이블은 백엔드 실행 시 Flyway가 자동 생성)

```sql
CREATE DATABASE jobiss CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

기본 접속 정보 (`backend/src/main/resources/application.yml`)

| 항목 | 값 |
|---|---|
| url | `localhost:3306/jobiss` |
| username | `root` |
| password | `ssafy` |

다르면 환경변수로 덮어쓴다.

```bash
# 예시
set DB_USERNAME=root
set DB_PASSWORD=본인비밀번호
```

### 2. 가짜 AI 서버 실행 (먼저)

```bash
cd fake-ai
npm install
node server.js
```

→ `ws://localhost:8000` 대기. **이게 떠 있어야 분석이 동작한다.**

### 3. 백엔드 실행

```bash
cd backend
gradlew.bat bootRun     # macOS/Linux: ./gradlew bootRun
```

→ `http://localhost:8080`

### 4. 접속

```
http://localhost:8080/login.html
```

회원가입 → 로그인 → `커리어 저장소`에 이력서 텍스트 붙여넣고 등록 → `새 분석`에서 공고 URL/원문 입력 → 분석 진행.

### 실행 순서 요약

1. MySQL 실행
2. `fake-ai` → `node server.js`
3. `backend` → `gradlew.bat bootRun`
4. 브라우저 → `http://localhost:8080/login.html`
