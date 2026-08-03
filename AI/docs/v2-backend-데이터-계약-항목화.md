# AI → 백엔드 제출 자료 항목화 (커리어지도 로드맵용)

작성 2026-08-03. 목적: **"적합도 중·하면 로드맵이 채팅 대신 커리어지도 페이지에 생성된다"** 를
성립시키기 위해 AI 서버가 백엔드에 넘겨야 하는 자료를 항목으로 고정한다.
백엔드·프론트는 이미 구현됨 — 이 문서는 **AI 쪽 산출물 명세**만 다룬다.

권위: `ai-server/app/models.py`(파이썬 기준 모델) = `backend/.../analysis/AiContracts.java`(자바 대칭 모델)
> `docs/ai-agent-integration.md`. 아래 근거 표기는 전부 백엔드 코드 실물이다.

---

## 0. 먼저 확정할 사실 세 가지

1. **로드맵 그림은 AI가 만들지 않는다.** 노드·간선·좌표·경력 관문은 `RoadmapService`
   (`generateDraft`→`buildSnapshot`)가 DB 행에서 결정론으로 만든다. AI는 **그 행의 재료**만 낸다.
2. **적합도 등급(중·하) 분기도 AI가 하지 않는다.** 최종 verdict 는 `AnalysisWorker.evaluateReadiness()`
   가 검증된 역량 수·경력 개월로 다시 계산하고, AI가 보낸 `evaluation` 은 설명 문구로만 저장된다
   (`conversation_messages.metadata.evaluation`). → **AI는 등급에 따라 제출물을 줄이거나 늘리지 않는다.
   COMPLETED 면 항상 competencyProposal 전량을 낸다.**
   - `APPLY_NOW`: 필수 역량 전부 충족 + 경력 충족
   - `ALTERNATIVE_FIRST`(≈하): 경력 부족 12개월 초과 **또는** 필수 충족률 < 0.5
   - `STRENGTHEN_THEN_APPLY`(≈중): 그 사이
3. **"채팅으로 말하지 않고 지도로 보낸다"** 의 유일한 레버는 `/v1/chat` 응답의
   `suggestedActions[].action = "OPEN_MAP"` 이다(허용값: `ATTACH_POSTING` `OPEN_MAP` `OPEN_STORAGE` `NONE`).
   로드맵 항목을 `message` 본문에 나열하지 않는다.

---

## 1. `POST /v1/analyses` (+ `/v1/analyses/stream`) — 지도 재료의 전부

### 1-1. 응답 골격
| 필드 | 필수 조건 |
|---|---|
| `status` | `COMPLETED` \| `NEEDS_INPUT` |
| `question` | `NEEDS_INPUT` 일 때만. 나머지 셋은 null |
| `job`, `evaluation`, `competencyProposal` | `COMPLETED` 면 **셋 다** 필수 (하나라도 null → 워커가 job FAILED 처리) |

### 1-2. `job` (JobContext) — 경력 관문·트랙 분기의 재료
| 필드 | 값·제약 | 백엔드에서 무엇이 되는가 |
|---|---|---|
| `primaryTrack` | **필수**. `BACKEND FRONTEND FULLSTACK DATA AI DEVOPS CLOUD SECURITY GAME MOBILE` | `posting_path_profiles.primary_track` → 지도의 트랙 가지, `관련 OO 취업` GATE 노드 |
| `experienceRequirement.type` | `NONE` \| `REQUIRED` \| `PREFERRED` | `REQUIRED` 만 경력 관문을 만든다. `NONE` 이면 `minimumMonths=0` 강제 |
| `experienceRequirement.minimumMonths` | 0~600 | `실무 경력 N년` MILESTONE 노드의 임계값 + 티어(단 tier) 위치 |
| `experienceRequirement.maximumMonths` | null 허용, min 이상 | 상한 표기 |
| `experienceRequirement.sourceText` | 1~1000자, 공고 원문 근거 | 화면의 경력 조건 문구 |
| `companyName` / `roleTitle` | 파싱값 | OPPORTUNITY 노드 제목·부제 (단, 카탈로그 표기로 덮일 수 있음) |
| `employmentType` / `experienceText` | 파싱값 | 공고 표시용 |
| `closesAt` / `lifecycleStatus` | `ACTIVE EXPIRED CLOSED UNKNOWN` | 마감 공고는 **로드맵 목표로 추가 불가**(`POSTING_CLOSED`) |
| `parsedData` | 자유 dict | `job_postings.parsed_data` 로 원본 보존 |

