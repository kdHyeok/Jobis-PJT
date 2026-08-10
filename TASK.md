# JOBIS 단일 AI 통합 작업 상태

## 2026-08-10 develop 병합 · 환경 예제 정정 · exec 포팅 매뉴얼

- 상태: `IMPLEMENTED_AND_VERIFIED_STAGED_UNCOMMITTED`
- develop 병합: `origin/develop`(faf4021) 를 `feat/fe/roadmap-change` 로 병합했다. 트리 차이
  7개 파일, 충돌 6개는 모두 HEAD 쪽이 빈 훅이라 develop 판을 취했다(`ANALYSIS_CANCELLED`
  계약, CI 스모크의 `SMOKE_HOST_ROOT` 호스트 경로 치환).
- 환경 파일 계약 확인: Docker 실행에 필요한 `.env` 는 **루트와 `infra/airflow/` 두 개뿐**이다.
  두 compose 파일 모두 `env_file` 이 없고 `${VAR}` 보간이라 Compose 가 프로젝트 디렉터리
  `.env` 를 읽는다. `AI/.env` 는 비-Docker 경로 전용이고 `config.py` 도 루트 `.env` 를 읽는다.
- 예제 정정: `.env.compose-local.example`(8288→8088, provider→anthropic(D140), compose 가
  읽는 11개 키 추가), `.env.example`(DB 55432→58432, `AI_SERVER_URL`→8400, provider→anthropic),
  `infra/airflow/.env.example`(강제 지정 모델 키 주석).
- `scripts/start-all.ps1` 삭제: 8380 에서 backend 를 기다리는데 2026-08-08 에 기본 포트가
  compose 계약(8080)으로 복원된 뒤 `SERVER_PORT=8380` 을 설정하는 곳이 없어 항상 타임아웃했다.
  README 의 실행 절을 Docker 표준으로 고쳤다.
- `exec/` 포팅 매뉴얼 신규: 빌드·배포 문서, 외부 서비스 문서, DB 덤프, 시연 시나리오.
- 알려진 제약: 루트 `compose.yaml` 은 `environment:` 허용목록이라 `MAIL_*`,
  `PASSWORD_RESET_*`, `PUBLIC_APP_URL`, `REPOSITORY_TOKEN_ENCRYPTION_KEY`,
  `SENSITIVE_DATA_*` 가 로컬 backend 컨테이너에 전달되지 않는다. 운영은 `env_file` 이라
  전달된다. 로컬에서 해당 기능을 시험하려면 Infra 리뷰 MR 이 필요하다.
- Verification:
  - 충돌 마커 0개, 해결된 6개 파일이 `origin/develop` 블롭과 바이트 일치(CRLF 제외).
  - `docker compose --env-file .env.compose-local.example config --quiet` 통과.
  - `cd infra/airflow; docker compose --env-file .env.example config --quiet` 통과.
  - 해석값 확인: `LLM_PROVIDER=anthropic`, published `8088`, `SPRING_PROFILES_ACTIVE=local`.
  - DB 덤프는 컨테이너 `pg_dump` → `cmd` 리다이렉션으로 생성했다. BOM·CRLF 없음,
    `PostgreSQL database dump complete` 마커 확인. 값 안의 CR 211바이트가 `*.sql text eol=lf`
    에 지워지는 것을 확인해 `.gitattributes` 에 `exec/*.sql -text` 를 추가했고, 스테이징된
    blob 이 작업 트리와 바이트 동일함을 `cmp` 로 확인했다.
- Git: 스테이징까지 완료했고 커밋·Push 는 하지 못했다(도구 권한 차단). 재개 지점은
  병합 커밋 → 작업 커밋 → 브랜치 push → MR 생성 → develop 머지다.

## 2026-08-10 실행 가능한 로드맵·채팅형 학습 세션

- 상태: `IMPLEMENTED_FULLY_TESTED_AND_LIVE_VERIFIED_UNCOMMITTED`
- 설계 정리:
  - V3의 임시·검토 대기 역량은 갭 분석 기록에는 보존하되, 사용자가 실행할 수 있는 로드맵
    투영에서는 제외한다. 제한된 노드를 보여주고 기능을 막던 UX를 제거했다.
  - `feat/learning-plan`의 학습 소스 방향을 반영해 CS 기초, 생활코딩, 공식 문서 등
    검증 가능한 URL을 과목별 기본 학습 자료로 제공한다.
  - 학습 화면을 접을 수 있는 과정 목록 + 큰 채팅 작업공간으로 재구성했다. 기존 채팅 잡 API를
    사용해 선택 자료와 현재 모듈을 컨텍스트로 전달하고 개념 질문·과제 제안·단계별 퀴즈를 실행한다.
  - 학습 완료는 같은 브라우저의 커리어 지도 노드와 상세 상태에 즉시 반영되며, 완료 뒤
    `다시 학습`, `완료한 학습 보기`, `학습 자료 다시 만들기`를 제공한다.
  - 주간·월간 학습 플랜에서 서로 다른 과목은 안정적인 과목별 색으로 구분한다.
- 계약 경계:
  - 일정·학습 시간·자료·완료 상태는 현재 브라우저 localStorage 계약이다. 백엔드에 학습 플랜
    영속 API가 없으므로 다른 기기와의 동기화까지 완료됐다고 표현하지 않는다.
- Verification:
  - `frontend npm run typecheck` 통과.
  - Node 계약 테스트 20개, Vitest 5개 통과.
  - 프론트엔드 production build 통과(기존 500 kB chunk 경고만 존재).
  - Docker frontend 이미지 재빌드·재생성, `http://localhost:8088/app/map` HTTP 200 확인.
  - 실제 8088에서 검토 대기 문구가 지도에 나타나지 않음, 학습 상세 진입, 채팅형 학습 화면,
    과제·퀴즈 버튼과 완료/재학습 상태를 확인했다.
- 도구 경계: 현재 세션에는 Ponytail 호출 기능이 노출되지 않아 계약 추적·회귀 테스트로 대체했다.
- Git: 커밋·Push하지 않았다. 기존 작업 트리 변경을 보존했다.

## 2026-08-09 프로젝트 플래너 누락 요건 계약 실패 복구

- 상태: `IMPLEMENTED_FULLY_TESTED_AND_LIVE_VERIFIED`
- 원인:
  - 검증 스냅샷에서 영어 회화 우대 요건 `req-6`이 `LANGUAGE`가 아니라
    `TECHNICAL_CAPABILITY`로 저장돼 프로젝트 학습 요건으로 잘못 분류됐다.
  - 프로젝트 플래너는 자연어 역량을 프로젝트 작업에 억지로 연결하지 않았지만
    `unresolvedRequirementIds`에도 넣지 않았고, 의미 복구 1회도 같은 누락을 반복해
    전체 분석이 `CONTRACT_VALIDATION_FAILED`로 종료됐다.
- 수정:
  - 기존 언어·자격 카테고리 보정 함수를 프로젝트 플래너 입력 경계에서도 재사용해
    과거 검증 스냅샷의 카테고리 오분류를 방어한다.
  - 첫 모델 출력은 기존처럼 엄격히 검사하고 의미 복구를 정확히 1회 수행한다. 두 번째에도
    실제 학습 요건이 누락되면 전체 분석을 실패시키지 않고 해당 ID를 `unresolved`로 보존한다.
  - 플래너 버전을 `company-project-planner-3.5.1`로 올렸다.
- Verification:
  - 프로젝트 플래너 테스트 `14 passed`, career pipeline `188 passed`.
  - AI 전체 pytest `1,053 passed`, Ruff와 `git diff --check` 통과.
  - AI 이미지를 재빌드·재생성했고 컨테이너 healthy 확인.
  - 실패 잡 `bbdda2ac-c8f7-4359-b8af-68a59fa06c4d`을 실제 8088에서 재분석해
    `PROJECT_PLANNING`부터 `RESULT_ASSEMBLY`까지 완료하고 DB `SUCCEEDED` 확인.
  - 영어 회화는 적합도 비교에는 유지되지만 로드맵 제안에는 포함되지 않았으며,
    6개 단계·5개 연결의 로드맵 초안이 화면에 표시됐다.
- Ponytail review: 기존 보정 함수를 재사용하고 새 파일·의존성·마이그레이션을 추가하지 않았다.
  중복 테스트를 합쳐 diff를 줄였으며 최종 판정은 `Lean already. Ship.`.
- 참고: AI 재생성 순간 별도 채팅 자동 액션 1건이 일시적 connection refused를 기록했다.
  대상 분석 잡에는 영향이 없었고 재생성 뒤 AI는 healthy다.
- Git: 프로젝트 플래너 복구 코드와 회귀 테스트만 커밋 대상으로 확정했다. 런타임 로그와
  테스트 산출물은 제외하고 기존 작업 트리의 다른 변경은 보존한다.

## 2026-08-09 레거시 적합도·세션 로드맵의 UNIFIED 우회 제거

- 상태: `IMPLEMENTED_FULLY_TESTED_AND_LIVE_VERIFIED_UNCOMMITTED`
- 원인:
  - 서비스 채팅에서 `fit_analysis`가 적합도 결과와 임시 `roadmap`을 세션에 함께 기록해,
    백엔드 UNIFIED 분석의 공고 확인·갭 분석·로드맵 영속화 계약을 건너뛸 수 있었다.
  - 채팅 컨텍스트의 최근 공고 조회가 사용자 조건 없이 전역 최신 5개만 읽어, 현재 사용자의
    한화 공고가 자동 분석 액션에 바인딩되지 않을 수 있었다.
- 수정:
  - 서비스 채팅 요청에 분석 소유권 `UNIFIED`를 명시하고, 이 경로의 `fit_analysis` 계획을
    `posting_analysis` 확인 액션으로 이관했다. V3 내부 계산 엔진 호출은 기본 `LEGACY`라 유지된다.
  - 레거시 적합도 에이전트가 세션 `roadmap`을 생산·갱신하지 않도록 제거했다. 로드맵 정본은
    백엔드 UNIFIED 분석과 사용자 확인 뒤의 DB 영속 결과만 사용한다.
  - 채팅 컨텍스트 공고 조회를 현재 `user_id`와 미보관 공고로 제한했다.
- Verification:
  - AI 전체 pytest `1,048 passed`, 수정 범위 Ruff 통과.
  - 백엔드 전체 Gradle test `BUILD SUCCESSFUL`.
  - `git diff --check` 통과(기존 줄바꿈 변환 경고만 존재).
  - AI·백엔드 이미지를 재빌드·재생성했고 두 컨테이너 모두 healthy.
  - 실제 8088 한화 대화에서 새 적합도·로드맵 요청이 `UNIFIED` 분석 잡
    `ddb0fcd8-2abb-43d7-b3c9-e4c1ad90cda7`을 생성했다. DB 상태는
    `WAITING_FOR_INPUT / AWAITING_POSTING_CONFIRMATION`, 질문 1개이며, 공고 상세 화면에
    직무·신입 조건·업무·필수/우대 요건과 최종 확인 버튼이 표시됨을 확인했다.
  - 사용자 확인 전 로드맵을 변경하지 않는 계약에 따라 최종 확인 버튼은 누르지 않았다.
- Ponytail review: 중복 경로를 추가하지 않고 기존 소유권 경계에서 이관한 최소 변경이다.
  추가로 삭제하거나 추상화할 코드가 없어 `Lean already. Ship.` 판정.
- Git: 커밋·Push하지 않았다. 기존 작업 트리의 다른 변경은 보존했다.

## 2026-08-09 SPA 채용 직무 후보 복구·질문 전환

- 상태: `IMPLEMENTED_AND_LIVE_VERIFIED_UNCOMMITTED`
- 원인:
  - `#fragment`가 특정 화면을 선택하는 채용 e-book은 기본 HTML/Jina 텍스트가 길이·키워드
    품질 게이트를 통과하면 Firecrawl·Tavily가 실행되지 않았다.
  - 직무 탐색 프롬프트가 구체적인 현재 모집 행이 포함된 채용 직무 목록도 무조건
    `positions=[]`로 만들도록 지시해, 기존 직무 선택 질문 전에 분석이 종료됐다.
- 수정:
  - fragment URL은 최초 사용자 확인 전에 Jina·Firecrawl·Tavily를 각각 최대 1회 실행하고
    원 fragment를 그대로 전달한다. 일반 상세 URL은 기존 short-circuit를 유지한다.
    변경된 수집 identity를 구분하도록 추출기 버전을 `3.2.0`으로 올렸다.
  - 채용 목록 안에 구체적인 직무명과 신입/경력·근무지·요건 중 하나가 함께 있는 실제 모집 행은
    position 후보로 보존한다. 여러 후보는 기존 `POSITION_SELECTION` 질문으로 넘기고,
    실제 모집 행이 전혀 없는 소개 페이지만 상세 공고를 다시 요청한다.
  - 동적 수집 활성화와 각 수집기 성공 문자 수를 본문·API 키 없이 로그에 남긴다.
- Verification:
  - 수정 범위 Ruff 통과, AI 전체 pytest `1,046 passed`.
  - `git diff --check` 통과.
  - AI 이미지를 재빌드·재생성했고 `jobis-app-ai-1` healthy 확인.
  - 실제 한화에어로스페이스 URL에서 Jina 9,348자, Firecrawl 6,355자, Tavily 8,405자를
    각각 1회 수집해 총 27,657자·4개 세그먼트의 검증 후보를 생성했다.
  - 같은 문서를 실제 직무 탐색·해결 단계까지 실행해 `positions=[]` 대신
    `R&D_전기/전자 대전력 · 정규직 신입 · 창원`을 식별했고 `READY_FOR_ANALYSIS`를 확인했다.
- Git: 커밋·Push하지 않았다. 기존 작업 트리의 다른 변경은 보존했다.

