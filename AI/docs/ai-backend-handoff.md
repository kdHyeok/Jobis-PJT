# AI ↔ 백엔드 인수인계 / 협의 자료

> 작성: AI 파트 · 대상: 백엔드 파트
> 목적: **지금 확보하면 좋은 데이터 / 백엔드가 맡을 작업 / AI와 협의·결정해야 할 사항**을 한 번에 정리.

---

## 0. 먼저 알아둘 전제

- 자비스는 **백엔드 서버와 AI 서버를 분리**하고, **입출력 계약(스키마)을 먼저 확정한 뒤 mock 으로 병렬 개발**한다. (설계 15.4)
- 이 문서의 계약 기준은 **설계 문서 15장** + 실제 코드 `src/jobis_ai/contracts/api.py` 이다.
- ⚠️ 기획 폴더의 `미니_프로젝트_백엔드/소프트웨어_요구사항_명세서.md` 두 파일은 **SSAFY 공통 프로젝트(화상회의) 템플릿**으로, **자비스와 무관**하다. 자비스 백엔드는 새로 설계한다. (user/conference/WebRTC 테이블은 참고하지 말 것)
- 현재 AI 서버는 **스켈레톤**: 그래프 전체 흐름은 돌지만 각 에이전트는 아직 mock 을 반환한다. 계약은 이미 고정되어 있으므로 백엔드는 지금부터 이 계약에 맞춰 개발 가능.

---

## 1. 지금 당장 확보하면 좋은 데이터 (우선순위 순)

AI 성능은 데이터 확보 속도에 직결된다. 아래는 백엔드/기획과 함께 지금부터 모으면 좋은 데이터다.
(데이터 조회 우선순위 원칙: **내부 정형 DB → 벡터/RAG → 웹 검색 → 외부 LLM**, 설계 6장)

| 순위 | 데이터 | 쓰는 에이전트 | 형식/규모 | 왜 필요한가 |
|---|---|---|---|---|
| ★★★ | **채용공고 원문 세트** | Job Posting Parser | URL + 원문 텍스트, 직무·연차·도메인 다양하게 수십 건 | 파싱 프롬프트 개발·평가의 입력. IT 웹 백엔드 우선 |
| ★★★ | **사용자 프로필/이력 샘플** | User Profile Builder, Gap Analyzer | 학력·경력·프로젝트·스킬·자격증 구조 (강점 뚜렷 케이스 + 애매 케이스) | 갭 분석·로드맵 테스트의 입력 |
| ★★★ | **기업 정보** | Gap Analyzer(company_context) | 기업명·도메인·기술스택·인재상·복지·규모 | 공고 맥락 보강, 대체 경로 탐색 |
| ★★☆ | **기술/직무 taxonomy** | 전 에이전트 | 스킬 표준어 사전 (예: "SpringBoot=Spring Boot=스프링부트") | 요구사항↔경험 매칭 정확도의 핵심 |
| ★★☆ | **근거 문서 (RAG용)** | Gap Analyzer, Alt Path Finder | 기업 후기·기술 블로그·면접 후기·직무 소개 | 벡터 DB 적재해 근거 기반 조언 |
| ★★☆ | **평가용 정답 라벨셋** | 전체 (성능 평가) | (공고 × 프로필) 페어별 충족/부족 요구사항, 기대 강점/gap, 정답 근거 문서 id | 지표(F1/Recall@k/Groundedness) 측정·개선 (설계 18장) |
| ★☆☆ | **유사/대체 공고 풀** | Alternative Path Finder | 저연차·유사 스택 공고 모음 | 대체 경로 추천 후보 (2차 우선순위) |

> 정보가 없는 필드는 추측하지 말고 `null` 로 둔다. (설계 8.4 / 18.2)

**데이터 수집 시 백엔드에 부탁할 것**
- 위 데이터를 담을 **자비스 도메인 테이블 설계** (아래 2절)
- 공고/기업/후기 크롤링·적재 파이프라인은 AI·백엔드가 역할 분담 (협의 4절)

---

## 2. 백엔드가 맡을 작업 (권장 범위)

AI 서버가 분석 "두뇌"라면, 백엔드는 **데이터·인증·중계·저장**을 맡는다.

1. **자비스 도메인 DB 설계·구축** — 예상 핵심 테이블
   - `user` (인증)
   - `job_posting` (공고 원문/파싱 결과 캐시)
   - `user_experience` (사용자가 선택하는 경험 단위 — `selectedExperienceIds` 의 소스)
   - `company` (기업 정보)
   - `analysis` (분석 요청·결과 저장, `analysisId` 관리)
   - `analysis_source` / `review_doc` 등 (근거·후기)
