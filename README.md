# JOBIS : 채용 공고에서 시작하는 커리어 성장 AI 에이전트

> 공고를 등록하면 AI가 요구 역량을 구조화하고, 사용자의 실제 경험과 대조해 **준비할 항목만**
> 짚어 로드맵과 학습 플랜으로 잇습니다. 판단은 데이터가 하고, LLM은 읽기와 표현만 맡습니다.

---

## 📋 목차

- [🎯 프로젝트 소개](#-프로젝트-소개)
- [✨ 주요 화면](#-주요-화면)
- [🛠 기술 스택](#-기술-스택)
- [🏗 시스템 아키텍처](#-시스템-아키텍처)
- [📚 API 문서](#-api-문서)
- [📁 프로젝트 구조](#-프로젝트-구조)
- [⚡ 실행 방법](#-실행-방법)
- [💻 개발 가이드](#-개발-가이드)
- [🚢 배포](#-배포)
- [📊 프로젝트 통계](#-프로젝트-통계)
- [📚 참고 자료](#-참고-자료)

---

## 🎯 프로젝트 소개

### 왜 JOBIS?

> 취업 준비의 병목은 정보가 없는 것이 아니라 **판단이 서지 않는 것**입니다.

공고는 읽었지만 "지금 지원해도 되는가", "안 된다면 정확히 무엇이 부족한가"에 답이 없습니다.
JOBIS는 그 판단을 데이터로 만듭니다. 공고의 요구 역량을 원자 단위로 정규화하고 사용자의
커리어 근거와 대조해 **채워진 것과 비어 있는 것을 구분**한 뒤, 비어 있는 항목만 로드맵과
학습 플랜으로 연결합니다.

### 핵심 특장점

**1. 점수 대신 근거를 제시합니다**
합격 확률이나 적합도 점수를 만들지 않습니다. 공고의 필수조건·우대사항·담당 업무를 사용자의
실제 경험과 연결하고, 판단 근거를 출처·원문·수집일과 함께 저장해 추적할 수 있게 합니다.

**2. 판정하지 못한 항목을 부족으로 세지 않습니다**
근거가 없으면 `not_met`이 아니라 `uncertain`으로 분모에서 제외하고 되묻습니다. 모르는 것을
부족으로 세면 근거 없는 로드맵이 쌓입니다.

**3. 생성 결과를 규칙으로 다시 검증합니다**
AI는 허용된 도구만 호출하며, 결과는 필수·우대 구분과 근거 존재 여부 규칙으로 재검사합니다.
매칭·계산·분기는 결정론 코드가 담당하고 LLM은 읽기와 표현만 맡습니다.

**4. 자동 확정과 자동 적용을 차단합니다**
경험 저장, 계획 적용, 재계획에 모두 사용자 승인을 요구합니다. 상태 전이는 관계형 데이터와
실행 이력으로 남아 되돌릴 수 있습니다. 외부 자료 조회(RAG)는 보조 기능으로 분리해 검색이
실패해도 핵심 분석이 계속되며, 폴백 사유는 경고로 노출합니다.

### 타겟 유저

- **취업 준비생** : 지원할 공고는 정했지만 무엇을 더 준비해야 하는지 판단이 서지 않는 경우
- **직무 기반으로 성장을 설계하려는 학생** : 막연한 학습 대신 실제 공고의 요구 역량을
  기준으로 준비 순서를 잡고 싶은 경우
- **커리어 전환을 준비하는 비개발 직무 재직자** : 기존 경험 중 무엇이 근거로 인정되고
  무엇을 새로 채워야 하는지 구분이 필요한 경우

---

## ✨ 주요 화면

### 1. 랜딩 : 첫 진입과 로그인

![랜딩](docs/demo/1-랜딩.webm)

### 2. 커리어 저장소 : 이력서·포트폴리오를 근거 단위로 분해

![커리어 조각](docs/demo/2-커리어조각.webm)

- docx, txt, md 파일의 첨부를 지원합니다.
- 업로드한 이력서·포트폴리오를 커리어 조각으로 분해해 저장합니다.
- 중복 조각은 병합하되 되돌릴 수 있게 남깁니다.
- 종류·등록일·최근 수정 기준으로 정렬하고 원본 자료를 다시 확인할 수 있습니다.

### 3. 대화 : 커리어 저장소 기반 역량 분석

![커리어 분석](docs/demo/3-커리어분석.webm)

- 저장된 커리어 조각을 근거로 현재 역량을 정리합니다
- 근거가 부족한 항목은 실패로 처리하지 않고 `답변 필요` 상태로 되묻습니다
- 사용자 메시지는 즉시 저장되고 AI 응답은 비동기로 도착해 지연이나 실패에도 유실되지 않습니다

### 4. 대화 & 커리어 지도 : 공고 분석 및 로드맵 제안

![대화](docs/demo/4-대화.webm)

- 공고 URL·원문·이미지를 입력받아 요구 조건을 구조화합니다
- URL 파싱이 실패하면 iframe 추적 → Jina Reader → Firecrawl → Tavily 순으로 단계별
  재시도해 원문 추출 성공률을 높입니다
- 요구 역량을 커리어 조각과 대조해 채워진 것과 비어 있는 것을 구분합니다
- 로드맵은 초안(DRAFT)으로 제안되며 미리보기 후 적용 또는 취소합니다
- 적용 이력은 버전으로 남아 이전 상태로 되돌릴 수 있습니다

### 5. 학습 플랜 : 로드맵을 주·월 단위 실행으로

![학습 플랜](docs/demo/5-학습플랜.webm)

- 로드맵 단계를 주간·월간 학습 플랜으로 펼칩니다
- 채팅형 학습 워크스페이스에서 개념 질문·과제·퀴즈를 진행합니다
- 완료 상태는 커리어 지도 노드에 즉시 반영됩니다

---

## 🛠 기술 스택

### Frontend

| 기술 | 버전 | 용도 |
|---|---|---|
| Vue | 3.5 | SPA 프레임워크 |
| Vite | 7.0 | 빌드·개발 서버 |
| TypeScript | 5.7 | 정적 타입 |
| Node.js | 22-alpine | 빌드 런타임 |
| Nginx | 1.27-alpine (unprivileged) | 정적 파일 서빙 + `/api` 프록시 |

### Backend

| 기술 | 버전 | 용도 |
|---|---|---|
| Spring Boot | 4.1.0 | API 서버 (내장 Tomcat) |
| Java | 17 (Eclipse Temurin) | 런타임 |
| Gradle | 9.5.1 (wrapper) | 빌드 |
| Spring Security | — | 인증·인가, CSRF |
| Flyway | — | 스키마 마이그레이션 (V1~V76) |

### AI

| 기술 | 버전 | 용도 |
|---|---|---|
| Python | 3.11 | 런타임 |
| FastAPI · uvicorn | — | AI 서버 (`jobis_ai.v2bridge.app`) |
| uv | — | 의존성 잠금 (`--frozen` 강제) |

### Data & ETL

| 기술 | 버전 | 용도 |
|---|---|---|
| PostgreSQL | 17-alpine | 서비스 DB |
| pgvector | pg16 | 벡터 DB |
| Apache Airflow | — | 수집·OCR·적재·색인 DAG 5개 |
| BGE-M3 | `BAAI/bge-m3` | 임베딩 (1024차원) |
| BGE-reranker-v2-m3 | `BAAI/bge-reranker-v2-m3` | 검색 리랭킹 |

### Infrastructure

| 기술 | 용도 |
|---|---|
| Docker · Docker Compose v2 | 컨테이너 실행 (묶음 2개) |
| AWS EC2 | 단일 인스턴스 호스팅 |
| Nginx (호스트) | TLS 종료, 경로별 서비스 분배 |
| Jenkins | CI/CD 3단 게이트 + 이미지 승격 배포 |

### External Services

| 서비스 | 용도 | 필수 |
|---|---|---|
| Anthropic API | LLM (팀 표준) | 셋 중 하나 |
| SSAFY GMS (OpenAI 호환) | LLM | 셋 중 하나 |
| OpenAI Codex (OAuth) | LLM | 셋 중 하나 |
| Jina Reader · Firecrawl · Tavily | JS 렌더 공고 원문 추출 폴백 | 선택 |
| NAVER CLOVA Studio | 이미지 공고 OCR/VLM | 선택 |

수집 대상 채용 사이트: 사람인 · 인크루트 · 잡코리아 · 원티드 · 고용24

### Development Tools

| 도구 | 용도 |
|---|---|
| GitLab | 소스·MR·protected branch |
| Jenkins | 파이프라인 |
| JUnit · Testcontainers | 백엔드 테스트 |
| pytest | AI 테스트 (LLM 호출 없는 결정론 회귀) |
| Vitest · Playwright | 프론트 단위·E2E |
| ruff · ESLint · SpotBugs | 정적 분석 |

---

## 🏗 시스템 아키텍처

### 전체 구조도

![시스템 아키텍처](docs/images/시스템_아키텍처.png)

단일 EC2 인스턴스에서 Docker Compose 두 묶음이 동작합니다.

| 계층 | 포트 | 역할 |
|---|---|---|
| 프론트엔드 | `8088` | SPA 정적 파일 + `/api` 프록시 |
| 백엔드 | 내부 `8080` | 정본 상태·인증·분석 잡 오케스트레이션 |
| AI | 내부 `8000` | 공고 구조화, 적합도, 역량 정규화, 로드맵 제안 |
| RAG 검색 | `8765` | 공고 추천 (하이브리드 검색) |
| 데이터 파이프라인 | `8081` | 크롤링 → OCR → 적재 → 임베딩 |
| DB | 내부 `5432` | 서비스 DB와 벡터 DB |
| CI/CD | `9090` | 3단 게이트 + 이미지 승격 배포 |

### 데이터 플로우

| 단계 | 하는 일 |
|---|---|
| **수집** | 공고 URL·원문·이미지를 받아 구조화합니다. JS 렌더 페이지는 폴백 3종으로 재수집합니다 |
| **확인** | AI가 읽은 원문을 **사용자가 승인한 뒤에만** 분석합니다 |
| **분석** | 요구 역량을 원자 단위로 정규화하고 커리어 조각과 대조해 상태와 근거를 만듭니다 |
| **제안** | 부족한 역량을 프로젝트·학습 단계로 엮어 로드맵 초안(DRAFT)을 만듭니다 |
| **확정** | 사용자가 미리보기를 확인해 **적용 또는 취소**합니다. 적용은 새 버전으로 발행됩니다 |

### 정본 경계

Spring Boot와 PostgreSQL이 **대화·질문·답변·분석 상태·로드맵 버전의 정본**입니다. AI는
상태를 직접 변경하지 않고 제안만 반환하며, 상태 전이는 오케스트레이터가 독점합니다.

공고 분석은 `DRAFT → 미리보기 → 적용 또는 취소`를 거치고, 적용 이력은 버전으로 남아
되돌릴 수 있습니다.

### 주요 테이블 관계

<!-- 작성 예정 -->

---

## 📚 API 문서

### 주요 API 엔드포인트

<!-- 작성 예정 -->

---

## 📁 프로젝트 구조

```
jobis/
├─ frontend/              Vue 3 + Vite + TypeScript SPA
│   ├─ src/               views · components · api.ts · router.ts
│   ├─ tests/             단위 · 계약 · Playwright E2E
│   ├─ nginx.conf         SPA 폴백 + /api 프록시 (envsubst 렌더링)
│   └─ ci-checks          프론트엔드가 정하는 CI 검사
│
├─ backend/               Spring Boot 4 — 정본 상태 · 인증 · 분석 잡
│   └─ src/main/resources/db/migration/    Flyway V1~V76
│
├─ AI/                    FastAPI 단일 AI 서버
│   ├─ src/jobis_ai/
│   │   ├─ v2bridge/          현행 정본 엔트리포인트 (app.py)
│   │   ├─ career_pipeline/   공고 구조화 · 적합도 · 역량 정규화 · 로드맵
│   │   ├─ agents/            역할별 에이전트와 오케스트레이션 루프
│   │   └─ eval/              플래너 정확도 · 궤적 일관성 평가 하네스
│   ├─ tests/             LLM 호출 없는 결정론 회귀
│   └─ docs/decisions.md  AI 설계 결정 D1~
│
├─ RAG/                   pgvector 하이브리드 검색 (BGE-M3 임베딩 + 리랭킹)
├─ DATA/                  채용 사이트 크롤러 5종 + OCR 보강 + 적재
│
├─ infra/                 배포 뼈대 — Infra 소유
│   ├─ airflow/           수집·OCR·적재·색인 DAG, jobrag Flyway 체인
│   └─ postgres/init/     app 역할 생성 초기화 스크립트
├─ ops/                   운영 스크립트 · nginx 조각 · 배포 런북 — Infra 소유
├─ Jenkinsfile            파이프라인 뼈대 (3단 게이트) — Infra 소유
├─ compose.yaml           애플리케이션 묶음 (frontend · backend · ai · postgres)
│
├─ contract-fixtures/     AI·백엔드·프론트가 공유하는 계약 픽스처 (3계층 테스트가 소비)
├─ scripts/               로컬 실행·검증 스크립트 (check.ps1, 스모크)
├─ exec/                  포팅 매뉴얼 — 빌드·배포·외부 서비스·시연·DB 덤프
└─ docs/                  문서 (정본 + 작업기록 + archive)
```

**CI 소유권이 구조에 반영되어 있습니다.** `Jenkinsfile`·`ops/`·`infra/`·`compose.yaml`은
파이프라인 뼈대이므로 Infra 리뷰가 필요하고, `<서비스>/ci-checks`는 각 서비스가 "무엇을
검사할지" 직접 정합니다. 기능을 추가할 때는 대부분 CI 파일을 수정하지 않습니다. 테스트를
추가하면 기존 파이프라인이 그것까지 실행합니다.

---

## ⚡ 실행 방법

전체 재현 절차(비밀값 생성, Airflow·RAG 묶음, Codex 로그인, 트러블슈팅)는
**[RUN.md](RUN.md)** 가 정본입니다. 아래는 애플리케이션만 실행하는 최단 경로입니다.

### 준비

- Docker Desktop (Linux containers, Compose v2 — `docker compose`, 하이픈 없음)
- Docker에 메모리 10GB 이상 할당을 권장합니다
- LLM 키 1개 (Anthropic 권장)

```powershell
docker version
docker compose version
docker info --format '{{.OSType}}'   # linux 가 출력되어야 합니다
```

### 환경 파일

Docker 실행에 필요한 `.env`는 **두 개뿐**입니다. Compose 파일에 `env_file`이 없고 전부
`${VAR}` 보간이므로, Compose가 각 프로젝트 디렉터리의 `.env`를 자동으로 읽습니다.

| 파일 | 대상 | 예제 |
|---|---|---|
| 루트 `.env` | 애플리케이션 묶음 | `.env.compose-local.example` |
| `infra/airflow/.env` | Airflow·RAG 묶음 (선택) | `infra/airflow/.env.example` |

```powershell
Copy-Item .env.compose-local.example .env
```

`.env`에서 최소한 다음 값을 채웁니다. 비어 있으면 Compose가 기동을 거부합니다.

| 변수 | 설명 |
|---|---|
| `POSTGRES_MIGRATOR_PASSWORD` · `POSTGRES_APP_PASSWORD` | 서로 다른 난수 |
| `JWT_SECRET` | 32바이트 이상 |
| `AI_SHARED_SECRET` | 백엔드 ↔ AI 내부 인증 (두 컨테이너에 같은 값) |
| `ANTHROPIC_API_KEY` | `LLM_PROVIDER=anthropic` 기본값에 필요 |

난수 생성 함수는 [RUN.md](RUN.md) 3장에 있습니다. `.env`는 커밋하지 않습니다.

### 실행

```powershell
docker compose config --quiet
docker compose up --build -d
docker compose ps
```

`postgres`·`ai`·`backend`가 `healthy`, `frontend`가 `running`이면 정상입니다.

| 주소 | |
|---|---|
| http://localhost:8088 | 웹앱 |
| http://localhost:8088/api/health | 백엔드 헬스체크 |

### 확인

```powershell
Invoke-RestMethod http://localhost:8088/api/health | ConvertTo-Json -Depth 10
docker compose logs --tail 100 ai backend frontend
```

AI 헬스체크 200은 프로세스가 준비되었다는 의미입니다. **실제 LLM 호출 성공은 분석이나 대화를
완주해 별도로 확인합니다.**

### 중지

```powershell
docker compose stop
```

`docker compose down -v`는 DB와 AI 세션 볼륨을 삭제하므로 일반 재시작에는 사용하지 않습니다.

### 데이터 파이프라인까지 실행하려면

크롤링·OCR·RAG 색인은 별도 묶음입니다. `infra/airflow/.env`를 만든 뒤 실행합니다.

```powershell
cd infra\airflow
docker compose up -d
```

첫 실행에서는 BGE-M3 임베딩 모델을 내려받아 시간이 걸립니다. 전체 절차는
[RUN.md](RUN.md) 5~7장에 있습니다.

---

## 💻 개발 가이드

### 코드 컨벤션

<!-- 작성 예정 -->

### Git 컨벤션

<!-- 작성 예정 -->

---

## 🚢 배포

### 서버 구성

<!-- 작성 예정 -->

### CI/CD 파이프라인

```
기능 브랜치 ──▶ 바뀐 영역만 테스트 + 정적분석
develop    ──▶ 전 영역 + 운영 덤프 마이그레이션 게이트 + Compose 스모크
                → 커밋 SHA 태그로 이미지 6개 빌드·push
master     ──▶ develop에서 검증한 트리와 동일한지 강제 → 이미지 승격 → 배포
```

`master`에서는 **다시 빌드하지 않습니다.** develop에서 검증한 이미지를 그대로 승격합니다
(Build Once, Deploy Many). 자세한 소유권 규칙은 [ops/CI_OWNERSHIP.md](ops/CI_OWNERSHIP.md)에
있습니다.

### Nginx 라우팅

Nginx가 **두 대**입니다. 호스트 Nginx는 TLS를 종료하고 *어느 서비스로 보낼지* 가르며,
프론트엔드 이미지 안의 Nginx는 *그 앱 안에서 무엇을 줄지* 가릅니다.

```
사용자 ──HTTPS :443──▶ ① 호스트 Nginx — 경로별 서비스 분배
                          ├─ /          → :8088  프론트엔드 컨테이너
                          ├─ /airflow/  → :8081  Airflow
                          └─ /jenkins/  → :9090  Jenkins
                                     │
                       ② 컨테이너 Nginx — 프론트엔드 이미지에 포함
                          ├─ /api/  → backend:8080
                          └─ /      → index.html (SPA 폴백)
```

②가 이미지 안에 있으므로 호스트 Nginx 없이 앱 묶음만으로 동작합니다. 로컬에서
`docker compose up` 만으로 `localhost:8088` 이 열리는 이유입니다.

---

## 📊 프로젝트 통계

<!-- 작성 예정 -->

### 개발 일정

<!-- 작성 예정 -->

### 역할 상세

<!-- 작성 예정 -->

---

## 📚 참고 자료

### 프로젝트 문서

| 문서 | 내용 |
|---|---|
| [RUN.md](RUN.md) | 전체 재현 런북 (정본) |
| [docs/](docs/README.md) | 문서 지도 |
| [docs/아키텍처.md](docs/아키텍처.md) | 실행 구조와 신뢰 경계 |
| [docs/API-계약.md](docs/API-계약.md) | 백엔드 API 계약 |
| [docs/결정-기록.md](docs/결정-기록.md) | 설계 결정 D001~ (배경과 근거) |
| [exec/](exec/README.md) | 포팅 매뉴얼 — 빌드·배포·외부 서비스·시연 시나리오 |
| [ops/DEPLOYMENT.md](ops/DEPLOYMENT.md) | 배포·롤백 런북 |
| [AGENTS.md](AGENTS.md) | 저장소 작업 규칙 |

### 공식 문서

<!-- 작성 예정 -->

### 데이터 출처

<!-- 작성 예정 -->