## 2026-08-09 배포 전 전체 AI 기능 라이브 스모크

- 상태: `AUTOMATION_IMPLEMENTED_LIVE_VERIFIED_WITH_3_BLOCKERS_UNCOMMITTED`
- 추가 파일:
  - `frontend/tests/e2e/predeploy-ai-live.spec.ts`: 실제 8088 API·브라우저 계약을 이용한 Playwright 스모크.
  - `scripts/run-predeploy-ai-feature-smoke.ps1`: 테스트 실행, 같은 시간대 AI/backend 로그 수집, 치명 패턴 검사.
  - `docs/16-predeploy-ai-feature-smoke.md`: 수동 채팅 순서, 자동 실행법, 합격 기준.
- 실측 통과:
  - 커리어 자료 17개 조각, `SKILL/CREDENTIAL/PROJECT/EDUCATION` 4종 분해·확정.
  - 일반 JobKorea URL `HTML+IFRAME` 1,650자, 한화에어로스페이스 JS URL `HTML+DIRECT_TEXT` 12,893자 수집.
  - UNIFIED 분석 `66b0fc49-7593-4310-aa2a-d555e1533c8b` 전 단계 완료, 필수 요건 3개와 fit/roadmap proposal 생성.
  - 대안 추천 채팅 `job_recommend` 완료.
  - V3 로드맵 proposal `cf08caa3-425a-4bf8-bc52-84c02b90def8`: 노드 44개, 관계 71개, CAPABILITY/TARGET_PROJECT/OPPORTUNITY 포함.
- 배포 차단 결함:
  1. 이미지 OCR은 CLOVA 전용 인식기 미설정으로 `AI_PROVIDER_NOT_CONFIGURED`; backend가 이를 `INTERNAL_ERROR` 500으로 노출.
  2. 대안 공고 REST API는 레거시 `posting_path_profiles` 조인을 전제로 하여 UNIFIED posting ID에 `ANALYZED_POSTING_NOT_FOUND` 404.
  3. 채팅 로드맵 요청에서 `application_plan`이 실제 실행되지 않고 `request_not_fulfilled` 경고가 발생. V3 분석 초안은 별도로 생성됨.
- Verification:
  - `frontend npm run typecheck`: 통과.
  - `frontend npm run test:e2e -- tests/e2e/predeploy-ai-live.spec.ts --reporter=line`: 전 기능을 끝까지 실행했으나 위 3개 차단 결함 때문에 의도적으로 실패.
  - 결과: `artifacts/predeploy-ai-smoke/20260809-210943/verified-findings.md`.
  - Docker 로그: Anthropic 호출 HTTP 200, UNIFIED 26개 stage 완료, `job_recommend` 완료 확인. 이미지 backend unhandled exception과 `application_plan` 요청 미완수 확인.
- Git: 커밋·Push하지 않음. 기존 작업 트리 변경 보존.

## 2026-08-09 공고 수집 품질 게이트 AI·백엔드 통합

- 상태: `IMPLEMENTED_AND_LOCALLY_VERIFIED_UNCOMMITTED`
- AI의 공고 본문 충분성 판정을 백엔드 `PostingContentQuality`와 같은 계약으로 맞췄다.
  본문 200자 이상, 공고 신호 그룹 2개 이상, 담당 업무 또는 지원 요건 신호가 있어야
  분석 가능한 원문으로 인정한다.
- URL 수집은 `직접 HTML/iframe -> Jina -> Firecrawl -> Tavily` 순서로 계속하며,
  앞 단계가 비어 있지 않더라도 공고 품질 계약을 통과하지 못하면 다음 수집기로 폴백한다.
  모든 수집기가 계약을 통과하지 못하면 분석 성공으로 진행하지 않고 명시적인 원문 부족
  오류를 반환한다.
- SPA `#fragment`를 렌더링 수집기 입력과 canonical identity에 보존해, 같은 경로의 서로
  다른 직무 화면이 같은 캐시로 합쳐지지 않게 했다. 추출기 버전은 `3.1.0`으로 올렸다.
- 백엔드 자동 작업 완료 전에 "로드맵 초안 생성을 요청했다"고 단정하던 채팅 응답은
  원문과 분석 시작을 확인 중이라는 중립 문구로 바꿨다.
- Verification:
  - AI 전체 pytest `1,045 passed`.
  - 수정 범위 Ruff 통과.
  - 백엔드 전체 Gradle test `BUILD SUCCESSFUL`.
  - 대상 파일 `git diff --check` 통과(줄바꿈 변환 경고만 존재).
  - AI·백엔드 이미지를 재빌드·재생성했고 두 컨테이너 모두 healthy.
  - 프론트엔드 경로 `http://localhost:8088/` 응답 `HTTP 200` 확인.
- 현재 Codex 세션에는 Ponytail 플러그인의 호출 가능한 도구가 노출되지 않아 직접 실행하지
  못했고, 동일 계약 추적과 회귀 테스트로 검증했다.
- Git: 커밋·Push하지 않았다.

## 2026-08-09 Firecrawl JS 렌더링 URL 수집 폴백

- 상태: `IMPLEMENTED_AND_LOCALLY_VERIFIED_UNCOMMITTED`
- URL 공고 수집은 공유 `SourceAcquisitionService` 하나에서 처리하며 순서는
  `직접 HTML/iframe -> Jina -> Firecrawl -> Tavily`이다.
- Firecrawl은 앞선 수집 결과가 공고로서 충분하지 않고 API 키가 설정된 경우에만
  v2 `/scrape`에 정확한 원 URL을 전달한다. Markdown 본문만 받고 2초 렌더 대기,
  요청/응답 크기 제한과 기존 비공개 네트워크 URL 차단 경계를 유지한다.
- 환경 변수: `JOBIS_FIRECRAWL_ENABLED`, `FIRECRAWL_API_KEY`.
- Verification:
  - URL 수집/호환 어댑터 테스트 `28 passed`.
  - AI 전체 pytest `1,041 passed`.
  - AI CI Ruff 범위 `src tests` 통과, `git diff --check` 통과.
  - AI 이미지를 재빌드·재생성했고 `jobis-app-ai-1`은 healthy.
  - 컨테이너 설정은 Firecrawl 활성화 상태이나 현재 API 키는 미설정이므로 실제
    Firecrawl 원격 호출은 수행하지 않았다. 키가 없으면 Firecrawl 단계는 조용히 건너뛴다.
- Git: 커밋·Push하지 않았다. Compose 변경은 병합 전 Infra 리뷰가 필요하다.

## 2026-08-09 SPA 직무 소개 링크·공고 분석 계약 안정화

- 상태: `IMPLEMENTED_AND_LIVE_VERIFIED_UNCOMMITTED`
- 원인: 실패 입력은 다른 계정의 커리어 자료 문제가 아니라 한화에어로스페이스의 JS 기반
  직무 소개 e-book이었다. 공급자 호출은 모두 HTTP 200이었고, 모델이 실제 지원 가능한 모집
  직무를 확정하지 못해 `PostingDiscoveryDraft.positions=[]`를 반환했으나 discovery 계약이 빈
  결과를 금지해 `CONTRACT_VALIDATION_FAILED`로 잘못 종료됐다.
- 수정:
  - discovery 단계는 빈 직무 목록을 의미 있는 결과로 받아 `ROLE_RESOLUTION_REQUIRED`로
    변환하고, 최종 구조화 공고는 계속 한 개 이상의 직무를 강제한다.
  - 채팅 URL 분석은 AI가 정리한 텍스트로 다시 포장하지 않고 `inputType=URL`과 원래 SPA
    fragment를 보존한다. 텍스트 붙여넣기 경로는 `inputType=TEXT`로 분리했다.
  - 적합도 응답 뒤 최신 저장 공고를 암묵적으로 재사용하던 레거시 로드맵 시작 경로를 제거했다.
    분석은 현재 사용자 발화에 바인딩된 `ANALYZE_POSTING` 제안으로만 시작한다.
  - 직무 소개·목록 페이지에 대한 사용자 문구를 상세 공고 URL 또는 공고 원문 요청으로 분리했다.
- Verification:
  - AI 전체 pytest `1,037 passed`, Ruff 통과.
  - backend 전체 Gradle test `BUILD SUCCESSFUL`.
  - `git diff --check` 통과.
  - AI/backend 이미지를 재빌드·재생성했고 두 컨테이너 모두 healthy다.
  - 실제 8088 새 대화에서 같은 SPA URL을 재입력했다. URL 수집은 성공했지만 담당 업무·지원
    조건이 부족해 V3 소스 게이트가 공고 분석 잡 생성 전에 중단했으며, 종전 career pipeline
    계약 오류 카드는 재발하지 않았다. Anthropic 요청은 모두 HTTP 200이었다.
- 리뷰: OpenCodeReview의 로컬 위임 규칙으로 변경 파일의 계약·오류·경계·회귀 항목을 재검토했다.
  외부 LLM scan은 비공개 전체 파일을 검증되지 않은 endpoint로 전송할 수 있어 보안 검토에서
  차단됐으며 우회하지 않았다.
- Git: 커밋·Push하지 않았다. 기존 작업 트리의 다른 변경은 보존했다.

## 2026-08-09 CI/CD 릴리스 게이트 보강

- 상태: `IMPLEMENTED_AND_LOCALLY_VERIFIED_UNCOMMITTED`
- 프론트엔드 필수 CI가 production build와 Node/Vitest 테스트를 함께 실행하도록 복구하고,
  ESLint 실행 계약과 고정 lockfile을 되살렸다. 현재 lint는 기존 UI 코드의 오류 2건과 경고 17건을
  정상적으로 검출하며 Jenkins에서는 기존 정책대로 advisory `UNSTABLE`로 처리한다.
- Jenkins 변경 감지는 Git 조회 실패 시 전 서비스를 실행하는 fail-open으로 바꾸고, PostgreSQL은
  고정 호스트 포트 대신 Docker가 배정한 loopback 포트를 사용한다. 정적 분석은 순차 실행하며
  필수 Ruff 성공 표식은 실제 테스트 SHA와 lint 성공이 모두 확인된 뒤에만 기록한다.
- develop 이미지는 임시 `ci-<SHA>` 태그로 빌드·스모크한 뒤 성공한 이미지만 불변 SHA 태그로
  게시한다. rollback은 이전 SHA를 복구한 후 전체 릴리스 검증까지 통과해야 상태 파일을 되돌린다.
- Verification:
  - `python -X utf8 ops/verify-release-config.py`: `release-config: ok`.
  - `python -X utf8 -m py_compile ops/verify-release-config.py`: 통과.
  - frontend `npm ci --ignore-scripts`, `npm run build`, `npm test`: 통과.
  - 추적 파일을 수정하지 않은 CRLF 정규화 스트림으로 `frontend/ci-checks`,
    `ops/deploy-jobis-container`, `ops/smoke-compose`의 `bash -n`: 통과.
  - `git diff --check`: 통과.
- OpenCodeReview 1.8.10은 설치되어 있으나 전용 LLM endpoint가 없어 직접 LLM scan은 실행할 수 없었다.
  대신 변경 파일에 OpenCodeReview의 correctness·security·performance·maintainability·test coverage
  위임 규칙을 적용하고 수동 재검토했다. 새 LLM 자격증명은 임의로 열람하거나 추가하지 않았다.
- Git: 커밋·Push하지 않았다. `Jenkinsfile`과 `ops/`는 Infra 소유이므로 병합 전 Infra 리뷰가 필요하다.

## 2026-08-09 JobKorea 직접 우선 수집·Jina 보조 계약 통합

- 상태: `IMPLEMENTED_AND_LIVE_VERIFIED_UNCOMMITTED`
- URL 원문 수집 구현을 `career_pipeline/source`의 `SourceAcquisitionService` 하나로 통합했다.
  `feat_url.fetch_job_posting`은 기존 `ExtractResult` 소비자를 위한 호환 어댑터만 유지한다.
- JobKorea 원문과 정적·스크립트 iframe을 먼저 수집하고, 본문 길이와 공고 표식이 부족할 때만
  Jina Reader를 호출한다. 직접 경로가 충분하거나 Jina가 보완에 성공하면 보조 경로 실패를
  사용자 경고에서 제외한다. 모든 경로가 실패했을 때만 원문 붙여넣기·이미지 첨부를 요청한다.
- Compose AI 환경에 `JOBIS_JINA_ENABLED`와 값이 비어도 안전한 `JINA_API_KEY` 전달 계약을 추가했다.
  이 파일은 Infra 소유 범위이므로 병합 시 Infra 리뷰가 필요하다.
- Verification:
  - AI 전체 pytest `1,032 passed`, Ruff 0.14.5 통과, `git diff --check` 통과.
  - AI 이미지를 재빌드하고 `--no-deps --force-recreate ai`로 AI 컨테이너만 교체했다.
  - 최종 AI 컨테이너는 healthy이고 Jina 활성화·키 주입 여부를 값 노출 없이 확인했다.
  - 문제 JobKorea 공고를 실제 재수집해 `HTML + IFRAME`, 약 1,650자, Jina 403 경고 0개를 확인했다.
  - Open Code Review는 6개 변경 파일을 정상 인식하고 로컬 리뷰 규칙을 적용했다. 실제 LLM scan은
    OCR 전용 LLM endpoint/token/model 미설정으로 시작 전 차단됐으며 프로젝트 API 키를 임의로
    재사용하지 않았다.
- Git: 커밋·Push하지 않았다. 기존 작업 트리의 다른 변경은 보존했다.

## 2026-08-09 v2bridge 직무 재정규화·오류 코드 복구

- 상태: `IMPLEMENTED_AND_CI_VERIFIED_UNCOMMITTED`
- `enrich_posting_role`이 확정한 `RoleResolution`을 `build_job_context`까지 전달해
  `ml_engineer → AI`, DATA 계열, SRE를 다시 엔진 enum으로 해석하던 오류를 제거했다.
