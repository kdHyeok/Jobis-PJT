# JOBISS

JOBISS는 AI와 자유롭게 대화하고 채용 공고를 분석해, 사용자의 역량·프로젝트·자격·경력을 하나의 누적 커리어 그래프로 연결하는 웹 앱입니다.

## 현재 구현된 사용자 흐름

1. 회원가입 시 자기 확인형 공통 기반 노드 3개가 생성됩니다.
2. 공고 없이도 커리어 상황과 목표를 자유롭게 대화할 수 있습니다.
3. 사용자 메시지는 즉시 저장·표시되고 AI 답변은 백그라운드 작업으로 도착합니다.
4. 이력서와 프로젝트 설명을 등록하면 AI가 기술·프로젝트·경력·성과 조각을 제안하고, 사용자가 검토한 항목만 확정합니다.
5. 대화 또는 전용 화면에 공고 원문을 등록하면 분석은 백그라운드에서 실행됩니다.
6. 주 직무처럼 분석 결과를 바꾸는 모호함이 있으면 AI가 한 번에 한 가지 선택형 질문을 하며, 답변 후 같은 작업을 이어갑니다.
7. 완료 또는 추가 확인 알림을 통해 언제든 공고 분석으로 돌아옵니다.
8. 백엔드가 검증된 역량과 경력 조건으로 계산한 `지금 지원 / 보강 후 지원 / 대체 공고 우선` 판단과 근거를 확인합니다.
9. 새 노드, 재사용 노드, 연결, 필수·우대 조건을 검토한 뒤 승인하거나 거절합니다.
10. 승인한 변경은 회사별 지도가 아니라 직무별 하나의 통합 커리어 경로에
    병합됩니다. 같은 기술은 공유되고, 신입 기회와 경력직 기회 사이에는 관련 직무
    취업과 요구 경력 관문이 놓입니다.
11. 기반 단계는 자기 확인하고, 전문 기술은 목표 공고 맥락의 개념·코드·상황 문제를 3~5회 풀어 검증합니다.
12. 기술 완료 기록은 다른 공고에서도 재사용하고, 회사 맞춤 프로젝트에서만 Git 저장소·실행 결과·배포 URL을 종합 검증합니다.
13. 대체 공고는 AI가 지어내지 않고 서비스의 실제 정규화 공고 카탈로그에서만 추천합니다.

커리어 저장소에서는 원본 자료 처리 상태와 조각 검색·정렬·수정·병합·보관·복원·삭제·재시도를 지원합니다. 채용 공고 화면에서는 공고 검색·정렬·수정·보관·복원·삭제·분석 재시도를 지원합니다. 화면에 고정된 사용자 스펙이나 성공 결과를 만드는 목업 데이터는 없습니다.

## 서비스 구성

- `frontend`: Vue 3, TypeScript, Vite
- `backend`: Java 17, Spring Boot, Spring Security, Flyway
- `AI`: Python 3.11, FastAPI v2bridge, 멀티에이전트, GMS/Anthropic/Claude Code/Codex
- `PostgreSQL 17`: 사용자별 Row-Level Security(RLS)

원본 `C:\jobiss-backend`와 UI 실험 폴더 `C:\ui_proto`는 수정하지 않습니다.

## 로컬 개발 실행

### 1. PostgreSQL

기존 5432 데이터베이스와 분리된 프로젝트 전용 55432 클러스터를 사용합니다.

```powershell
powershell -ExecutionPolicy Bypass -File C:\jobiss-service\scripts\start-local-postgres.ps1
```

### 2. AI/v2bridge

`AI\.env.example`을 복사하고 사용할 LLM provider만 설정합니다. Codex를 쓰면 최초 한 번
`uv run jobis-codex-oauth --login`으로 인증합니다. 인증 파일 내용은 출력하거나 커밋하지 않습니다.

```powershell
cd C:\jobiss-service\AI
Copy-Item .env.example .env
uv run --frozen --extra prototype python -m uvicorn `
  jobis_ai.v2bridge.app:app --host 127.0.0.1 --port 8000