### 1-3. `competencyProposal.competencies[]` — 지도의 모든 역량 노드
1~100건, `ref`·`canonicalKey` 각각 유일.

| 필드 | 값·제약 | 백엔드에서 무엇이 되는가 |
|---|---|---|
| `ref` | `^[A-Za-z0-9_-]{1,80}$` | 응답 내부 참조 키(requirements·targetProject 가 가리킴) |
| `canonicalKey` | `^[a-z0-9][a-z0-9._:-]{2,159}$` | `user_competencies` 유일키. **`foundation.` 접두어는 공통 기반 줄기**로 취급됨 |
| `title` | 1~160자 | 노드 제목 |
| `domain` | `COMMON BACKEND FRONTEND DATA DEVOPS CLOUD SECURITY AI MOBILE GAME DOMAIN CAREER` | 노드 분야(DB CHECK 있음) |
| `kind` | `TECHNOLOGY KNOWLEDGE PRACTICE TASK DOMAIN_KNOWLEDGE EXPERIENCE CREDENTIAL` | `EXPERIENCE`/`CREDENTIAL` 은 career 노드 종류가 바뀐다 |
| `stage` | `FOUNDATION WEB LANGUAGE FRAMEWORK DATA QUALITY OPERATIONS SCALE DOMAIN EXPERIENCE CREDENTIAL` | **노드의 가로 순서(단계)**. 같은 `track|stage` 는 한 MILESTONE 으로 묶인다 |
| `scopeDefinition` | 1~4000자, 공백만 금지 | "무엇까지 하면 충족인가". 역량 정체성의 일부(`canonicalKey+scope+level`) |
| `requiredLevel` | 1~5 | 요구 수준. `verified_level >= requiredLevel` 이어야 충족으로 계산됨 |
| `roadmapEligible` | bool | **false 면 로드맵에서 완전히 제외**(카탈로그 등재 안 됨, 준비도 분모에서도 빠짐). 정성적 태도·소통력은 false |
| `verificationMethod` | `roadmapEligible=true` 면 **비어 있으면 안 됨** | 그 역량을 무엇으로 검증하는지 |
| `prerequisiteRefs` | ≤5, 순환 금지, 같은 응답의 ref | ⚠️ 파이썬 모델엔 있으나 `AiContracts.AnalyzedCompetency` 에 아직 없다 → 지금은 무시된다(보내도 무해) |

### 1-4. `competencyProposal.requirements[]` — 필수/우대 관계
1~200건, `(competencyRef, relation)` 중복 금지.

| 필드 | 값·제약 | 효과 |
|---|---|---|
| `competencyRef` | 같은 응답의 ref | `posting_competency_requirements.competency_id` |
| `relation` | `REQUIRED` \| `PREFERRED` \| `RESPONSIBILITY` | **REQUIRED = 지도의 본선 경로**, PREFERRED = "우대사항 선택 퀘스트"(optional 노드). ⚠️ `RESPONSIBILITY` 는 `RoadmapService` 가 읽지 않아 **지도에 안 나온다** |
| `sourceText` | 1~4000자, 공고 원문 인용 | 노드 근거 문구(`job_requirements.source_text`) |
| `confidence` | 0~1 | 근거 신뢰도 |

경력 요건 특례: `experienceRequirement.type=REQUIRED` 이고 `minimumMonths>0` 인 공고에서
`kind=EXPERIENCE` 또는 `stage=EXPERIENCE` 인 REQUIRED 요건은 일반 노드가 아니라
**경력 관문 노드로 흡수**된다(`isCareerGateRequirement`).