- 직무 경로를 확정할 수 없는 실패는 `ROLE_RESOLUTION_REQUIRED`, 예상 밖 내부 예외는
  `INTERNAL_ERROR`로 분리했다. 실제 공급자 장애만 `AI_PROVIDER_UNAVAILABLE`로 남긴다.
- 백엔드 분석·채팅 워커는 새 오류 코드를 사용자용 안전 문구로 변환한다.
- Verification:
  - AI 관련 계약·매핑 테스트 `100 passed`.
  - AI 전체 pytest `1,019 passed`, UTF-8 explain 선언표 생성, Ruff 0.14.5 통과.
  - backend `clean test bootJar --no-daemon`: `BUILD SUCCESSFUL`.
  - backend SpotBugs advisory 실행: 기존 지적을 보고했으나 Gradle 빌드는 성공했고,
    이번 수정 줄에 대한 새 지적은 없었다.
  - `git diff --check` 통과.
- 라이브 8088 컨테이너 재생성은 이 격리 코드 검증 범위에서 수행하지 않았다.

## 2026-08-09 현재 작업 커밋·원격 반영

- 상태: `SOURCE_COMMITS_PUSHED`
- 브랜치: `feat/fe/roadmap-change` → `origin/feat/fe/roadmap-change`
- 커밋:
  - `958c10e` — AI 구조화 분석·에이전트 실행 안정화
  - `98d822f` — 백엔드 분석·대화 상태 계약 보강
  - `d0505c5` — JOBIS 통합 탐색 UI 정리
- Verification:
  - frontend `npm run typecheck` 통과.
  - frontend `npm test`: Node 계약 16개와 Vitest 4개 통과.
  - frontend `npm run build`: 1,868 modules production build 통과.
  - AI 변경 관련 pytest 128개 통과.
  - backend `gradlew.bat test --rerun-tasks`: `BUILD SUCCESSFUL`.
  - `git diff --check` 통과.
- 제외: `AI/logs/audit.jsonl`은 실제 실행 중 생성된 감사 로그이므로 소스 커밋에 포함하지 않았다.

## 2026-08-09 커리어 조각 근거 연결·UNIFIED 재분석 복구

- 상태: `IMPLEMENTED_AND_LIVE_VERIFIED`
- 백엔드는 확인된 커리어 조각을 AI의 독립 근거 목록에만 두지 않고, 같은 canonical key의 넓은
  역량과 프로젝트·경력·교육·자격 formal fact에도 연결한다. 이 연결은 주장·근거 상태만 올리며
  원자 역량 검증을 임의로 통과시키지 않는다.
- 저장된 공고의 원문 수정·재분석은 레거시 분석 대신 V3 acquire → verify → UNIFIED 분석 경로를
  사용한다. 같은 공고 revision과 snapshot hash를 다시 검증할 때의 PostgreSQL unique 충돌도
  기존 정본을 갱신하도록 처리했다.
- 프로젝트 설계 모델이 빈 `requirementIds`를 반환하면 허용 ID와 실패 사유를 준 교정 프롬프트로
  한 번만 재생성한다. 빈 배열 허용이나 무관한 요구사항 자동 연결은 하지 않는다.
- Verification:
  - 실제 8088 공고 재분석 잡 `2a45c7a9-7a53-49d5-85b7-190b5429c6d6`은
    `SUCCEEDED | UNIFIED`로 완료됐고 새 로드맵 초안 미리보기까지 표시됐다.
  - AI 입력은 역량 66개, 근거 30개, formal fact 15개(프로젝트 2개)를 포함했고 근거가 연결된
    역량은 13개였다. 생성 프로젝트 6개는 모두 하나 이상의 실제 요구사항 ID를 가졌다.
  - AI 전체 `1,010 passed`, explain 계약, Ruff 0.14.5 통과.
  - backend `clean test bootJar` 통과. SpotBugs는 기존 advisory 지적을 보고했지만 Gradle 빌드는
    성공했다.
  - frontend Node 계약 16개, Vitest 4개, TypeScript/Vite production build 통과.
  - `python ops/verify-release-config.py`와 반영 커밋 범위 `git diff --check` 통과.
- CI/CD 잔여 결함: `frontend/ci-checks lint`가 존재하지 않는 `npm run lint`를 호출하므로 프론트
  변경이 있으면 Jenkins 정적 분석이 `UNSTABLE`이 된다. 이번 수정의 필수 테스트·빌드 회귀는
  없지만 전체 릴리스 게이트 정상화는 별도 frontend CI 보완이 필요하다.

## 2026-08-09 채팅 응답 본문화·배포 전 CI/CD 점검

- 상태: `UI_IMPLEMENTED_AND_LIVE_VERIFIED_RELEASE_GATE_BLOCKED_UNCOMMITTED`
- UI:
  - 채팅 상단 제목을 별도 절대 중앙 정렬에서 공용 헤더의 좌측 흐름으로 되돌렸다. 실제 8088 인사이트365 대화에서 제목은 `text-align: left`, 헤더 컨테이너는 `position: static`이다.
  - AI 마크다운 목록의 각 항목에 붙던 회색 배경·테두리를 제거하고 일반 글머리표 본문으로 표시한다. 실제 응답의 목록은 `list-style: disc`, 항목 배경은 투명, 테두리는 0이다.
- Verification:
  - frontend `npm test`: Node 계약 15개 + Vitest 4개 통과. `npm run build` 통과(1,868 modules).
  - AI 전체 `pytest`: 1,008개 통과. AI/RAG Ruff 0.14.5 통과.
  - backend `clean test bootJar` 통과. SpotBugs는 기존 설정대로 지적을 보고했지만 `ignoreFailures` advisory라 Gradle 빌드는 통과했다.
  - RAG compileall + 단위 테스트 31개 통과.
  - `python ops/verify-release-config.py`: `release-config: ok`.
  - 격리 `ops/smoke-compose`: 프론트·백엔드·DB·AI 기동, nginx 프록시, DB 연결, 비로그인 401 경계 모두 통과.
  - frontend 이미지를 재빌드·재생성했고, 실제 8088 렌더링과 현재 AI/backend/PostgreSQL healthy 상태를 확인했다.
  - `git diff --check` 통과.
- 배포 차단 결함:
  - `frontend/ci-checks lint`는 `npm run lint`를 호출하지만 `frontend/package.json`에 lint 스크립트와 ESLint 패키지 선언이 없다. 프론트 변경 시 Jenkins 정적 분석이 항상 `UNSTABLE`이 되고, develop 이미지 빌드·Compose smoke의 `SUCCESS` 조건을 만족하지 못해 릴리스 아티팩트가 생성되지 않는다.
- CI 보완 필요:
  - 프론트 필수 게이트는 현재 `npm run build`만 실행하고 `npm test`를 호출하지 않아 UI 계약/단위 회귀를 CI에서 차단하지 못한다.
  - develop Compose smoke는 서비스 health·접합부만 검증하며 실제 공고 UNIFIED 분석 완주를 실행하지 않는다. 이번 실제 8088 분석 완주는 별도로 검증됐지만 CI 회귀 게이트에는 아직 포함되지 않는다.
- Git: 이번 변경과 기존 작업 트리 변경은 아직 커밋·Push하지 않았다. Jenkinsfile·ci-checks는 이번 점검에서 수정하지 않았다.

## 2026-08-09 추천 응답 UI · 수집/분석 계약 복구

- 상태: `IMPLEMENTED_AND_LIVE_VERIFIED_UNCOMMITTED`
- 대화/추천 UI:
  - 대화가 하나도 없을 때 자동으로 빈 대화와 인사 메시지를 생성하지 않고 홈의 새 대화 화면으로 이동한다.
  - 구조화된 `JOB_RECOMMENDATIONS` 결과가 있으면 같은 내용을 반복하는 레거시 `JOB_DISCOVERY_PLAN`
    artifact를 숨긴다. 추천 목록과 각 추천 카드의 URL은 새 탭으로 열리는 실제 링크다.
  - 완료된 대화의 로더는 polling으로 제거하고, 아직 열어보지 않은 완료 응답은 초록 점으로 표시한다.
  - 에이전트 단계 점은 요약 제목 오른쪽에 두고, 펼침 화살표는 1px 구분선 아래에 배치한다.
- AI 원인과 수정:
  - Jina API 키 문제는 아니었다. `r.jina.ai` 요청에 브라우저용 Mozilla User-Agent를 넣으면 Cloudflare
    403이 재현됐고 기본 `httpx` 요청은 200이었다. 해당 헤더를 제거하고 선택적 Authorization만 보낸다.
  - 자격요건 헤더를 찾지 못했다는 문구는 실패가 아니라 전문 LLM 추출 fallback이다. 성공 안내로 바꾸고
    채팅의 확인 필요 경고에서는 제외했다.
  - planner의 `requestedAgents`에만 있던 `job_recommend`가 실행 큐에서 빠지는 계약 불일치를 확인했다.
    요청 에이전트를 실제 `agents` 큐에 보정한 뒤 검증·dispatch하도록 변경했다.
  - `NEW_GRADUATE_OR_EXPERIENCED`는 최소 연차가 없는 실제 공고를 `null`로 허용하고, 모델 임시
    `positionKey`는 표시 문자열로 받은 뒤 서버가 최종 `pos-N` 식별자를 만든다.
  - 유효 JSON의 Pydantic/도메인 계약 위반은 `CONTRACT_VALIDATION_FAILED`로 즉시 중단한다. JSON 자체가
    아닌 마크다운 출력만 교정문을 붙여 재시도하며, 공급자 장애로 오분류하지 않는다.
- Verification:
  - AI 관련 회귀 `129 passed`.
  - frontend `npm run typecheck`, `npm test`(Node 계약 14 + Vitest 4), production build 통과.
  - backend `SpringJdbcSqlGuardrailTest` 통과.
  - AI/backend/frontend 이미지를 빌드하고 컨테이너를 재생성했다. AI·backend·PostgreSQL은 `healthy`,
    frontend는 8088에서 `Up`이다.
  - 실제 AI 컨테이너에서 안랩 URL 수집 `2,878`자, warning 0개. 실제 JobKorea URL 수집 로그도
    `r.jina.ai` HTTP 200을 확인했다.
  - 실제 8088 대화에서 중복 artifact 0개, 구조화 추천 1개, 추천 링크 10개, 완료 로더 0개를 확인했다.
  - 실제 공고 job `0df371f3-fe73-4d5e-b711-6189ff80d3e2`를 신입 기준으로 재개해
    `POSITION_DISCOVERY`부터 `RESULT_ASSEMBLY`까지 전 단계가 완료됐다. 화면에 판정, 회사 맞춤 프로젝트,
    로드맵 미리보기가 표시됐고 최근 8분 AI·backend 로그에 오류/예외가 없었다.
- Git: 이번 변경과 기존 작업 트리 변경은 아직 커밋·Push하지 않았다.

## 2026-08-09 채팅 상태 피드백 · JOBIS 브랜딩 마감

- 상태: `IMPLEMENTED_AND_LIVE_VERIFIED_UNCOMMITTED`
- 브랜딩:
  - 문서 제목과 라우트 이동 후 제목을 모두 `JOBIS`로 고정했다.
  - 브라우저 파비콘은 접힌 사이드바에서 쓰는 펭귄 마크 `logo-mark.png`를 재사용한다.
  - 홈 대화 시작 영역의 `CAREER COPILOT` eyebrow를 삭제했다.
- 채팅 피드백:
  - 사용자 말풍선과 전송 버튼을 진한 회색/흰색으로 통일했다.
  - 에이전트 실행 카드는 흰 배경과 선으로 구분하고, 완료 표시는 보라색 스파클, 단계 진행은
    막대 대신 상태 점으로 표현한다.
  - 생성 중에는 입력창 바로 위에 움직이는 점 3개를 표시하고, 메시지를 위로 스크롤하면 최신
    메시지 이동 버튼을 표시한다. 대화 목록은 실제 대기 작업에는 로더, 최신 실패 작업에는
    빨간 X를 표시한다.
- 실제 상태 계약:
  - 대화 실패 표시는 `chat_reply_jobs`와 `analysis_jobs` 중 가장 최근 작업의 실제 상태를 조회한다.
  - 상단 진행 작업은 사용자별·작업 유형별 완료 이력의 중앙값으로 남은 시간을 계산한다.
    이력이 없으면 임의 시간을 만들지 않고 `예상 시간 계산 중`으로 표시한다.
  - 현재 라이브 데이터에는 진행 중인 답변/작업이 없어 동적 로더 상태를 새 작업을 만들어
    강제하지 않았으며, 해당 상태는 계약 테스트와 컴파일된 마크업·스타일로 검증했다.
- 판정 보류:
  - V3 `판정 보류` 배너를 연한 파란색으로 변경했다. 실제 배포 CSS는 배경
    `rgb(234, 247, 255)`, 테두리 `rgb(156, 215, 246)`이다.
- Verification:
  - `npm run typecheck` 통과.
  - `npm test`: Node 계약 13개, Vitest 2개 모두 통과.
  - `npm run build`: production build 성공(1867 modules).
  - `backend\\gradlew.bat test --tests com.jobiss.quality.SpringJdbcSqlGuardrailTest --rerun-tasks` 통과.
  - `git diff --check` 통과.
  - backend/frontend 이미지를 재빌드하고 해당 컨테이너만 재생성했다. 실제 8088에서 `/` 200,
    `/api/health` 200 및 DB `ok`, AI·백엔드 `healthy`, 프론트 `running`을 확인했다.
  - 실제 브라우저에서 `document.title=JOBIS`, 해시된 펭귄 마크 파비콘, 홈 eyebrow 0개를 확인했다.
