# 19. D001~D045 구현 추적표

이 문서는 `07-decision-register.md`의 결정이 코드·DB·UI·테스트 어디에 반영됐는지 기록한다. 코드가 존재하는 것과 실제 전환이 가능한 것은 구분한다. 실제 사용자 시나리오, 운영 정책 또는 외부 그래프 발행이 남아 있으면 `부분 구현`으로 표시한다.

마지막 갱신: 2026-08-06

## 결정별 상태

| 결정 | 현재 상태 | 구현·검증 근거 | 남은 경계 |
|---|---|---|---|
| D001 | 구현 | `AI-v3` 격리 코어와 별도 계약·테스트 | legacy 디렉터리 보존 |
| D002 | 구현 | provider·RAG·agent adapter 경계 유지 | 새 팀 코드 도입 시 같은 경계 재검토 |
| D003 | 구현 | AI proposal과 Spring 무결성 compiler 분리 | AI 결과의 직접 공개 금지 유지 |
| D004 | 구현 | 붙여넣기·URL·이미지·채팅 source/snapshot 확인 관문 | 현재 자동 확인 출처 없음 |
| D005 | 구현 | `StructuredPosting.positions[]`, 복수 직무 질문 | 복수 직무 실공고 회귀 유지 |
| D006 | 구현 | 승인 역량, 유사 후보, `NEW_CANDIDATE`를 무손실 보존 | 공용화는 D043 운영 절차 필요 |
| D007 | 구현 | posting·fit·project·roadmap 계약 분리 | 단계 혼합 회귀 금지 |
| D008 | 구현 | claimed·evidenced·verified 상태 분리 | UI와 계산에서 축 합치기 금지 |
| D009 | 구현 | V3 preview/apply/cancel/remove/reset/version restore | 실제 사용자 E2E 추가 필요 |
| D010 | 실험판 구현 | 통합 실험판 V3 기본, legacy 보존·명시적 rollback | 운영 기본 전환은 D036 gate 통과 후 결정 |
| D011 | 구현 | 공용 구조 cache/lease와 사용자별 적합도·로드맵 계산 분리 | 운영 부하 지표 관찰 필요 |
| D012 | 구현 | 실제 분석·채팅·자료·검증 작업만 전역 진행 배너에 포함, JOBIS 역할 표시 | p50/p95 운영 지표 필요 |
| D013 | 구현 | 결과를 바꾸는 ambiguity만 질문 | 새로운 ambiguity 유형 회귀 테스트 유지 |
| D014 | 구현 | 현재 목표·최종 목표·마감 공고 장기 목표 분리 | 목표 추천 정책은 별도 결정 |
| D015 | 구현 | Java 17, PostgreSQL, Spring, Vue, FastAPI 기본값과 운영 설정 검증 | 기술 교체 시 ADR 작성 |
| D016 | 구현 | TEXT·URL·IMAGE/OCR 모두 사용자 verified snapshot 확인 | 향후 공식 구조화 API만 별도 신뢰 검토 |
| D017 | 구현 | exact key/alias+범위만 재사용, 그 외 운영자 승인 | 자동 신규 승격 없음 |
| D018 | 구현 | VERIFIED 100/EVIDENCED 70/CLAIMED 30/NOT_MET 0, UNKNOWN 분모 제외 | 단일 종합 점수는 만들지 않음 |
| D019 | 구현 | provider/model 환경 선택, 시간·토큰·비용 audit | 실제 운영 비용 상한은 D036 표본으로 결정 |
| D020 | 현 단계 거절 | legacy 비교·롤백 기준선 유지 | D036 이후 제거 여부 결정 |
| D021 | 구현 | 승인된 Capability Graph closure만 공용 정답으로 소비 | 외부 graph 장애 fallback 감시 |
| D022 | 구현 | source document, verified snapshot revision/hash, job 입력 revision 분리 | 운영 key/backfill과 30일 backup lifecycle 필요 |
| D023 | 구현 | 신입 경력은 `null`, 0년으로 변환 금지 | 계약 회귀 유지 |
| D024 | 구현 | 구조 질문을 하나씩 묻고 질문·답변을 영속 복원 | 최대 질문 수 운영 관찰 |
| D025 | 구현 | canonical capability 상태와 section/context membership 분리 | 화면 하드코딩 금지 |
| D026 | 구현 | exact alias도 문장 전체 자동 매핑에 사용하지 않음 | alias 운영 감사 유지 |
| D027 | 구현 | 외부 그래프를 version/hash 검증된 read-only closure로 소비 | 쓰기/발행은 D043 bundle 경계로 분리 |
| D028 | 구현 | 회사별 프로젝트·기회·경력 관문을 하나의 사용자 career graph로 합침 | 복잡한 다직무 실데이터 E2E 필요 |
| D029 | 구현 | Spring이 job·공개 상태를 소유하고 AI stream·provider까지 취소 전파 | 프로세스 강제 종료 운영 관찰 |
| D030 | 구현 | 원자 역량은 세부 퀘스트, 프로젝트·취업·경력은 주 흐름으로 분리 | 모바일 밀도 사용자 검증 필요 |
| D031 | 구현 | 프로젝트 과제 설계 후 역량 매핑·선수 closure·사용자 gap 순서 | 모델별 품질 비교 필요 |
| D032 | 구현 | `(user, canonicalKey)` 상태와 증거 보존 | graph migration 입력이 생기면 추가 E2E 필요 |
| D033 | 구현 | scope 안 문제 생성, 부분 재시험, target context, 제출 idempotency | 난이도 정책 사용자 실험 필요 |
| D034 | 구현 | completion policy가 완료 방식을 결정 | 화면 위치 기반 완료 처리 금지 유지 |
| D035 | 부분 구현 | 개인정보 중복 전송 없는 passive paired 비교 저장·운영 UI, V3 live smoke 1회 | 실제 paired 표본 운영자 판정 필요 |
| D036 | 보류 유지 | 전환 gate와 롤백 경로 문서화 | 정확성·안정성·p50/p95·비용 표본 부족 |
| D037 | 구현 | 모든 공고 진입점에서 선택 직무·경력·원문 확인 | URL·이미지 실사이트 회귀 유지 |
| D038 | 구현 | 공고 모달 제출 즉시 닫힘, 동일한 영속 채팅 요청 1회 생성, 검토 UI 대화에 복원 | 브라우저 E2E 추가 필요 |
| D039 | 완료 | legacy 보존 감사와 수정 gate·회귀 시나리오 반영 | 새 변경마다 감사 갱신 |
| D040 | 구현 | 사용자 화면에는 provider/model 대신 JOBIS 에이전트 역할 표시 | provider/model은 운영 로그·비교함에만 허용 |
| D041 | 구현 | 사용자 취소 terminal, 자동 부활 금지, chat/analysis provider 실행 취소 | OS 강제 종료 복구 관찰 |
| D042 | 구현 | project-first graph, employment·experience min/max·기회 projection·section membership | 실제 경력 증명 정책은 추후 결정 |
| D043 | 구현 | 신규 후보 검토·감사·bundle과 외부 graph preview/import/activate/rollback | 운영 release/rollback 훈련 필요 |
| D044 | 구현 | 수정 gate 0~7과 브라우저 핵심 시나리오 회귀 반영 | 실제 사용자 표본 관찰 필요 |
| D045 | 구현 | 마감·readiness·동적 section·lease·세션·DNS·추천 오류·암호화·보존·refresh 정책 반영 | 운영 key/backfill/backup lifecycle 적용 필요 |

