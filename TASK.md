# JOBIS 단일 AI 통합 작업 상태

- 마지막 갱신: `2026-08-07`
- 상태: `PROJECT_CENTERED_CAREER_JOURNEY_IMPLEMENTED_LIVE_ACCEPTANCE_PENDING`
- 영구 결정: `docs/07-decision-register.md`의 `D047`, `D048`

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