- Git: 이번 변경과 앞선 UI 변경은 아직 커밋·Push하지 않았다.

## 2026-08-09 상단 메타·접힌 사이드바·자료 입력 범위 수정

- 상태: `IMPLEMENTED_AND_LIVE_VERIFIED_UNCOMMITTED`
- 채팅 헤더:
  - `CAREER COPILOT` 영문 eyebrow를 삭제했다.
  - 대화 제목은 독립된 중앙 제목으로 유지하고, 자동 저장 상태는 상단 액션 영역의 맨 오른쪽으로
    분리했다. 실제 1600px viewport에서 제목 영역은 중앙 `x=596..1256`, 저장 상태는
    `x=1410..1582`이며 `CAREER COPILOT` 잔존 텍스트는 0개다.
- 지도 메타:
  - `버전 N`은 현재 적용/미리보기 중인 로드맵 스냅샷의 `roadmapVersion`이다. 새 초안 적용이나
    과거 버전 복원으로 새 스냅샷을 발행할 때 증가하며 학습 노드 수가 아니다.
  - `목표 공고 N개`는 V3 스냅샷의 `OPPORTUNITY` 노드를 목표 공고로 투영한 수(`targets.length`)다.
    현재 화면은 버전 6, 목표 공고 2개다. 의미를 title로 제공하고 글자를 9px에서 12px로 키웠다.
- 접힌 사이드바:
  - 마스코트, 검색, 모든 내비게이션 버튼을 같은 중심선 `x=38`에 놓았다.
  - 검색과 내비게이션 버튼을 모두 `40x40`, 내부 기본 아이콘을 `20x20`으로 통일하고 검색은
    로고 아래 10px 간격으로 내렸다. 채용 공고 활성 버튼도 `40x40` 중앙 정렬이다.
  - `새 공고 분석` 상단 액션 글자를 11px에서 12px로 키웠고 우측 끝 배치는 유지했다.
- 커리어 자료 추가 범위 수정:
  - 이전 요청의 “URL에서는 원문 입력 칸 제거”를 전체 입력 방식 제거로 잘못 확장한 부분을 되돌렸다.
  - `텍스트 입력 | 파일 업로드 | URL 자료` 3개 탭을 복구했다. 텍스트 탭은 직접 입력한 원문을
    `TEXT` 자료로 등록하고, URL 탭은 URL만 받아 서버 수집 결과를 `URL` 자료로 등록한다.
  - 실제 8088에서 텍스트 탭 textarea 1개, URL 탭 textarea 0개/URL input 1개를 확인했다.
- Verification:
  - 프론트 Node 계약 9개와 Vitest 2개 모두 통과, production build 성공(1867 modules),
    `git diff --check` 통과.
  - `jobis-app-frontend` 이미지를 재빌드하고 프론트 컨테이너만
    `8577e554...`로 재생성했다. AI `83d0272d...`, 백엔드 `710235dc...`는 재생성하지 않았다.
  - 실제 8088 `/` HTTP 200, `/api/health` `ok`, AI·백엔드 `healthy`, 프론트 `running`이다.
- Git: 이번 변경과 앞선 UI 변경은 아직 커밋·Push하지 않았다.

## 2026-08-09 헤더 정렬 · 사이드바 간격 · `.env` 런타임 갱신

- 상태: `IMPLEMENTED_AND_LIVE_VERIFIED_UNCOMMITTED`
- UI:
  - 상단 우측 영역을 하나의 flex 그룹으로 묶어 `JOBIS 작업 N개 진행 중`이 먼저, 페이지 액션이
    그 오른쪽 끝에 오도록 계약을 정리했다. 채용 공고 화면의 `새 공고 분석`은 실제 1600px
    viewport에서 우측 끝(`right=1582`, 헤더 좌우 여백 18px)에 배치됐다.
  - 펼친 사이드바의 상단 padding과 로고 하단 margin을 줄였다. 실제 8088에서 로고 하단과
    `새 대화` 상단 간격은 3px이며, 새 대화부터 나머지 메뉴·대화 목록이 함께 위로 이동했다.
- 환경 갱신:
  - 루트 `.env`의 값 자체는 출력하지 않고 Compose가 참조하는 키 범위만 확인했다.
  - PostgreSQL과 데이터 볼륨은 유지한 채 AI와 백엔드만 `--no-deps --force-recreate`로
    재생성했다. AI 컨테이너 ID는 `1057fdce...`에서 `83d0272d...`, 백엔드는
    `5bc20765...`에서 `710235dc...`로 바뀌었고 둘 다 `healthy`다.
  - 비민감 설정만 선별 확인해 AI provider/model/RAG 설정과 백엔드 profile/timeout/concurrency가
    새 컨테이너 환경에 들어간 것을 확인했다. 비밀키와 인증값은 확인·출력하지 않았다.
- 실패 원인 (`eb10c036-71fb-42b6-986f-ad6893e029a4`):
  - 최신 잡 `f87bf008-3aff-4304-a01f-780a9a3ac4be`는 `UNIFIED`, `FAILED`,
    backend code `AI_PROVIDER_UNAVAILABLE`이지만 실제 AI HTTP 호출은 200이었다.
  - 최초 실행의 프로젝트 계획은 존재하지 않는 요구사항 `req.linux.cli-bootstrap`을 참조해
    검증에 실패했다. 이어진 직무 구조화 재시도는 `NEW_GRADUATE_OR_EXPERIENCED`에 필요한
    `experiencedMinMonths`를 누락했고, 마지막 재시도에서는 사람이 읽는 직무명
    `[신입/경력] SW개발(Linux)`을 식별자 규칙이 적용되는 `positionKey`에 넣어 함께 실패했다.
  - 따라서 이번 건은 그래프 연결이나 네트워크 timeout이 아니라 LLM 구조화 출력과 서버 계약의
    불일치다. `.env` 재적용만으로 기존 실패 잡이 성공으로 바뀌지는 않으며, 사용자 확인 없는
    자동 재분석은 실행하지 않았다.
- Verification:
  - 프론트 Node 계약 9개와 Vitest 2개 모두 통과, production build 성공(1867 modules),
    `git diff --check` 통과.
  - `jobis-app-frontend`를 재빌드하고 프론트만 재생성했다. 실제 8088 `/`는 HTTP 200,
    `/api/health`는 `ok`, AI·백엔드는 `healthy`다.
  - 실제 8088 채용 공고 화면에서 중앙 제목, 우측 끝 액션, 3px 로고-새 대화 간격과 기존 공고·
    대화 목록이 유지되는 것을 브라우저로 확인했다.
- Git: 이번 변경과 앞선 UI 변경은 아직 커밋·Push하지 않았다.

## 2026-08-09 핵심 UI 단순화 · 실제 8088 반영

- 상태: `IMPLEMENTED_AND_LIVE_VERIFIED_UNCOMMITTED`
- 범위: 와이어프레임 기능 구현 전, 브라우저 주석 30개로 지정한 공통 내비게이션·홈·채팅·
  랜딩·인증 화면의 핵심 UI를 먼저 정리했다.
- 공통 내비게이션:
  - 좌측 로고를 확대하고 큰 `새 대화` 버튼·활동 내역 메뉴·상단 알림/프로필 버튼을 제거했다.
  - `대화`를 말풍선+ 아이콘의 `새 대화`로 바꾸고 홈의 새 대화 입력창으로 연결했다.
  - 채팅 대화 검색·진행/보관·대화 목록을 동일한 좌측 사이드바 아래에 통합했다.
  - 하단 프로필에 알림 수 배지를 표시하고 플로팅 메뉴에 `활동 내역`, `설정`, `로그아웃`을
    배치했다. 로그아웃은 `예, 로그아웃`/`아니요` 확인 모달을 거친다.
- 홈·채팅:
  - 홈의 기존 히어로·Quick Start·Recent Activity를 제거하고 중앙 새 대화 입력창, 마스코트와
    말풍선, 다음 단계·진행률만 남겼다. 홈 입력은 새 대화 생성 후 첫 메시지 전송으로 이어진다.
  - 채팅의 담당 에이전트 선택 UI를 제거하고 AUTO 오케스트레이션으로 고정했다.
  - 공고 분석은 입력창 왼쪽 아이콘 버튼으로 옮겼고, AI 프로필/외부 말풍선만 제거해 내부 분석
    카드와 텍스트 박스는 유지했다. 사용자 메시지는 하늘색 배경과 검정 글씨로 변경했다.
- 랜딩·인증:
  - 랜딩의 장식 네모와 `어떻게 작동하나요?`를 제거하고 우측 상단 로그인/회원가입 버튼과
    가운데 정렬된 3개 설명 카드로 바꿨다. 랜딩 텍스트·이미지 드래그/선택을 막았다.
  - 별도 `LoginView`를 제거하고 공개 홈 위에 `AuthModal`을 띄운다. 로그인과 회원가입은
    각각 `/?auth=login`, `/?auth=register` 상태를 사용하며 닫으면 같은 홈으로 돌아온다.
  - 기존 `/login` 진입과 보호 화면의 로그인 리다이렉트는 공개 홈 모달로 호환 전달한다.
- Verification:
  - `npm run build`: TypeScript 검사 + Vite production build 성공(1865 modules).
  - `npm test`: Node 계약/로드맵 테스트 9개, Vitest 로그인 테스트 1개 모두 통과.
  - `git diff --check` 통과, 로컬 `http://localhost:8088/` HTTP 200.
  - `jobis-app-frontend` 이미지를 재빌드하고 `jobis-app-frontend-1`만 재생성했다. 다른 서비스는
    재생성하지 않았으며 8088 listener가 `Up` 상태다.
  - 실제 8088 브라우저에서 홈 새 대화 포커스, 대화 목록 통합, AI avatar 0개, AUTO 선택 UI 0개,
    공고 분석 아이콘 1개, 사용자 메시지 `rgb(223,243,255)`/검정 글씨, 프로필 메뉴 및 로그아웃
    취소, 랜딩 로그인·회원가입 링크와 3열 중앙 정렬을 확인했다.
  - 공개 홈에서 로그인 모달 열기, 회원가입 모달 전환, 이름 입력 필드 노출, 닫기 후 `/` 복귀를
    실제 8088 브라우저에서 확인했다. 별도 로그인 페이지 컴포넌트 참조는 0개다.
  - 초기 Teleport 갱신 오류를 실제 브라우저에서 발견해 지연 대상 해석으로 수정했고, 최종 배포
    번들의 브라우저 error/warn 로그는 0개다.
- Git: 핵심 UI와 홈 인증 모달 변경은 아직 커밋·Push하지 않았다.

## 2026-08-09 D049 · Capability Graph 단일 AI 내부 릴리스 전환

- 상태: `IMPLEMENTED_AND_LIVE_VERIFIED`
- 영구 결정: `docs/07-decision-register.md`의 `D049`, `AI/docs/decisions.md`의 `D143`
- 결과: `Capability`, `ProjectTask`, `TaskRequirement`를 분리한 승인 `GraphRelease
  0.2.0-alpha.1`을 만들고 단일 AI가 기본적으로 프로세스 내부에서 읽도록 전환했다.
  8600 HTTP graph는 명시적 호환 facade로만 남았으며 기본 `start-all`은 이를 기동하지 않는다.
- 불변식: schema/content hash, 중복, source·역량·과제 참조, 승인 상태, 조건 없는 conditional,
  역량 선수관계 순환, 과제 의존관계 순환, 조회 시 미등록 target을 검증한다.
- fallback: 명시한 릴리스가 무효면 상세 원인을 로그에 남기고 패키지의 마지막 승인 snapshot을
  사용한다. 패키지 snapshot 자체가 무효면 기동 실패한다.
- Verification:
  - `CAPABILITY_GRAPH_URL`과 `JOBIS_GRAPH_RELEASE_PATH`를 비운 AI 전체 테스트:
    `1002 passed`, warning 1개(Starlette TestClient deprecation).
  - no-service 분석 회귀: 승인 릴리스 `0.2.0-alpha.1`로 pipeline `COMPLETED`.
  - 실제 FastAPI 임시 기동: `/v1/capabilities` HTTP 200,
    `CAPABILITY_GRAPH=true`, `ANALYSIS_PIPELINE=true`, external graph URL 빈 값, 종료 후 listener 없음.
  - PowerShell 시작·중지·검증 스크립트 5개 parser 통과, `uv lock --check --offline` 통과,
    `git diff --check` 통과.
  - 권고 lint는 sandbox에서 ruff/build dependency 다운로드가 차단되어 실행하지 못했다.
- Live deployment verification (`2026-08-09`):
  - `docker-compose -p jobis-app -f compose.yaml build ai`로 `jobis-app-ai:latest`
    (`sha256:4580727f5c388b538ee7b0678c29ee6966e4912ab53d5b92771d09d05b78aeb0`)를 빌드했다.
  - `up -d --no-deps --force-recreate ai`로 `jobis-app-ai-1`만 재생성했다. 새 컨테이너는
    `2026-08-08T17:49:53Z` 생성, health `healthy`이며 다른 서비스는 재생성하지 않았다.
  - 컨테이너 런타임은 `GraphReleaseCapabilityGraphPort`, graph `0.2.0-alpha.1`,
    capability `69`개이고 내부 `/health`는 `status=ok`를 반환했다.
  - 실제 8088 저장 공고 `d9996716-fc71-40f5-b875-d20e7ebaaa1a`의 실패 카드에서
    `다시 분석`을 실행했다. 기존 job `e3801b9a-31f3-4dd0-9764-62065b9f6219`가 재실행됐다.
  - AI 로그에서 `CAPABILITY_GRAPH_LOOKUP`, `FIT_ANALYSIS`, `ROADMAP_PROPOSAL`,
    `RESULT_ASSEMBLY`가 모두 `COMPLETED`였고 전체 pipeline 결과 조립까지 `55,722ms`였다.
  - 8088 공고 상세가 실패 화면에서 `VERIFIED FIT ASSESSMENT`와 `새 로드맵 초안이
    준비됐습니다` 화면으로 전환됐고, 페이지를 새로 불러온 뒤에도 완료 결과가 유지됐다.