## 이번 전체 수정의 구현 근거

### 1. 무손실 공고 분석과 프로젝트 우선 로드맵

- AI v3가 requirement를 승인 역량 또는 검토 후보 중 하나로 반드시 남긴다.
- 회사 맞춤 프로젝트 과제를 먼저 만들고, 과제별 원자 역량과 선수 closure를 뒤에서 연결한다.
- 미등록 역량은 화면에서 사라지지 않고 `PENDING_REVIEW` 후보로 표시한다.
- 단일 회사 스택 목록이 아니라 프로젝트, 관련 취업, 경력 구간, 회사 기회를 하나의 career graph로 조립한다.
- 경력 관문은 최소·최대 기간과 관련 직무 문맥을 보존한다.
- 같은 canonical 역량은 진행 상태를 공유하되 직무·프로젝트별 사용 이유는 section membership으로 각각 표시한다.

주요 코드:

- `AI-v3/src/jobis_ai_v3/project_planning/`
- `AI-v3/src/jobis_ai_v3/normalization/`
- `AI-v3/src/jobis_ai_v3/roadmap/`
- `backend/src/main/java/com/jobiss/analysis/v3/V3RoadmapCompiler.java`
- `frontend/src/roadmap/v3-adapter.ts`
- `frontend/src/roadmap/journey.ts`