```

`http://127.0.0.1:8000/health`의 `service`가 `jobis-ai-v2bridge`인지 확인합니다.
모델이 연결되지 않으면 가짜 분석을 생성하지 않고 명시적인 실패를 반환합니다.

Windows에서 `--reload`는 별도 감시 프로세스를 만들기 때문에 Claude CLI 하위
프로세스 실행과 충돌할 수 있습니다. AI 서버를 실제로 시험할 때는 위 명령처럼
`--reload` 없이 실행하고, 코드 변경 후 직접 재시작합니다.

### 3. 백엔드

IntelliJ의 Project SDK와 Gradle JVM을 모두 Java 17 이상으로 지정합니다.

```powershell
cd C:\jobiss-service\backend
$env:JAVA_HOME="C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot"
$env:Path="$env:JAVA_HOME\bin;$env:Path"
.\gradlew.bat bootRun
```

기본 연결은 PostgreSQL `localhost:55432`, AI 서버 `localhost:8000`, API `localhost:8080`입니다.
동시에 실행할 공고 분석 수는 `AI_MAX_CONCURRENT_ANALYSES`로 지정하며 기본값은
2, 허용 범위는 1~8입니다.

### 4. 프론트엔드

```powershell
cd C:\jobiss-service\frontend
npm install
npm run dev
```

`http://localhost:5173`에서 열며 Vite가 `/api`를 `localhost:8080`으로 프록시합니다.

## 전체 검증

```powershell
powershell -ExecutionPolicy Bypass -File C:\jobiss-service\scripts\check.ps1
```

이 명령은 Java 버전을 확인한 뒤 백엔드 테스트, AI v2bridge 회귀/구조 검사,
프론트엔드 타입 검사와 프로덕션 번들을 실행합니다.

## 컨테이너 실행

로컬 Docker 실행은 선택한 LLM provider의 인증이 필요합니다.

```powershell
cd C:\jobiss-service
Copy-Item .env.compose-local.example .env
# .env의 비밀번호와 LLM provider 설정을 수정
docker compose up --build -d
```

접속 주소는 `http://localhost:8088`입니다. 데이터베이스·백엔드·AI 서버는 내부 네트워크에만 있고 프론트 프록시만 외부에 노출됩니다.

실서비스는 `.env.production.example`을 기준으로 강한 비밀값과 실제 HTTPS 도메인을
설정합니다. 운영 준비, DB 백업/복구, `develop → master`, CD, 롤백의 정본은
[배포 런북](ops/DEPLOYMENT.md)입니다.

## 운영상 중요한 규칙

- 브라우저의 사용자 ID는 신뢰하지 않고 인증 쿠키에서만 사용자 문맥을 결정합니다.
- 모든 사용자 데이터 쿼리는 트랜잭션 범위의 PostgreSQL RLS를 거칩니다.
- AI 서버에는 서비스 DB 자격 증명이 없습니다. AI 세션/OAuth/감사 로그는 별도 영속 경로를 씁니다.
- AI 출력은 제안일 뿐이며 서버가 노드 정체성, 참조, 지원 판단, 역량 검증 점수, 허용 간선과 그래프 버전을 재검증합니다.
- 분석과 증빙 작업은 재진입 가능한 DB 큐에서 처리됩니다.
- 대화 답변과 커리어 자료 파편화도 같은 방식의 재진입 가능한 DB 큐에서 처리됩니다.
- 시간당 AI 요청 제한, 로그인·가입 제한, CSRF, HttpOnly 쿠키와 요청 추적 ID가 적용됩니다.
- AI 서버는 모델의 내부 사고 내용 대신 작업 ID·단계·경과 시간·토큰 사용량을
  `JOBISS_AI_PROGRESS` 로그로 10초마다 출력합니다.

상세 내용은 [아키텍처](docs/architecture.md), [API 계약](docs/api-contract.md),
[AI 에이전트 연동 가이드](docs/ai-agent-integration.md),
[운영 가이드](docs/operations.md)를 참고하세요.