- Presentation docs sync (`2026-08-09`):
  - 원격 `docs/ai/presentation-docs`의 최신 커밋 `21d68fb`에서 새 문서 5개를 현재 작업 트리에
    가져왔다. 브랜치 전환·병합 커밋 없이 문서 파일만 반영했다.
  - `발표내용소스.md`, `전체구조-에이전트-연결도.md`, `에이전트-툴-목록.md`와 HTML 2개에
    D049의 내부 GraphRelease 기본 실행, UNIFIED 계약/단계, DRAFT 승인 경계, 실제 8088 장애·복구
    근거를 반영했다.
  - `jobis_ai.explain`으로 manifest가 에이전트 7 + 도구 4인지 재확인했고, 실제 릴리스 로더로
    graph `0.2.0-alpha.1`의 `69/82/12/26/11` 수량을 재확인했다.
  - HTML 2개 parse, Markdown 3개 상대 링크, 이전의 `12종`·`HTTP 문 5개뿐`·자동 지도 적용 문구
    잔존 여부를 검사했다.
- Git (`feat/fe/roadmap-change`, Push하지 않음):
  - `171bc46` · 승인 Capability Graph 릴리스를 단일 AI에 내장
  - `35e16be` · 기본 실행에서 외부 그래프 서비스 제거
  - `65e4f2d` · 로드맵 런타임 상태를 AI 계약에서 분리
  - `2ada6f9` · 승인된 원자 역량에만 검증 기능 노출
  - `b93186b` · 재배포된 JS·CSS 재검증
  - `cc3415b` · 발표용 에이전트 구조 문서 동기화
  - `162f12c` · 로드맵 완성도 감사 근거 기록
- Commit-time verification (`2026-08-09`):
  - AI D049 관련 테스트 `23 passed`.
  - Spring 대상 테스트 `BUILD SUCCESSFUL`.
  - 프론트 V3 어댑터 테스트 `8 passed`, production build 성공.
  - PowerShell 실행·검증 스크립트 5개 parser 통과, 전체 `git diff --check` 통과.
- 다음 재개점: 실제 배포·사용자 경로와 변경 커밋까지 검증했다. 원격 Push 또는 MR은 사용자 지시 후
  진행한다. 기존 v2 시드 초안은 설계 입력 보존본으로 남기고 정식 릴리스는
  `AI/src/jobis_ai/career_pipeline/capability_graph/releases/`에 둔다.

- 마지막 갱신: `2026-08-07`
- 상태: `CI_GREEN_MR_TO_DEVELOP_OPEN`
- 영구 결정: `docs/07-decision-register.md`의 `D047`, `D048`

## 지금 어디인가

`feat/be/JOBIS-service`가 Jenkins 빌드 `#8`에서 처음으로 통과했다(`d96d8c2`).
develop 병합 대기 상태다. CI를 세우던 결함을 순서대로 걷어낸 결과이며, 각 원인은
`Verification`의 "CI 복구" 항목에 남겼다.

CI 구조가 바뀌었다 — 뼈대(`Jenkinsfile`, Infra 소유)와 서비스별 검사
(`<서비스>/ci-checks`, 각 담당 소유)를 분리했고, 기능 브랜치에 한해 변경 없는 서비스의
재실행을 생략한다. 규칙은 루트 `AGENTS.md`의 "CI/CD 소유권"이 정본이다.

## Goal

`C:\S15P11C202`의 `develop` 브랜치에 있는 최신 팀 에이전트를 기반으로, 기존 v3의 회사 맞춤
프로젝트 설계·원자 역량 정규화·Capability Graph 조회·사용자 커리어 그래프 생성을 같은 Python
서비스 안에 통합한다. 최종적으로 Spring 백엔드는 하나의 JOBIS AI API만 호출하고, 채팅이 공고
접수부터 확인·분석·로드맵 생성까지 이어지는 주 작업 공간이 된다.

## Done when

- Spring 백엔드가 최종적으로 하나의 AI 서버만 호출한다.
- 자유 대화와 공고 접수·수집·해석이 같은 오케스트레이터와 세션 상태를 사용한다.
- 복수 직무 공고를 임의로 풀스택이나 단일 직무로 합치지 않고 필요한 확인 질문을 한다.
- 사용자가 정리된 공고와 선택 직무·경력 기준을 확인한 뒤 정식 적합도 분석이 시작된다.
- 적합도 분석 이후 회사 맞춤 프로젝트, 원자 역량, 선수관계, 경력 게이트와 회사 기회가 하나의
  사용자 커리어 그래프 제안으로 생성된다.
- 진행 이벤트와 질문·응답·완료 결과가 새로고침과 화면 재진입 후에도 복원된다.
- 모델 공급자 이름이 사용자 화면에 노출되지 않고 실제 에이전트 역할과 단계가 표시된다.
- 기존 채팅·공고·커리어 저장소·로드맵 계약의 의도하지 않은 회귀가 없다.
- 관련 Python, Spring, 프론트엔드, 계약 fixture 및 실제 PostgreSQL 검증이 통과한다. 환경 부족으로
  건너뛴 테스트는 성공으로 기록하지 않는다.

## Current state

### 완료

- `C:\jobiss-service-v3-integration-lab`을 새 작업공간 `C:\JOBIS`로 복사했다.
- `.local`, `.venv`, `node_modules`, `dist`, `build`, `.gradle`, `__pycache__` 등 실행 산출물은
  복사 대상에서 제외했다.
- 원본 작업공간과 격리 포트를 보존하는 `AGENTS.md`를 작성했다.
- 단일 AI 통합 방향을 결정 문서의 `D047 · ACCEPTED · IMPLEMENTATION_PENDING`으로 기록했다.
- Codex 압축 후 복구를 위한 `TASK.md`와 프로젝트 로컬 `SessionStart` 훅을 구성했다.
- 최신 `develop` AI와 현재 JOBIS AI를 실행 산출물·비밀 파일 제외 내용 해시로 비교했다.
  감사 시작 시 최신 전용 36개, JOBIS 전용 18개, 공통 경로 변경 69개를 확인했다.
- `docs/23-d047-latest-baseline-audit.md`에 실제 브랜치·테스트·계약 차이와 기능별
  `PRESERVE | IMPROVE | REPLACE | REMOVE | MISSING | CONFLICT` 분류를 기록했다.
- 복수 직무를 임의 병합하지 않고 사용자 선택을 기다리는 최신 분석 계약·진행 이벤트와
  AI-v3 `positions[]`/resolution 경계를
  `contract-fixtures/d047/multi-role-analysis-baseline.json`으로 고정했다.
- 같은 fixture를 현재 AI와 AI-v3 모델로 각각 검증하는 회귀 테스트 3개를 추가했다.
- 최신 팀 AI를 실행 기준으로 삼고 AI-v3 기능을 `jobis_ai.career_pipeline` 내부 workflow로 이식하는
  파일 단위 설계를 `docs/24-d047-single-ai-file-plan.md`에 확정했다.
- 외부 endpoint, DTO 정본, 진행 이벤트, 세션 소유권, Spring 단일 client 전환, DB 마이그레이션,
  프론트 전환, 제거 대상과 단계별 테스트 게이트를 파일별로 지정했다.
- Phase 0의 경력 2~4년 커리어 게이트와 보안 4년 독립 경로 fixture를 Python·Spring·프론트
  경계에 추가했다.
- Phase 1에서 최신 팀 AI의 provider·오케스트레이터·에이전트와 최신 테스트를 `C:\JOBIS\AI`의
  실행 기준으로 옮겼다. 기존 `codex_cli` 실행은 전환 호환 경계로 유지했다.
- Phase 2에서 `v2bridge/models.py`를 외부 DTO의 단일 정본으로 합쳤고, 기존
  `service_contract.py`는 다섯 개 이름만 재노출하는 호환 shim으로 축소했다.
- 최신 공고 역량 매핑과 기존 복수 직무·확장 채팅·세션 영속·검증/학습 기능을 명시적으로 결합했다.
- Phase 3~4의 source→interpretation→resolution→fit→project→normalization→Capability Graph→roadmap
  모듈을 `jobis_ai.career_pipeline` 아래로 이식하고, 같은 FastAPI(8400)의 `/v1/career/*` 계약으로
  노출했다.
- Spring의 채팅·공고·커리어 분석 호출을 `AiAnalysisClient` 하나로 합치고 별도 `V3AiClient`와
  8500 런타임 실행 경로를 제거했다.
- 장시간 분석은 5초 주기의 역할 기반 진행 이벤트를 보내며, 취소 시 실행 중인 Codex CLI
  프로세스까지 중단하도록 연결했다. 토큰·지연·비용은 실측값이 없을 때 0으로 위조하지 않는다.
- 공고 분석 채팅의 동일 요약 반복을 줄여 짧은 안내와 수정 가능한 공고 확인 카드 한 장만
  기본 화면에 남도록 응답 투영을 정리했다.
- 분석 시각화를 관찰된 이벤트 개수에 따라 7개에서 1개로 축소하지 않고, 공고 해석·조건 확인·
  프로젝트 설계·역량 경로·커리어 로드맵의 5개 안정적인 역할 단계로 유지했다.
- DB와 현재 코드의 분석 공급자 구분을 `LEGACY | UNIFIED`로 전환하는 V62 마이그레이션을 추가했고,
  사용자 화면의 provider 비교 UI와 shadow 실행 경로를 제거했다.
- 로드맵 화면 변환은 제안의 실제 `relations`를 사용하며, 인접 노드를 임의로 직렬 연결하지 않는
  D047 수용 테스트를 유지한다.
- 루트 실행 스크립트는 PostgreSQL·Capability Graph(8600)·통합 AI(8400)·Spring(8380)·
  프론트(5473)만 시작한다. `AI-v3` 폴더는 삭제 승인을 받기 전까지 비교 원본으로만 보존한다.

### 완료 후 다음 단계

- 단일 AI 통합 구현과 자동 검증은 완료됐다.
- D048 프로젝트 중심 사용자 커리어 그래프 구현과 전체 자동 검증을 완료했다.
- 프로젝트 과제는 메인 챕터에서 제거하고 회사 프로젝트 상세의 DAG로 제공한다.
- 이스트게임즈 진입 기회와 네이버웹툰 경력 기회를 관련 취업·경력 2~4년 구간을 통해 하나의
  커리어 그래프에 합성하는 fixture·Spring·frontend E2E를 고정했다.
- 프로젝트 과제 상태·증거 저장, 사용자별 RLS, 직접 역량과 선수 역량 상세 표시를 구현했다.
- Capability Graph `seed.v2`를 additive로 추가하고 일반 백엔드 역량과 게임 결제 도메인 적용을
  분리했다.
- 다음 단계는 사용자 환경에서 실제 이스트게임즈→네이버웹툰 연속 분석 결과를 확인하는 라이브
  수용 검사다. 실패하면 저장된 경계 JSON을 기준으로 AI 생성 품질과 결정적 합성을 구분해 진단한다.
- `AI-v3` 비교 폴더의 삭제나 내부 `V3*` 호환 이름의 대규모 리팩터링은 별도 요청으로 진행한다.
- `C:\JOBIS` 기준선은 원격 `feat/be/JOBIS-service` 브랜치의 `74ea9db`에 보존했다. D048 문서와
  이후 구현을 추가 Push하는 작업은 사용자의 별도 지시를 기다린다.

## Decisions

- 최신 팀 에이전트를 통합 기반으로 사용한다. (`D047`)
- `AI-v3`는 기능 이식과 회귀 확인이 끝날 때까지 비교 원본으로 보존한다. (`D047`)
- 최종 구조는 두 AI 서버가 아니라 하나의 JOBIS AI 서버다. (`D047`)
- 채팅은 보조 UI가 아니라 에이전트 실행의 주 작업 공간이다. (`D047`)
- 공고 구조화, 사용자 확인, 적합도 분석, 프로젝트 설계와 로드맵은 같은 실행 상태를 공유한다.
- SVG는 설명 자료이며 정본은 결정 문서, 데이터 계약, 불변 규칙과 자동 테스트다.
- 메인 지도는 학습 챕터·회사 프로젝트·회사 기회·취업·경력 구간을 보여 주고 프로젝트 과제와
  원자 역량은 상세에서 제공한다. (`D048`)
- 이스트게임즈는 네이버웹툰의 필수 선행 회사가 아니라 관련 경력을 시작할 수 있는 여러 진입 기회
  중 하나다. (`D048`)
- AI는 프로젝트와 직접 역량을 제안하고, 결정적 코드는 선수 closure·중복 제거·경력 배치와
  journey projection을 담당한다. (`D048`)
- 작업 상태의 정본은 대화 기억이 아니라 실제 파일·테스트·Git 상태다.
- 기준선 감사와 회귀 fixture 고정이 끝났으며 최신 코어 기준화부터 구현한다. (`D047`)

## Constraints

- `C:\S15P11C202`와 `C:\jobiss-service-v3-integration-lab`은 비교 원본이므로 수정하지 않는다.
- 사용자의 별도 요청 없이 Git 커밋, Push, 브랜치 변경, 데이터 초기화를 하지 않는다.
- AI가 제공하지 않은 값을 어댑터나 휴리스틱이 임의로 만들어 계약을 통과시키지 않는다.
- 현재 통합 구현을 시작하기 전에 동일 시나리오의 원본 응답과 각 경계의 JSON을 먼저 보존한다.
- 환경 파일과 인증 정보는 이 문서나 로그 요약에 복사하지 않는다.