### 2. V3 목표·버전·미리보기 수명주기

- 로드맵 변경안은 명시적으로 preview한 뒤 적용하거나 취소한다.
- 목표 하나 제거와 전체 목표 초기화는 분석 기록·공용 역량·검증 증거를 삭제하지 않는다.
- 적용 버전 목록과 과거 버전 복원을 제공한다.
- 홈, 커리어 지도, 공고 삭제 참조 검사가 같은 V3 snapshot/version을 정본으로 사용한다.
- 공고 영구 삭제는 legacy뿐 아니라 V3 초안·공개 버전 참조도 검사한다.

주요 코드·DB:

- `V44__v3_roadmap_lifecycle.sql`
- `V3RoadmapService.java`, `V3RoadmapController.java`
- `CareerMapView.vue`, `HomeView.vue`, `JobPostingService.java`

### 3. 공고 source·공용 cache·취소

- source document, 사용자 확인 snapshot, 분석 job revision을 분리한다.
- 수정된 원문은 과거 완료 job을 재사용하지 않는다.
- 같은 verified posting 구조는 공용 cache/lease로 한 번 구조화하고 사용자별 적합도·로드맵은 별도로 계산한다.
- 사용자 취소와 시스템 중단을 구분하고 취소를 Spring worker에서 AI v3 provider 프로세스까지 전달한다.
- 일반 채팅 job도 취소·idempotent enqueue·quota 1회 차감을 보장한다.
- 전역 진행 배너는 `QUEUED`/`RUNNING` 작업이 실제로 있을 때만 나타나며 사용자 응답 대기는 진행 중으로 세지 않는다.

주요 코드·DB:

- `V45__v3_source_job_lifecycle.sql`
- `V46__shared_v3_posting_structure_cache.sql`
- `V3SourceService.java`, `V3AnalysisJobProcessor.java`
- `ChatReplyJobService.java`, `ChatReplyWorker.java`
- `ActivityJobService.java`, `AppShell.vue`

### 4. 커리어 저장소와 검증

- 확정된 조각의 kind·canonical identity·structured detail은 일반 수정으로 바뀌지 않는다.
- 병합 전 preview에서 kind·canonical key·수행 범위 호환성을 검사한다.
- 병합은 원본을 즉시 파괴하지 않고 archive하며 before snapshot과 undo ID를 남긴다.
- 사용자는 병합 직후 되돌릴 수 있다.
- 원자 역량 검증 문제는 `scopeDefinition`과 `excludedScope`, 현재 회사·프로젝트 문맥 안에서 생성한다.
- 진행 중 검증 중단, 부분 재시험, 제출 idempotency, 운영자 이의 검토를 유지한다.

주요 코드·DB:

- `V48__career_fragment_merge_history.sql`
- `CareerRepositoryService.java`, `CareerRepositoryController.java`
- `StorageView.vue`
- `V3AtomicAssessmentService.java`

### 5. 운영자 역량 사전

- 분석 중 발견된 신규·유사 역량 후보를 사용자 흐름과 분리해 운영 검토함에 적재한다.
- 운영자는 신규 승인, 기존 canonical 연결, 분리 필요, 보류, 반려를 선택하고 이유를 남긴다.
- 승인 후보를 versioned release bundle로 묶고 후보 snapshot과 감사 이력을 보존한다.
- 외부 `jobiss-capability-graph-lab`은 D027대로 read-only이므로, bundle 생성만으로 활성 공용 그래프가 바뀌었다고 간주하지 않는다. 외부 그래프가 해당 version과 canonical key를 실제 제공하는지 검증한 뒤 activation하는 절차가 남아 있다.

주요 코드·DB:

- `V49__operator_capability_review.sql`
- `OperatorCapabilityService.java`, `OperatorCapabilityController.java`
- `V3AnalysisJobProcessor.java`
- `OperatorView.vue`

### 6. 인증·보안·운영 설정

