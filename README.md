# JOBIS (잡이스)

특정 IT 채용공고와 사용자의 실제 경험 증거를 비교해 현실적인 준비·지원 경로를 제시하고, 선택한 경로를 로드맵과 캘린더로 만들어 주는 **취업 준비 AI 에이전트** 서비스입니다.

- 서비스 정의와 기능 명세: [docs/잡이스_통합_프로젝트_정의서_기능명세서.md](docs/잡이스_통합_프로젝트_정의서_기능명세서.md)

---

## 디렉토리 구조

```text
S15P11C202/
├── backend/    # Spring Boot 백엔드 (웹 서비스 본체, 정적 프론트 포함)
│   └── src/main/resources/static/   # 프론트엔드 화면 (HTML/JS)
├── fake-ai/    # 개발용 가짜 AI 서버 (Node.js, WebSocket)
├── AI/         # AI 에이전트 개발 (Python, LangGraph 기반 분석 파이프라인)
│   ├── src/jobis_ai/   # AI 패키지 소스
│   ├── tests/          # 테스트
│   ├── evals/          # 평가 데이터셋
│   └── docs/           # AI 설계·계약(contract) 문서
├── DATA/       # 채용공고 데이터 수집 (크롤러 + 수집 데이터)
│   ├── crawl_*.py      # 사이트별 크롤러 (인크루트/잡코리아/사람인/원티드/워크24)
│   ├── data/           # 수집된 SQLite DB
│   └── exports/        # JSON 내보내기 결과
├── RAG/        # RAG 기능 개발 격리 디렉토리 (안내: RAG/README.md)
├── docs/       # 기능 정의서 등 산출물 문서
├── plan/       # 프로젝트 계획 관련 문서
└── front_ref/  # 프론트 참고 자료 (이미지·영상)
```

> `김동혁/`, `김주형/` 폴더는 초기 개인 연구 자료입니다. 추후 `AI/`·`DATA/`·`docs/`로 정리 예정이며, `김동혁/AI`는 깨진 서브모듈 링크라 빈 폴더로 클론됩니다.

## 브랜치 운영

```text
master   # 배포·시연 가능한 안정 버전 (직접 push 금지)
└── develop   # 통합 개발 브랜치 (모든 작업의 기준)
    ├── feat/<영역>/<기능명>   # 영역: ai / be / fe / infra
    ├── fix/<영역>/<수정명>
    └── refactor/<영역>/<작업명>
```

모든 작업은 최신 `develop`에서 분기해 MR로 병합합니다. 자세한 규칙은 팀 Git 브랜치 전략 문서를 따릅니다.

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