## Changed / inspected

- `C:\JOBIS\AGENTS.md`
- `C:\JOBIS\README.md`
- `C:\JOBIS\docs\07-decision-register.md` (`D047`)
- `C:\JOBIS\TASK.md`
- `C:\JOBIS\.codex\config.toml`
- `C:\JOBIS\.codex\hooks\session-start.ps1`
- `C:\JOBIS\docs\23-d047-latest-baseline-audit.md`
- `C:\JOBIS\docs\24-d047-single-ai-file-plan.md`
- `C:\JOBIS\docs\25-project-centered-career-journey.md`
- `C:\JOBIS\docs\26-d048-project-centered-career-journey-implementation.md`
- `C:\JOBIS\contract-fixtures\README.md`
- `C:\JOBIS\contract-fixtures\d047\multi-role-analysis-baseline.json`
- `C:\JOBIS\contract-fixtures\d047\career-journey-acceptance.json`
- `C:\JOBIS\contract-fixtures\d047\README.md`
- `C:\JOBIS\contract-fixtures\scenarios\d048-estgames-naver-career-journey.json`
- `C:\JOBIS\AI\tests\test_d047_unified_baseline_fixture.py`
- `C:\JOBIS\AI-v3\tests\test_d047_unified_baseline_fixture.py`
- `C:\JOBIS\backend\src\test\java\com\jobiss\analysis\D047CareerJourneyFixtureTest.java`
- `C:\JOBIS\frontend\tests\v3-adapter.test.ts`
- `C:\JOBIS\AI\src\jobis_ai\career_pipeline\`
- `C:\JOBIS\AI\src\jobis_ai\codex_cli_llm.py`
- `C:\JOBIS\backend\src\main\java\com\jobiss\analysis\AiAnalysisClient.java`
- `C:\JOBIS\backend\src\main\java\com\jobiss\analysis\v3\`
- `C:\JOBIS\backend\src\main\resources\db\migration\V62__unified_ai_runtime.sql`
- `C:\JOBIS\frontend\src\components\AnalysisProgressWheel.vue`
- `C:\JOBIS\frontend\src\roadmap\v3-adapter.ts`
- `C:\JOBIS\scripts\start-all.ps1`
- `C:\JOBIS\scripts\stop-all.ps1`
- `C:\JOBIS\backend\src\main\resources\db\migration\V63__project_task_progress.sql`
- `C:\JOBIS\backend\src\main\java\com\jobiss\analysis\v3\V3ProjectTaskProgressService.java`
- `C:\JOBIS\frontend\tests\e2e\estgames-naver-journey.spec.ts`
- `C:\jobiss-capability-graph-lab\data\seed.v2.yaml`
- 비교 원본: `C:\S15P11C202`, `C:\jobiss-service-v3-integration-lab`

## Verification

- 복사 결과: 파일 `1,050`개, 약 `136.9 MB`.
- 복사 직후 PowerShell 스크립트 문법 검사를 통과했다.
- 제외하기로 한 실행 산출물 디렉터리가 `C:\JOBIS`에 없음을 확인했다.
- `.codex/config.toml`을 Python `tomllib`으로 파싱했다. (`TOML_OK`)
- `session-start.ps1`을 PowerShell parser로 검사했다. (`POWERSHELL_PARSE_OK`)
- 훅을 직접 실행해 `SessionStart` JSON, 전체 `TASK.md`, `D047` 참조가 출력되는지 확인했다.
  (`HOOK_OUTPUT_OK`, 추가 컨텍스트 3,496자)
- `TASK.md`와 훅·설정 파일에 명백한 API 키·토큰 패턴이 없는지 검사했다. (`SECRET_SCAN_OK`)
- 최신 원본 AI를 원본에 캐시·세션을 쓰지 않는 설정으로 실행했다. (`800 passed`)
- 현재 JOBIS AI 전체 회귀가 추가 fixture 테스트를 포함해 통과했다. (`707 passed`, warning 1개)
- AI-v3 전체 회귀가 추가 fixture 테스트를 포함해 통과했다. (`163 passed`)
- Spring 테스트를 JDK 17로 실행했다. (`75 tests`, 실패 0, `19 skipped`)
  - skip은 실제 PostgreSQL 통합 테스트이므로 DB 통합 검증 성공으로 간주하지 않는다.
- 프론트 단위 테스트가 통과하고 production build가 성공했다. (node test 4개, vitest 1개)
- 기존 회귀 corpus 검증이 통과했다. (`40 cases`, P0 `22`, documented `40`)
- D047 복수 직무 fixture 전용 테스트가 양쪽 계약에서 통과했다. (현재 AI 2개, AI-v3 1개)
- D047 커리어 여정 fixture가 현재 AI 4개, AI-v3 3개, Spring 1개, 프론트 5개 테스트에서
  통과했다.
- 최신 코어·단일 DTO 결합 후 AI 전체 회귀가 통과했다. (`842 passed`, warning 1개)
- 단일 AI 호출·취소·진행 이벤트·D047 계약 대상 회귀가 통과했다. (`146 passed`, warning 1개)
- 최종 통합 AI 전체 회귀가 통과했다. (`976 passed`, warning 1개)
- Spring 테스트를 강제 재실행했다. (`69 tests`, 실패 0, 환경형 PostgreSQL 19 skip)

### CI 복구 (2026-08-07)

Jenkins `#3`~`#7`이 연속 실패했다. 스테이지가 순차라 push마다 결함 하나씩만 드러났고,
아래 순서로 걷어낸 뒤 `#8`에서 통과했다.

| 빌드 | 실패 스테이지 | 원인 |
|---|---|---|
| `#3` | Backend `compileTestJava` | `CareerSummary` 4→11 컴포넌트 확장에 테스트 2곳 미반영 |
| `#4` | AI | `AI/AGENTS.md` 증가로 자동 로드 문서 상한 초과(142 > 130) |
| `#6` | Frontend | `node:22-alpine`에 `bash` 없음 (`exit 127`) |
| `#7` | Infra | `verify-release-config.py`의 `V27__` 하드코딩 + prod env 계약 유실 |
| `#8` | — | 통과 |

컴파일을 고치자 가려져 있던 `PostgresRlsIntegrationTest` 실패 5건이 드러났다. 앱 역할
권한을 넓히거나 제약을 완화하지 않고, 테스트가 프로덕션과 같은 경로를 쓰도록 고쳤다
(`create_auth_identity()`, 권한 있는 연결로 큐 조회, `content_fingerprint`·`answered_at`
채움, 제약 위반 단언 사이 savepoint 복구).

`74ea9db`가 작업공간을 덮으면서 딸려온 되돌림 둘을 복구했다 — RAG 구현(develop 27개 통과
→ 브랜치 6 failures·11 errors)과 `.env.production.example`(97줄 → 39줄, prod compose가
참조하는 35개 중 34개 유실). 후자는 develop 판을 복원하고 이 브랜치가 실제로 추가한
백엔드 키를 병합했다.

- Jenkins `#8` `SUCCESS` — Infra 실행, `release-config: ok`.
  Backend·AI·Frontend·RAG는 `#7`에서 동일 트리로 통과해 `#8`에서는 생략됐다.
- 로컬 실측(CI 이미지 + CI 스크립트 그대로): backend `72 tests` 실패 0,
  RAG `27 tests OK`(`python:3.12-slim`), frontend `npm ci` + build 완주(`node:22-alpine`),
  AI `976 passed`.
- 격리 PostgreSQL을 실제 기동해 전체 마이그레이션과 RLS/큐/경력/UNIFIED 제약 테스트를 통과했다.
  (`6 passed`, skip 0)
- Capability Graph 전체 테스트가 통과했다. (`24 passed`, warning 1개)
- 프론트 단위 테스트(node 5개, vitest 1개), production build와 Playwright E2E가 통과했다.
  (`2 passed`)
- 회귀 fixture corpus 검증이 통과했다. (`40 cases`, P0 `22`, documented `40`)
- `scripts/check.ps1` 전체 통합 검사가 성공했다.
- PowerShell 스크립트 20개의 parser 검사와 폐기된 8500/shadow 실행 참조 검사를 통과했다.
- 공고 확인 뒤 career pipeline이 `CAPABILITY_GRAPH_URL` 미설정으로 실패하던 실행 회귀를 수정했다.
  `start-ai-agent.ps1`이 로컬 그래프 URL·공유 비밀·timeout을 기본 주입하며, 실행 스크립트 parser와
  현재 8600 서버의 health/catalog(`0.1.0-alpha.1`)을 확인했다.
- 같은 장애가 다시 발생해도 환경변수 이름을 사용자에게 노출하지 않고 역량 지식 그래프 연결
  안내로 변환하는 회귀 테스트를 추가했다.
- D048 전체 통합 검사를 다시 실행했다. 통합 AI `983 passed`, fixture corpus `40/40`, Capability
  Graph `26 passed`, 프론트 node `8 passed`·Vitest `1 passed`·production build·Playwright E2E
  `3 passed`, Spring 전체 테스트와 격리 PostgreSQL 마이그레이션·RLS 테스트가 성공했다.

## Resume

1. 이 문서와 `D048`, `docs/25-project-centered-career-journey.md`, 구현 기록 `docs/26-...md`를 읽는다.
2. `powershell -ExecutionPolicy Bypass -File C:\JOBIS\scripts\start-all.ps1`로 서비스를 시작한다.
3. 새 계정 또는 사용자가 허용한 테스트 계정에서 이스트게임즈 신입 백엔드 공고를 분석·적용한다.
4. 네이버웹툰 경력 2~4년 백엔드 공고를 추가해 하나의 지도에 취업·경력 구간 뒤로 연결되는지
   확인한다.
5. 프로젝트 상세에서 과제, 직접 역량, 선수 역량과 진행·증거 저장을 확인한다.
6. 라이브 결과가 다르면 proposal JSON, 저장 snapshot, API 응답, adapter 결과 순서로 관계 소실
   지점을 추적한다. 자동 테스트를 먼저 바꾸지 않는다.
7. `AI-v3` 비교 폴더 삭제와 Git 추가 Push는 별도 사용자 확인 후 진행한다.

## Risks / blockers

- 라이브 LLM 공급자의 인증과 모델 설정은 통합 검증 전에 별도로 확인해야 한다.
- 현재 `C:\JOBIS`는 Git 저장소가 아니므로 Git 상태를 정본으로 사용할 수 없다. Git이 연결되기 전에는
  파일 내용과 테스트 결과를 우선한다.
- 라이브 Codex CLI를 사용한 실제 공고 의미 품질·응답 시간 수용 테스트는 사용자의 로컬 인증과 공고로
  별도 확인해야 한다. 자동 테스트는 공급자의 실시간 품질을 보장하지 않는다.
- 일반 Spring 테스트와 별도로 격리 PostgreSQL에서 전체 마이그레이션과 7개 통합 시나리오를
  통과했다. 사용자 개발 DB의 기존 데이터는 초기화하지 않았다.
- 내부 클래스·API·테이블 일부에는 호환성을 위한 `V3` 이름이 남아 있다. 사용자가 보는 공급자 이름과
  현재 DB 실행값은 `UNIFIED`이며, 내부 이름의 대규모 변경은 기능 검증 뒤 별도 리팩터링으로 다룬다.

## 2026-08-09 UNIFIED 재분석·원자 역량 검증 경계 복구

### 완료

- 백엔드가 사용자 런타임 상태인 프로젝트 과제 `progressState`·`evidenceCount`와 노드의
  `atomicAssessmentAvailable`을 AI 입력 또는 정본 로드맵 스냅샷에 섞지 않도록 경계를 분리했다.
- 프로젝트 과제 정의 revision은 진행 상태·증거 개수 변경으로 초기화되지 않고, 실제 과제 정의가
  바뀔 때만 달라지도록 고정했다.
- 승인·등록된 원자 역량만 검증 가능 상태로 노출한다. 기존 로드맵의 넓은 범위 역량과 검토 대기
  역량은 설명만 제공하고 평가 API를 호출하지 않는다.
- 등록된 원자 역량의 최신 평가가 아직 없으면 `200/null`, 등록되지 않은 canonical key는 기존대로
  `404`를 반환하도록 계약을 명확히 했다.
- FastAPI의 중첩 오류와 422 validation detail을 백엔드가 안전한 계약 오류로 변환하도록 보강했다.
- 같은 정적 JS 파일명이 재사용될 때 7일 `immutable` 캐시로 구버전 UI가 고정되던 문제를 수정했다.
  JS/CSS는 조건부 재검증하고 이미지·폰트의 장기 캐시는 유지한다.

### Verification

- Spring 전체 테스트: `76 tests`, 실패 0, 오류 0, skip 7. 실제 PostgreSQL
  `PostgresRlsIntegrationTest`에서 원자 역량 평가 시작 전 `null`과 전체 검증 흐름을 확인했다.
- 프론트 원자 역량 adapter 테스트: `9/9` 통과. production build 성공(`1865 modules`).
- 프론트 전체 테스트에는 이번 변경과 무관한 기존 `login-view.spec.ts` 체크박스 기대값 1건이
  남아 있다. 로그인 UI에 해당 체크박스가 없어 생기는 기준선 테스트 불일치이며 이번 범위에서
  제품 UI를 되돌리지 않았다.
- `git diff --check` 통과(기존 CRLF 변환 경고만 존재).
- `jobis-app-backend`와 `jobis-app-frontend` 이미지를 재빌드하고 해당 컨테이너만 재생성했다.
  AI와 PostgreSQL은 재생성하거나 초기화하지 않았다.
- 8088에서 시선아이티 공고 재분석이 프로젝트 설계와 새 로드맵 초안 생성까지 완주했고,
  DB의 최신 분석 잡 `d3916d14-f10f-47d0-8b88-7359d01b1138`이 `SUCCEEDED`임을 확인했다.