2. **인증/인가** — 로그인, JWT 등. (사용자 식별 → `userId`)
3. **파일 업로드** — 이력서/포트폴리오(PDF 등) 업로드·저장. (텍스트 추출 책임 경계는 협의)
4. **AI 서버 호출 오케스트레이션**
   - 프론트 요청 → 백엔드가 `POST /api/v1/analyze` 로 AI 서버 호출 → 결과 저장·반환
   - `need_more_info` 응답 시 `followUpQuestions` 를 프론트에 노출하고, 사용자 답을 모아 **같은 `analysisId` 로 재요청**
5. **진행상태(SSE) 중계** — AI 서버의 status 스트림을 받아 프론트로 중계 (설계 17장)
6. **사용자 데이터 조회 수단 제공** — AI 가 "내부 정형 DB 우선 조회" 원칙을 지키려면, 백엔드가 프로필/경험/기업 데이터를 **요청에 실어 전달**하거나 **조회 API** 를 제공해야 함 (협의 4절 핵심 항목)

---

## 3. 확정된 인터페이스 계약 (이대로 개발 시작 가능)

전체 스키마·샘플은 `docs/contracts/` 참고:
- `analyze_request.schema.json` / `analyze_response.schema.json` (JSON Schema)
- `sample_request.json` / `sample_response.json` (실제 실행 샘플)

### 3.1 분석 요청 — `POST /api/v1/analyze`

```json
{
  "userId": 1,
  "jobPostingInput": { "sourceType": "url", "value": "https://..." },
  "selectedExperienceIds": [3, 7, 9],
  "preparationPeriodWeeks": 16,
  "availableHoursPerWeek": 20,
  "options": { "includeAlternatives": true },
  "analysisId": null
}
```
- `sourceType`: `url | text | file`
- `analysisId`: 최초엔 `null`, `need_more_info` 재개 시 이전 값 포함

### 3.2 분석 응답

```json
{
  "analysisId": "uuid",
  "status": "completed | need_more_info | failed",
  "requirements": [],
  "strengths": [],
  "gaps": [],
  "roadmap": [],
  "alternativeJobs": [],
  "followUpQuestions": [],
  "sources": [],
  "warnings": [],
  "meta": { "retriedNodes": [], "generatedAt": "ISO8601", "modelVersion": "" }
}
```
- `status == need_more_info` → 백엔드는 `followUpQuestions` 노출 후 `analysisId` 포함해 재요청

### 3.3 진행상태 이벤트 (SSE, 설계 17장) — *스키마 협의 후 확정*

분석은 수십 초 이상 걸리므로, AI 서버가 노드 단위로 진행상태를 스트리밍하고 백엔드가 프론트로 중계한다.

- 제안 엔드포인트: AI 서버 `GET /api/v1/analyze/{analysisId}/stream` (SSE) → 백엔드가 받아 프론트로 재중계
- 이벤트 envelope:

```json
{ "status": "analyzing_gap", "from": "build_user_profile", "to": "analyze_gap",
  "message": "이력 검증 → 갭 분석 담당에게 전달", "timestamp": "ISO8601" }
```

`from → to` 는 프론트의 "에이전트 핸드오프" 시각화용이다. (설계 17.3)

| status 코드 | 프론트 표시 문구 |
|---|---|
| `parsing_job` | 채용공고 분석 중 |
| `building_profile` | 사용자 경험 조회 중 |
| `need_info` | 부족한 정보 확인 중 |
| `analyzing_gap` | 강점·부족 역량 분석 중 |
| `fetching_company` | 기업 정보 검색 중 |
| `planning_roadmap` | 준비 로드맵 생성 중 |
| `finding_alternatives` | 유사 공고 비교 중 |
| `verifying` | 최종 결과 검증 중 |
| `completed` | 완료 |

---

## 4. 협의·결정이 필요한 항목 (❗ 백엔드 회신 요청)

계약을 완전히 못 박기 전에 아래를 함께 정해야 한다.

| # | 결정할 것 | 선택지 | AI 파트 의견 |
|---|---|---|---|
| 1 | **사용자 프로필/경험 데이터 전달 방식** | (a) AI가 백엔드 DB 직접 접근 (b) 백엔드가 요청 body 에 프로필 동봉 (c) 백엔드가 조회 API 제공 | **(c) 조회 API** 선호 (결합도↓, 계약 명확). MVP는 (b)도 수용 |
| 2 | **`selectedExperienceIds` 의 정의** | 어느 테이블의 어떤 id 체계인가 | 백엔드 `user_experience.id` 로 가정 — 확정 필요 |
| 3 | **파일(이력서) 텍스트 추출 책임** | (a) 백엔드가 추출 후 텍스트 전달 (b) AI가 `document_text_extract` 로 처리 | 파싱 품질 위해 **(b) AI 처리** 선호. 대신 파일 접근 경로/URL 필요 |
| 4 | **호출 방식(동기 vs 비동기)** | (a) 동기 REST (b) 작업 큐 + 폴링/웹훅 | 분석이 수십 초~수 분 → **비동기 권장**. 최소 SSE로 진행상태 노출 |
| 5 | **`analysisId` 발급 주체** | (a) AI가 발급 (b) 백엔드가 발급해 전달 | 현재 AI가 uuid 발급 중. 저장 주체가 백엔드면 **(b)로 통일** 검토 |
| 6 | **AI↔백엔드 내부 통신 인증** | API Key / mTLS / 내부망 | 내부 통신 방식 합의 필요 |
| 7 | **벡터 DB 소유·운영 주체** | AI 파트 운영 가정 | 인프라(호스팅/비용)는 팀 협의 |
| 8 | **`status=failed` 에러 응답 규약** | 공통 에러 포맷 정의 | `{code, message}` 형태 제안 |