### 1-5. `competencyProposal.targetProject` — PROJECT 노드 1개
| 필드 | 제약 | 효과 |
|---|---|---|
| `title` / `objective` / `domainContext` | 1~200 / 1~4000 / 1~4000자 | PROJECT 노드 제목·목표·도메인 맥락 |
| `requiredCompetencyRefs` | **1개 이상**, 30 이하 | 프로젝트가 증명하는 역량 |
| `optionalCompetencyRefs` | ≤20 | 선택 역량 |
| `deliverables` | **1개 이상**, ≤20 | 산출물 목록 |
| `acceptanceCriteria` | **1개 이상**, ≤30 | 완료 기준 |
| (공통 규칙) | 참조는 전부 같은 응답의 ref, 중복 금지, **`roadmapEligible=false` 역량 참조 금지** | 위반 시 계약 검증 실패(502) |

PROJECT 노드는 필수 역량 경로 끝에 붙고, 그 뒤에 OPPORTUNITY(공고) 노드가 온다.
프로젝트가 없으면 지도에 회사 가지가 완성되지 않는다 → **targetProject 는 옵션이 아니다.**

### 1-6. `evaluation`
`verdict`(`APPLY_NOW`/`STRENGTHEN_THEN_APPLY`/`ALTERNATIVE_FIRST`) + `summary` + `reasons[]`.
저장은 되지만 **지도·판정에 영향 없음**(0-2 참조). 사용자에게 보일 설명 문구로만 쓴다.

### 1-7. `NEEDS_INPUT` 되묻기
- `question.key`: `^[a-z0-9][a-z0-9._-]{1,79}$`, **같은 job 안에서 재사용 금지**(재질문하면 워커가 실패 처리)
- `options`: **2~4개**, `value` 유일, `label`·`description` 비우지 않기
- 되묻기는 job 당 **최대 3회**(`questionCount>=3` 이면 실패)
- 이때 `job`/`evaluation`/`competencyProposal` 은 반드시 null

### 1-8. 스트림(`/v1/analyses/stream`, NDJSON) — 진행 화면(피자)용
한 줄 = 한 이벤트, `runId` 동일, `sequence` 1부터 엄격 증가.
- `RUN_STARTED`: `stages[]` 1~12개, 각 `{id,label,role,message,color(#rrggbb)}`
- `STAGE_UPDATED`: `stage.{id,status,message}`, status ∈ `PENDING RUNNING WAITING COMPLETED FAILED`
- `RESULT`: `result` = 1-1 응답 전문
- `ERROR`: `errorCode`/`errorMessage` (스트림을 그냥 끊지 않는다)
- `runId` 는 **요청의 analysisJobId 와 일치**해야 한다(`recordProgress` 가 불일치를 예외로 던진다)
- 미구현 시 404/405 면 백엔드가 `/v1/analyses` 로 자동 폴백 → 스트림은 진행 화면용 선택 사항

---

## 2. `POST /v1/chat` — "말하지 말고 지도로 보내기"
| 필드 | 값 |
|---|---|
| `message` | 1~4000자. **로드맵 항목 나열 금지** — 무엇이 지도에 생겼는지 한두 문장 안내까지 |
| `intent` | `GENERAL_CAREER PROFILE_DISCOVERY POSTING_ANALYSIS ROADMAP_QUESTION EVIDENCE_HELP OTHER` |
| `shouldRequestPosting` | 공고가 필요할 때 true |
| `suggestedActions` | ≤3건. **로드맵이 생겼으면 `{"action":"OPEN_MAP","label":"커리어 지도 보기"}`** |

---