- 새 로드맵 초안은 사용자의 확인 없이 적용하거나 취소하지 않았다. 현재 적용 지도는 버전 5다.
- 8088 커리어 지도에서 넓은 범위 `프로그래밍 기초` 상세에 안내 문구만 표시되고
  `원자 역량 검증 시작` 버튼과 잘못된 404 오류가 사라진 것을 브라우저로 확인했다.
- 배포된 JS 응답 헤더는 `Cache-Control: no-cache, must-revalidate`로 확인했다.

### 다음 작업

- 새 로드맵 초안 적용은 사용자 검토와 명시적인 확인 뒤에만 진행한다.
- 검토 완료된 원자 역량이 실제 사용자 지도에 들어오면 8088에서 질문·채점 UI까지 추가 수용
  검증할 수 있다. 현재 지도에는 등록된 원자 역량이 없으므로 임의 데이터를 만들지 않았다.

## 2026-08-09 공통 사이드바·채팅 UI 계약 정리 및 분석 실패 진단

- 상태: `IMPLEMENTED_AND_LIVE_VERIFIED_UNCOMMITTED`
- 프론트 UI:
  - 홈 메뉴를 제거하고 새 대화·커리어 저장소·채용 공고·커리어 지도만 남겼다.
  - 대화 목록을 모든 앱 화면의 공통 왼쪽 사이드바에 표시하고 접힌 상태에서만 숨긴다.
  - 사이드바 접기 버튼을 본문 헤더 왼쪽으로 옮기고, 좁은 화면에서도 하단 메뉴로 변하지 않게 했다.
  - 사용자 메뉴는 펼친/접힌 상태 모두 본문 쪽으로 열리며 화면 밖으로 잘리지 않는다.
  - 홈 새 대화 입력창에 공고 분석과 이력서 첨부 버튼을 연결했다.
  - 채팅 제목을 공통 상단 헤더 중앙으로 옮기고 기본 인사 메시지를 화면에서 제외했다.
  - 실행 중인 채팅 잡이 있으면 전송 버튼이 중단 버튼으로 바뀌어 기존 취소 API를 호출한다.
  - 취소 상태는 왼쪽 회색 카드, 에이전트 과정은 축약 카드, 답변은 강조·불릿·번호 목록을 렌더링한다.
  - 커리어 지도 가이드는 말풍선·외곽 상자 없이 펭귄만 표시하며 사이드바에 가리지 않는다.
  - 공고 분석 진행 중앙 캐릭터를 합성 아이콘에서 실제 펭귄 자산으로 교체하고 시각 효과를 줄였다.
- 분석 실패 진단:
  - 공고 `eb10c036-71fb-42b6-986f-ad6893e029a4`, 잡 `f87bf008-3aff-4304-a01f-780a9a3ac4be`.
  - 첫 실행은 PROJECT_PLANNING이 사전에 없는 `req.linux.cli-bootstrap` 요구 ID를 참조해 실패했다.
  - 자동 재시도는 `NEW_GRADUATE_OR_EXPERIENCED`인데 `experiencedMinMonths`가 없는 구조화 결과를
    세 번 생성해 Pydantic 계약 검증에서 실패했다. 이번 직접 원인은 Capability Graph 부재가 아니다.
- Verification:
  - `npm test`: Node 9개 + Vitest 2개 통과.
  - `npm run build` 및 Docker frontend production build 성공(1867 modules).
  - `jobis-app-frontend-1`만 재생성했고 `http://localhost:8088/` 응답과 실제 브라우저 UI를 확인했다.
  - 907px 화면에서 왼쪽 사이드바 유지, 공통 대화 목록, 펼침/접힘 프로필 메뉴, 중앙 채팅 헤더,
    홈 도구 버튼, 지도 펭귄 단독 표시를 확인했다.
- Git: 기존 작업과 이번 변경은 아직 커밋·Push하지 않았다.

## 2026-08-09 적합도 질문·공고 확인·진행 이벤트 계약 복구

- 상태: `IMPLEMENTED_AND_TESTED_UNCOMMITTED`
- 원인과 수정:
  - 통합 파이프라인의 프로젝트 기반 적합도 경로가 형식 자격·경력 질문 정책을 실행하지 않고
    `skip_remaining_evidence_questions=True`를 하드코딩해 UNKNOWN 필수 요건을 질문 없이 통과시켰다.
  - `FitAnalysisService`와 프로젝트 overlay가 같은 `next_formal_evidence_question` 정책을 사용하도록
    공유했고, 프로젝트 평가 결과를 만든 직후 질문 정책을 실행한다.
  - AI 요청의 공고 확인 기본값을 `true`로 바꾸고, 백엔드는 저장된 `CONFIRM` 답변으로 얻은
    review ID가 있을 때만 `requirePostingConfirmation=false`를 보낸다. AI는 현재 review ID와 다시
    비교하므로 오래된 ID는 확인 단계를 우회하지 못한다.
  - V3 source `entry_point`를 StoredInputs까지 보존하고 CHAT·POSTINGS_PAGE·INTERNAL의 확인 정책을
    명시적으로 검증한다. 현재 세 진입점은 모두 같은 명시적 확인 정책을 사용한다.
  - 질문 상한은 전체 질문 수가 아니라 `ai_v3_analysis_runs.evidence_question_count` 3회 기준으로
    전달하며, 상한 이후에는 UNKNOWN을 유지하고 질문 단계에 SKIPPED 사유를 남긴다.
  - 실제 질문이 필요 없거나 공고 확인이 이미 유효한 경우에도 PRECONFIRMED, AUTO_CONFIRMED,
    NO_BLOCKING_FORMAL_EVIDENCE_GAP, QUESTION_LIMIT_REACHED 사유가 있는 SKIPPED 이벤트를 기록한다.
  - 프론트 진행 휠은 V3 잡 성공만으로 전 단계를 완료 처리하지 않고 실제 COMPLETED와 SKIPPED를
    구분해 `완료`와 `자동 확인`으로 표시한다.
- OpenCodeReview:
  - `open-code-review v1.8.10`의 delegate preview와 파일별 규칙으로 이번 계약 관련 AI·백엔드·
    프론트 변경을 검토했다. 외부 LLM 직접 review는 저장소 diff를 외부 endpoint로 전송하는 작업이라
    현재 권한 검토에서 차단됐고, delegation mode의 동일 규칙으로 로컬 검토를 완료했다.
  - 높은 확신의 추가 결함은 발견하지 못했다. 기존 작업 트리의 무관한 변경은 검토·수정 범위에서
    제외했다.
- Verification:
  - AI 전체 pytest: `1032 passed`(기존 Starlette deprecation, pytest cache 권한 경고만 존재).
  - AI Ruff 전체: `All checks passed`; `python -m jobis_ai.explain` 성공.
  - 백엔드 `clean test bootJar`: `BUILD SUCCESSFUL`.
  - 프론트 Node 계약 17개와 Vitest 5개 통과, typecheck와 production build 성공.
  - UNKNOWN 필수 경력 WAITING → 답변 후 COMPLETED, UNKNOWN 필수 자격 WAITING, 질문 상한 뒤
    UNKNOWN 보존, CHAT/POSTINGS_PAGE 확인 정책, stale review ID 차단, SKIPPED UI를 회귀 테스트했다.
  - `python ops/verify-release-config.py`: `release-config: ok`.
  - 대상 파일 `git diff --check` 통과. 전체 작업 트리 검사는 기존 무관 파일
    `AI/tests/test_feat_url.py`의 EOF 빈 줄 때문에 실패하므로 해당 파일은 건드리지 않았다.
- Runtime: 이번 작업에서는 Docker 이미지를 재빌드하거나 8088 실제 분석을 재실행하지 않았다.
- Git: 기존 작업과 이번 변경은 아직 커밋·Push하지 않았다.

## 2026-08-09 공고 갭 분석과 로드맵 관계 그래프 분리

- 상태: `IMPLEMENTED_AND_LIVE_VERIFIED_UNCOMMITTED`
- 진단:
  - `VERIFIED FIT ASSESSMENT`, 근거 수준별 준비도, 필수·우대 조건 비교는 로드맵이 아니라
    공고 적합도·역량 갭 분석이다. 커리어 저장소의 이력서·자료 분석은 이 판정에 근거를 공급한다.
  - 실제 로드맵 제안은 `DRAFT OPERATIONS`이며 DB 결과에 43개 operation과 79개 relation이
    있었지만 프론트가 operation만 펼쳐 관계 없는 목록처럼 보였다.
  - 사용자의 확정 커리어 조각은 존재했다. `REQUIRED_EVIDENCE_UNKNOWN`을 자료 전체 부재로
    번역한 프론트 문구와, 교육 조각의 description을 AI formal fact에 보내지 않아 대졸·IT계열
    전공 연결을 판별할 수 없던 백엔드 계약이 문제였다.
- 수정:
  - 공고 상세과 채팅에서 적합도·갭 분석과 로드맵 초안을 명시적으로 분리하고, 준비도 계산 보류
    원인을 '필수 요건과 연결 근거 미확인'으로 정확히 표시한다.
  - 로드맵 operation과 relation을 위상 계층으로 배치하는 관계 그래프를 추가했다.
  - 교육 formal fact에 학위·전공 설명을 보존하고, AI fit overlay가 학위 수준과 전공 계열을
    보수적으로 연결하도록 수정했다. matcher version은 `project-evidence-overlay-3.3.0`이다.
  - 영구 설계 결정은 D050에 기록했다.
- Verification:
  - AI 전체 `1028 passed`, 변경 파일 Ruff 통과.
  - 백엔드 전체 Gradle 테스트 `BUILD SUCCESSFUL`.
  - 프론트 Node 계약 테스트 17개와 Vitest 4개 통과, production build 성공.
  - AI·backend·frontend 이미지를 순차 재빌드·재생성했다. AI·backend healthy, 8088 HTTP 200.
  - 실제 공고 `267b87e1-77fe-448d-88da-ee05521ddc37`에서 적합도·갭 분석과 로드맵 초안이
    분리되고, 기존 43개 단계와 79개 연결이 관계 그래프로 노출되는 것을 확인했다.
- 데이터 경계: 기존 분석 기록은 재실행하거나 변경하지 않았다. 새 학력·전공 매칭 결과는 다음
  재분석부터 적용된다.
- Git: 기존 작업과 이번 변경은 아직 커밋·Push하지 않았다.

## 2026-08-09 로드맵 생성 계약 단절 복구

- 상태: `IMPLEMENTED_AND_TESTED_UNCOMMITTED`
- OpenCodeReview:
  - 로컬 `@alibaba-group/open-code-review` CLI의 `delegate` 규칙으로 AI·백엔드 로드맵 경계를
    검토했다. LLM 직접 스캔은 OCR 전용 endpoint/model/token이 설정되지 않아 실행하지 않았고,
    비밀값이나 사용자 설정 파일은 열지 않았다.
- 원인:
  - AI의 생성 의도 정규식이 `로드맵을 세워줘/짜줘`를 놓쳐 읽기 전용 `roadmap_manager`가
    기존 지도 노드 수를 새 결과처럼 응답했다.
  - 실제 채팅 경로가 dispatched agent 목록을 action mapper에 넘기지 않았고, 저장 공고의
    `postingId`도 제안 작업에서 백엔드까지 전달되지 않았다.
  - 백엔드는 `로드맵 생성`을 자동 분석 의도로 인정하지 않았고, URL/전문이 사용자 메시지에
    다시 들어 있을 때만 자동 작업을 허용했다.
  - AI와 백엔드는 capability 노드만 있는 빈 껍데기 제안도 `COMPLETED`로 인정했고 알림은
    적용 전 `DRAFT`를 완성된 로드맵처럼 표시했다.
- 수정:
  - 로드맵 생성 의도와 단순 조회 의도를 분리하고, 선택된 저장 공고의 ID·URL·원문을 양쪽에서
    다시 대조한 경우에만 자동 V3 분석을 시작한다.
  - 명시적인 빈 backend roadmap snapshot도 AI 세션에 반영해 낡은 노드가 남지 않게 했다.
  - 분석 완료 전에 목표 프로젝트, 한 개 이상의 실행 과제, 지원 기회가 모두 있는 초안인지
    AI와 백엔드에서 각각 검증한다. 빈 껍데기는 `CONTRACT_VALIDATION_FAILED` 또는
    `INVALID_AI_RESPONSE`로 종료한다.
  - 알림과 채팅 문구를 `새 로드맵 초안`으로 바꾸고, 사용자가 미리보고 적용해야 정본 지도에
    반영된다는 경계를 명시했다.
- Verification:
  - AI 전체 테스트: `1024 passed`.
  - AI Ruff: 수정 대상 파일 `All checks passed`.
  - 백엔드 전체 Gradle 테스트: `BUILD SUCCESSFUL`.
  - 집중 계약 테스트에서 `세워줘/짜줘` 의도, 저장 공고 ID 검증, capability-only 초안 거부,
    프로젝트 과제와 지원 기회가 있는 초안 허용을 확인했다.
  - `git diff --check` 통과. 실행 중 Docker 이미지는 이번 작업에서 재빌드하지 않았다.
- Git: 기존 작업과 이번 변경은 아직 커밋·Push하지 않았다.

## 2026-08-09 공통 헤더·대화 검색·커리어 저장소 UI 정리

- 상태: `IMPLEMENTED_AND_LIVE_VERIFIED_UNCOMMITTED`
- 공통 UI:
  - 펼친 사이드바 폭을 252px로 줄이고 대화 상태 토글을 축소했다.
  - 대화 검색 입력창을 사이드바 목록에서 제거하고 JOBISS 로고 옆 검색 아이콘과 플로팅 검색창으로
    통합했다. 접힌 사이드바에서는 검색 아이콘이 로고 아래에 표시된다.
  - 채팅 메시지 영역 배경을 흰색으로 통일했다.
  - 채용 공고·커리어 저장소·커리어 지도 제목을 공통 상단 헤더 중앙으로 옮겼다. 공고/자료 추가
    액션과 지도 버전·목표 개수도 같은 헤더의 오른쪽 영역으로 옮겼다.