---

## 5. 백엔드에 전달하는 산출물 체크리스트

- [x] 이 문서 (`docs/ai-backend-handoff.md`)
- [x] 계약 JSON Schema (`docs/contracts/analyze_*.schema.json`)
- [x] 샘플 요청/응답 (`docs/contracts/sample_*.json`)
- [ ] 협의 4절 회신 → 회신 반영해 계약 v1 **동결**
- [ ] (협의 후) SSE 이벤트 스키마 확정본
- [ ] (협의 후) 사용자 데이터 조회 API 스펙 (선택지 1-c 채택 시)

---

## 6. 다음 액션

1. 백엔드: 4절 8개 항목 회신
2. 공동: 회신 반영해 `contracts/api.py` = **계약 v1 동결** 후 각자 mock 병렬 개발
3. AI: 1절 데이터 확보되는 대로 노드 mock → 실제 체인 교체 (Job Posting Parser 부터)

---

## 부록 A. 자비스 도메인 테이블 초안 (제안 · 협의 대상)

백엔드 ERD 설계의 출발점. 컬럼은 제안이며 확정본은 백엔드가 결정한다. (SSAFY 화상회의 템플릿과 무관)

```text
user [사용자]
  id           BIGINT PK
  user_id      VARCHAR   -- 로그인 ID
  password     VARCHAR
  name         VARCHAR
  created_at   DATETIME

user_experience [사용자 경험 단위]   -- 요청의 selectedExperienceIds 소스 (협의 #2)
  id           BIGINT PK
  user_id      BIGINT FK -> user.id
  type         VARCHAR   -- project | work | education | cert | language | award ...
  title        VARCHAR
  content      TEXT      -- 상세 (문제-조치-성과 등)
  started_at   DATE
  ended_at     DATE

company [기업]
  id           BIGINT PK
  name         VARCHAR
  domain       VARCHAR   -- 산업/도메인
  tech_stack   JSON      -- ["Java","Spring", ...]
  culture      TEXT      -- 인재상/복지 등
  meta         JSON

job_posting [채용공고]
  id           BIGINT PK
  company_id   BIGINT FK -> company.id (nullable)
  source_type  VARCHAR   -- url | text | file
  source_value TEXT      -- 원문/URL
  parsed_json  JSON      -- AI 파싱 결과 캐시(normalizedJobPosting)
  created_at   DATETIME

analysis [분석 세션]   -- analysisId 관리 (협의 #5)
  id           VARCHAR PK  -- = analysisId(uuid)
  user_id      BIGINT FK -> user.id
  job_posting_id BIGINT FK -> job_posting.id
  status       VARCHAR   -- completed | need_more_info | failed
  request_json JSON      -- AnalyzeRequest 스냅샷 (need_more_info 재개용)
  result_json  JSON      -- AnalyzeResponse
  created_at   DATETIME
  updated_at   DATETIME

analysis_event [진행 이벤트 로그]  -- SSE 재생/감사용(선택)
  id           BIGINT PK
  analysis_id  VARCHAR FK -> analysis.id
  status       VARCHAR
  payload      JSON
  created_at   DATETIME
```

## 부록 B. 요청 라이프사이클 시퀀스

```text
[정상 흐름]
프론트 → 백엔드: 분석 요청(userId, 공고, 선택경험, 기간/시간)
백엔드 → AI:   POST /api/v1/analyze   (analysisId 없음)
AI:            그래프 실행, 노드마다 status 이벤트 스트리밍
백엔드 → 프론트: SSE 중계 (진행상태 UI)
AI → 백엔드:   200 { status: "completed", ... }
백엔드:        analysis.result_json 저장 → 프론트 응답

[정보 부족 → 재개]
AI → 백엔드:   200 { status: "need_more_info", followUpQuestions: [...], analysisId }
백엔드 → 프론트: 추가 질문 노출
프론트 → 백엔드: 사용자 답변
백엔드 → AI:   POST /api/v1/analyze  (같은 analysisId + 보강된 입력)
AI:            중단 지점부터 재개 → completed
```