## 3. 나머지 엔드포인트 (계약만 유지)
| 경로 | 응답 필수 필드 |
|---|---|
| `POST /v1/career-extractions` | `summary`, `fragments[]` **1건 이상**. kind ∈ `SKILL PROJECT EXPERIENCE EDUCATION CREDENTIAL ACHIEVEMENT LINK`, `canonicalKey` 는 패턴 맞거나 null |
| `POST /v1/evidence-verifications` | `verdict` ∈ `VERIFIED NEEDS_WORK REJECTED`, `confidence` 0~1, `summary`, `strengths/gaps/nextActions` |
| `POST /v1/competency-assessments` | `sessionSummary` + (`answerEvaluation` \| `nextQuestion`). 문제 kind ∈ `CONCEPT CODE SCENARIO FOLLOW_UP`, 점수 0~100, `coreCriteria` 만 통과 판정에 쓰임 |
| `GET /v1/health`, `GET /v1/ready` | 프로세스·공급자 상태 |

오류는 `{"detail":{"code","message"}}` 형태로, 코드는
`AI_PROVIDER_NOT_CONFIGURED`(503) / `AI_PROVIDER_UNAVAILABLE`(503) / `INVALID_AI_RESPONSE`(502) 를 유지한다.

---

## 4. 지금 AI/ 쪽 상태와의 차이 (구현해야 할 것)

현재 8000 포트에서 도는 것은 `AI/src/jobis_ai/v2bridge/app.py` 다(`/health` 확인: `jobis-ai-v2bridge`).
그 산출물과 위 계약의 차이:

| # | 항목 | 현재 | 필요 |
|---|---|---|---|
| 1 | **`competencyProposal`** | 없음. `changeProposal`(nodes/edges/requirements)을 낸다 — 백엔드에서 **legacy** 로 격리됨 | competencies/requirements/targetProject 신설. 이게 없으면 워커가 `"did not include a competency proposal"` 로 매번 FAILED → **지도에 로드맵이 절대 생기지 않는다** |
| 2 | `job.primaryTrack` | 없음 | 10종 트랙 중 하나로 판정 필요(트랙 가지의 근원) |
| 3 | `job.experienceRequirement` | 없음(`experience_text` 만) | type/minimumMonths/maximumMonths/sourceText — 경력 관문 |
| 4 | `job.closesAt` / `lifecycleStatus` | 없음 | 마감 공고 목표 추가 차단에 쓰임 |
| 5 | `stage` / `domain` / `kind` / `requiredLevel` / `roadmapEligible` / `verificationMethod` | 없음(어댑터가 level=2 상수로 채움) | 노드 배치·검증의 전부. 상수로 두면 지도가 한 줄로 뭉친다 |
| 6 | `targetProject` | 없음 | PROJECT 노드. 없으면 회사 가지 미완성 |
| 7 | `POST /v1/analyses/stream` | 없음(404 → 폴백) | 피자형 진행 화면을 쓰려면 필요 |
| 8 | `POST /v1/competency-assessments` | 없음 | 역량 검증 화면이 통째로 죽는다 |
| 9 | `/v1/chat` `suggestedActions=OPEN_MAP` | 미사용(로드맵을 문장으로 읊는다 — 실측 세션 `v2-chat-ae039c84`) | 로드맵은 지도로, 채팅은 안내만 |
| 10 | `/health` 경로 | `/health` | 문서 기준은 `/v1/health`·`/v1/ready` (백엔드가 지금 쓰진 않음 — 낮은 우선순위) |

우선순위: **1 → 2·3 → 5 → 6 → 9 → 4 → 7 → 8 → 10.**
1~6 이 끝나야 커리어지도에 로드맵이 생기고, 9 가 끝나야 "채팅이 아니라 지도" 가 된다.

## 5. AI가 하지 않는 일 (경계)
- 노드 좌표·간선·경력 관문 계산 (백엔드 `RoadmapService`)
- 최종 지원 판정 (백엔드 `evaluateReadiness`)
- 사용자 역량 완료 처리 (검증 통과 여부는 백엔드가 점수로 계산)
- 대체 공고 검색 (백엔드 카탈로그)
- 로드맵 목표 추가·적용 (`/api/roadmap/*`, 사용자 행동)