- 로그아웃 시 cookie만 지우지 않고 `auth_version`을 올려 기존 access token 전체를 서버에서 무효화한다.
- 이 함수는 반드시 RLS 사용자 transaction 안에서 호출한다.
- production validator는 기본/짧은 JWT·AI secret, 동일한 app/migrator DB 비밀번호, 미지원 AI mode, 개발용 저장소 암호화 키·CORS·메일 설정을 거부한다.
- URL 수집은 DNS에서 확인한 public IP에 실제 socket을 고정하고 redirect마다 재검증해 DNS rebinding을 막는다.
- RLS가 적용된 병합 이력·운영 후보·release·audit table을 추가했다.

주요 코드·DB:

- `V47__server_side_logout_revocation.sql`
- `AuthTokenVersionService.java`, `AuthController.java`
- `ProductionConfigurationValidator.java`
- `AI-v3/src/jobis_ai_v3/source/security.py`
- `AI-v3/src/jobis_ai_v3/source/http_client.py`

### 7. UI·접근성·복원

- 모든 사용자 confirm/prompt를 JOBIS 공통 dialog로 교체했다.
- 공통 dialog는 첫 focus, Tab focus trap, Escape 닫기, trigger focus 복원을 제공한다.
- sidebar current route, 고정 account 영역, 채팅 내부 스크롤, 최대 10줄 composer, 입력 draft 복원을 유지한다.
- 질문 카드·사용자 답변·진행 역할·완료/실패 결과가 새로고침 후에도 같은 대화 순서로 복원된다.
- hover 전용 삭제 버튼을 touch에서도 노출하고 최소 글자 크기·focus ring·운영자 탭 가로 스크롤을 보완했다.
- 사용하지 않는 별도 V3 지도 화면을 제거하고 기존 커리어 지도 화면에 V3 내용을 투영한다.
- `scripts/check.ps1`가 프론트 테스트 뒤 빌드까지 함께 실행한다.

주요 코드:

- `ProductDialog.vue`, `product-dialog.ts`, `App.vue`
- `AppShell.vue`, `ChatView.vue`, `CareerMapView.vue`, `StorageView.vue`, `OperatorView.vue`
- `jobis-theme.css`, `scripts/check.ps1`

## 검증 결과

2026-08-06 기준:

- Spring 전체 테스트: 통과
- legacy AI: `697 passed`
- AI v3 fixture: `40 cases`, P0 `22`, 문서화 `40` 통과
- Capability Graph: 전체 테스트 통과
- AI v3: 전체 테스트 통과
- frontend adapter 테스트: `4 passed`
- Vue TypeScript 검사와 production build: 통과
- 실제 로컬 PostgreSQL: Flyway V1~V61 적용과 격리 DB 회귀 통과
- 실제 PostgreSQL app role: refresh 회전/reuse 차단, 사용자당 분석 2개, 탈퇴 purge, 운영자 경력 승인 RLS 통과
- Playwright: 공고 URL 영속 채팅 전환과 현재 목표 저장 `2 passed`
- Codex live V3 pipeline: 1회 PASS, 61초, progress event 46개
- Docker가 없는 환경에서는 `PostgresRlsIntegrationTest`가 skip될 수 있으므로, CI에서는 Docker/Testcontainers 테스트를 반드시 실행한다.

검증 명령:

```powershell
powershell -ExecutionPolicy Bypass -File C:\jobiss-service-v3-integration-lab\scripts\check.ps1
```

## 운영 배포 전에 필요한 외부 적용·실사용 검증

1. 기존 평문 데이터 AES-GCM backfill과 운영 비밀 저장소의 key 주입·회전 감사
2. 백업 저장소의 탈퇴 데이터 최대 30일 lifecycle과 복원 훈련
3. 승인 release bundle의 외부 Capability Graph import·activation·rollback 훈련
4. 실제 사용자·공고 표본의 paired 정확성, 안정성, p50/p95, 비용과 운영자 판정
5. 위 표본을 근거로 D036의 운영 기본 provider 전환 여부 승인

정책 기본값은 D046에서 확정됐지만, 외부 인프라 적용과 실제 품질 표본은 코드만으로 대신할 수 없다. 그 전까지 운영 환경은 Legacy 기본을 유지한다. 상세 구현 기록은 `docs/21-bulk-completion-implementation-record.md`를 따른다.