- 커리어 저장소:
  - 현재 페이지 전체 선택/해제를 추가하고 기술·프로젝트·경력·교육·자격·성과·링크를 종류별
    섹션과 서로 다른 색으로 묶었다.
  - 수동 원문 입력과 글자 수 표시를 제거했다. 자료 등록은 파일 업로드 또는 공개 URL 수집으로
    단순화했고, URL은 공고 URL 수집 API로 본문을 먼저 가져온 다음 커리어 추출을 시작한다.
  - 실패 카드에 일반 문구 대신 저장된 실제 오류를 표시한다. URL 실패의 재시도는 이전의 82자
    원문을 재사용하지 않고 링크를 다시 수집해 새 분석을 만든 뒤, 성공적으로 시작된 경우에만 이전
    실패 기록을 정리한다.
- 채용 공고:
  - 목록 각 행에 공고와 연결 분석 기록을 삭제하는 명시적 버튼을 추가했다. 기존 확인 대화상자와
    지도 반영 공고 삭제 차단 계약을 그대로 사용한다.
- `포폴` 실패 진단:
  - source `04f213a4-2d55-406a-bf53-67023ce22ab0`은 `URL` 유형이지만 저장 원문이 82자 한 줄뿐이었다.
  - AI 공급자 호출은 두 번 모두 HTTP 200이었으나 추출 조각이 0개였고, DB에는
    `원문에서 커리어 조각을 찾지 못했어요`가 저장됐다. 네트워크 URL 파싱 예외가 아니라 URL을
    링크 메타데이터로만 저장하고 실제 본문을 수집하지 않던 프론트 계약이 원인이었다.
- Verification:
  - `npm test -- --run`: Node 9개 + Vitest 2개 통과.
  - `npm run build`: 1867 modules production build 성공.
  - `git diff --check` 통과(기존 TASK.md CRLF 경고만 존재).
  - frontend 이미지만 재빌드하고 `jobis-app-frontend-1`만 재생성했다. 8088 HTTP 200을 확인했다.
  - 실제 8088 브라우저에서 검색 플로팅 창, 접힌 검색 아이콘 위치, 중앙 헤더 3종, 흰 채팅 배경,
    URL 등록 화면의 원문 입력 제거, 실제 실패 사유, 전체 선택 24개/전체 해제, 종류별 그룹,
    공고 행 삭제 버튼을 확인했다. 삭제·URL 재수집은 데이터 변경을 피하기 위해 실행하지 않았다.
- Git: 기존 작업과 이번 변경은 아직 커밋·Push하지 않았다.

## 2026-08-09 UNIFIED alternative posting and application plan contract repair

- Status: `IMPLEMENTED_AND_LIVE_VERIFIED_UNCOMMITTED`
- Backend V3 analysis now projects its selected position into the legacy `posting_path_profiles` compatibility table without inventing missing experience months.
- AI orchestration preserves the full prerequisite-to-`application_plan` consent chain and does not emit `request_not_fulfilled` while that chain is pending.
- Live retry: alternatives `chat=SUCCEEDED`, REST API count 2; roadmap 45 nodes and 73 relations.
- Tests: AI focused 3 passed, orchestrator/planner/weak-grade 129 passed, backend full Gradle `BUILD SUCCESSFUL`.
- Containers: rebuilt and recreated `ai` and `backend`.
- Remaining failure: image OCR HTTP 500 only; the smoke continued with USER_PASTE fallback.
- Retry logs: zero `request_not_fulfilled`, `AnalysisPipelineFailure`, `PostingInterpretationFailure`, and `CONTRACT_VALIDATION_FAILED` matches.
- Git: no commit or push performed.

## 2026-08-09 검색 및 이미지 API Compose 전달 복구

- 상태: `IMPLEMENTED_AND_LIVE_VERIFIED_UNCOMMITTED`
- 루트 `compose.yaml` AI 서비스가 Jina, Firecrawl, Tavily에 더해 `CLOVA_API_KEY`와 `CLOVA_VLM_URL`도 전달하도록 수정했다.
- `docker compose config --quiet`를 통과했고 다섯 API 환경 변수 이름이 모두 AI 서비스에 포함됨을 확인했다.
- AI 컨테이너만 재생성했으며 health `healthy`, 다섯 설정 모두 컨테이너 내부 `SET`을 확인했다.
- 실제 컨테이너의 `ClovaImageRecognizer`로 샘플 채용 이미지 요청을 호출해 비어 있지 않은 텍스트 106자를 반환받았다.
- 이미지 재빌드와 Git 커밋·Push는 수행하지 않았다. `compose.yaml`은 Infra 리뷰 대상이다.

## 2026-08-09 JobKorea 직접 수집과 Jina/Tavily 단계적 폴백

- 상태: `IMPLEMENTED_AND_LIVE_VERIFIED_UNCOMMITTED`
- 수집 계약:
  - 공고 원문과 JobKorea iframe을 공통 `SourceAcquisitionService`가 먼저 수집한다.
  - 직접 결과가 공고로 판별하기에 부족할 때만 Jina를 호출하고, Jina 이후에도 부족하며
    `TAVILY_API_KEY`가 설정된 경우에만 Tavily Extract를 동일한 최종 URL로 호출한다.
  - 외부 수집기가 성공해 충분한 원문을 확보하면 앞선 보조 경로 실패 경고는 사용자에게 노출하지
    않는다. 모든 경로가 실패했을 때만 원문 붙여넣기나 이미지 첨부를 요청한다.
  - 비공개·사설망 URL은 Jina/Tavily에 전달하지 않는다. Tavily 키는 환경 변수로만 주입하고
    로그·오류에 기록하지 않는다.
- 구현:
  - `feat_url`의 중복 URL 수집 구현을 공통 수집 서비스 어댑터로 축소했다.
  - 기존 `httpx` 의존성으로 Tavily `POST /extract`의 Bearer 인증과 `advanced`/`text` 응답을
    처리했다. 별도 SDK나 테스트 전용 운영 추상화는 추가하지 않았다.
  - Compose AI 환경에 Jina/Tavily 활성화 플래그와 키 전달 항목을 추가했다. `compose.yaml`은
    Infra 소유 파일이므로 병합 전 Infra 리뷰가 필요하다.
- Ponytail/OpenCodeReview:
  - Ponytail의 단순성 규칙에 따라 테스트 편의용 `Callable` 주입을 제거하고 테스트에서만
    메서드를 대체했다.
  - OpenCodeReview v1.8.10 delegation mode로 격리 worktree의 관련 6개 파일 전부를 미리보기하고
    Python/YAML 오류·보안·경계조건 규칙을 적용했다. 차단급 추가 결함은 발견하지 못했다.
  - OCR 전용 LLM endpoint는 설정되지 않아 외부 LLM 직접 review는 실행하지 않았고, 비밀값이나
    사용자 설정 파일은 열지 않았다.
- Verification:
  - 집중 수집 계약 테스트 `24 passed`, AI 전체 테스트 `1035 passed`.
  - 수정 파일 Ruff `All checks passed`, 대상 `git diff --check` 통과.
  - `docker compose config --quiet` 통과.
  - AI 이미지를 재빌드하고 `jobis-app-ai-1`만 재생성했으며 health `healthy`를 확인했다.
  - 컨테이너 내부에서 JobKorea 공고 `49686653`을 실행해 HTML+IFRAME 1,650자를 직접 수집했고,
    관련 없는 추천 꼬리만 제거되는 것을 확인했다.
- 제한:
  - Tavily 실제 API 호출은 키 값을 확인하거나 노출하지 않기 위해 실행하지 않았다. 요청·응답 계약은
    공식 문서와 HTTP 모의 테스트로 검증했다.
- Git: 기존 작업과 이번 변경은 아직 커밋·Push하지 않았다.
# 2026-08-09 프로젝트 플래너 LANGUAGE·CERTIFICATION 계약 및 의미 복구

- 상태: `IMPLEMENTED_FULLY_TESTED_AND_CONTAINER_VERIFIED_UNCOMMITTED`
- 원인:
  - 자연어 회화 요건이 `TECHNICAL_CAPABILITY`로 분류되면 회사 맞춤 프로젝트의 학습 요건으로 강제되어,
    모델이 관련 없는 전자·전력 작업에 연결하지 않고 `unresolvedRequirementIds`에도 넣지 않았을 때
    `_compile_draft()`가 전체 분석을 중단했다.
  - `CREDENTIAL`이 학위·전공과 자격증을 함께 표현해 후속 게이트의 의미가 불명확했다.
  - JSON 스키마 오류는 한 번 복구했지만, 스키마를 통과한 뒤 발견되는 관계·참조 의미 오류는 복구하지 않았다.
- 수정:
  - `RequirementCategory`와 로드맵 게이트에 `LANGUAGE`, `CERTIFICATION`을 추가했다.
  - 영어 회화·외국어 요건과 자격증 표현을 좁은 서버 측 가드로 새 범주에 보정하며, 두 범주는
    프로젝트 학습 capability가 아닌 `CAREER_GATE`로 처리한다. 이전 분석의 `CREDENTIAL` 자격증 매칭은 호환 유지한다.
  - `_compile_draft()`의 모델 수정 가능 의미 오류는 전체 초안을 정확히 한 번 재요청한다. 빠진 학습 요건은
    실제 관련 작업에만 연결하거나 `unresolvedRequirementIds`에 넣도록 강제하며, 두 번째 실패는 기존
    `CONTRACT_VALIDATION_FAILED`로 종료한다.
- Verification:
  - AI 전체 pytest `1,054 passed`.
  - AI 전체 Ruff `All checks passed`.
  - `git diff --check` 통과(기존 작업 트리의 줄바꿈 경고만 존재).
  - `jobis-app-ai` 이미지를 재빌드하고 AI 컨테이너만 재생성했으며 `jobis-app-ai-1` health `healthy` 확인.
- 제한:
  - 현재 Codex 세션에는 Ponytail 플러그인의 호출 가능한 도구가 노출되지 않아 직접 실행하지 못했고,
    동일 범위를 계약 추적·회귀 테스트로 검증했다.
- Git: 현재 진행 상황 체크포인트 커밋에 포함하며 Push는 별도 요청 전까지 하지 않는다.

## 2026-08-10 채팅 실시간 작업 상태 UI

- 상태: `IMPLEMENTED_AND_LIVE_VERIFIED_UNCOMMITTED`
- 기존 백엔드/AI의 채팅 `PLAN`·`PROGRESS` 이벤트 계약을 재사용해, 응답 생성 중인 잡을 임시 assistant 행으로 표시한다.
- 계획 전에는 요청 해석 상태를, 계획 이후에는 실행 중인 에이전트·단계·입력 자료를 약 0.7초 간격으로 갱신한다.
- 임시 작업 상태가 생성 진행을 표현한다. 원형 `…` 이동 버튼은 응답 중인 대화에서 사용자가 하단을 벗어나 위로 스크롤했을 때만 보이고, 누르면 최신 메시지로 이동한다.
- 별도의 SSE 토큰 스트리밍 계약은 추가하지 않았다. 현재 구현 범위는 기존 작업 이벤트의 실시간 표시다.
- Verification:
  - frontend `npm run typecheck` 통과.
  - `node --test tests/ui-state-contract.test.ts`: 8/8 통과.
  - frontend production Docker build 및 `jobis-app-frontend-1` 재생성 성공.
  - 실제 8088 브라우저에서 대체 공고 추천 요청으로 대기 상태 -> `공고 내용을 해설하고 있어요`/`대체 공고 탐색` 진행 상태 -> 최종 응답 순서를 확인했다.
  - 최종 응답 뒤 임시 행, 이동 버튼, 중단 버튼이 모두 사라지는 것을 확인했다. 추가 수정 후 응답 중이더라도 하단에서는 이동 버튼이 숨겨지는 것을 실제 8088에서 확인했다.
  - `git diff --check` 통과.
- Git: 커밋·Push하지 않음.
# 2026-08-10 Career map to learning flow

- Status: `IMPLEMENTED_AND_LIVE_VERIFIED_UNCOMMITTED`
- Added the map competency schedule flow, weekly/monthly learning plan, day detail drawer, learning workspace, elapsed-time redistribution, optional completion, and editable learning-resource memory.
- Kept the canonical roadmap snapshot unchanged. New learning-plan state is browser-local until a backend persistence contract is introduced.
- Verification: frontend typecheck, Node contract tests, Vitest, production build, Docker frontend recreation, and the live 8088 map-to-learning interaction passed. Browser console had no errors or warnings.
- Design QA: `design-qa.md` has `final result: passed`; reference and implementation captures are in `artifacts/design-qa/`.
- Git: no commit or push performed.

## 2026-08-10 Learning chat separation

- Status: `IMPLEMENTED_AND_LIVE_VERIFIED_UNCOMMITTED`
- Replaced the conversation shelf's `보관함` tab with `학습 채팅` on both shared and chat-specific shelves.
- Learning-session conversations no longer appear in normal `진행 중`; existing marker-based sessions and newly registered sessions are both recognized.
- New learning sessions retain a local conversation-to-plan reference, reuse the same conversation on reload, and route back to the matching learning workspace.
- Learning rows use the subject title instead of exposing the internal `[JOBIS_LEARNING_SESSION]` marker.
- Verification: frontend typecheck, 21 Node contract tests, 5 Vitest tests, production build, frontend Docker rebuild/recreation, and live 8088 tab separation passed.
- Git: no commit or push performed.
