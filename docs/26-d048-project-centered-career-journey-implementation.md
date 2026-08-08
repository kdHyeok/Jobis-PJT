# D048 프로젝트 중심 사용자 커리어 그래프 구현 기록

- 날짜: `2026-08-07`
- 상태: `IMPLEMENTED · LIVE_ACCEPTANCE_PENDING`
- 설계 정본: `docs/25-project-centered-career-journey.md`
- 수용 fixture: `contract-fixtures/scenarios/d048-estgames-naver-career-journey.json`

## 구현 결과

### AI와 계약

- `PlannedProjectTask`에 `taskKey`, `dependsOnTaskKeys`를 추가했다.
- 과제 의존은 DAG여야 하며 미등록 과제 참조, 자기 참조, 순환, 필수 과제의 확장 과제 의존을
  거부한다.
- 프로젝트 업무를 먼저 설계하고 승인된 원자 역량을 직접 매핑한다. 지식 그래프에 없는 key를
  만들어 계약을 통과시키지 않는다.
- 백엔드 직무에서 시연 편의만을 위한 프론트 기술은 필수 과제가 될 수 없도록 생성 규칙을
  명시했다.
- 과제 membership은 직접 `capabilityKeys`만 사용한다. 공유 `requirementId`로 같은 역량을 모든
  과제에 복제하던 조건을 제거했다.
- 과제명 대신 공통 기초, 언어·프레임워크, HTTP·API·데이터베이스, 테스트·품질, 배포·운영,
  도메인 심화의 안정적인 챕터를 사용한다.
- 공개 `company-project-blueprint` schema와 fixture가 현재 단일 AI Pydantic 계약과 일치하는지
  자동 검사한다.

### Capability Graph

- 기존 `seed.v1.yaml`은 수정하지 않고 `data/seed.v2.yaml`을 추가했다.
- 일반 백엔드 역량인 상태 전이, 트랜잭션 원자성, 요청 멱등성, 동시 갱신 제어와 게임 결제 도메인
  적용을 별도 노드로 분리했다.
- 일반 역량에서 도메인 적용으로 이어지는 선수 관계를 추가했다.
- 실행 스크립트는 `0.2.0-alpha.1` 데이터셋을 사용한다.

### Spring과 PostgreSQL

- 기존 `V3RoadmapCompiler`를 canonical relation과 경력 흐름의 결정적 합성 경계로 사용한다.
- 진입 회사 기회는 관련 취업으로, 취업은 경력 구간으로, 경력 구간은 경력직 회사 기회로
  연결한다. 이스트게임즈는 여러 진입 기회 중 하나이며 네이버웹툰의 유일한 선행 회사가 아니다.
- `V63__project_task_progress.sql`에 프로젝트 과제 진행과 증거 테이블, 인덱스, trigger, RLS를
  추가했다.
- 프로젝트 과제 조회·상태 변경·증거 등록 API를 기존 roadmap controller 아래에 제공한다.
- 실제 격리 PostgreSQL에서 마이그레이션, 과제 동기화와 사용자 간 RLS 격리를 검증했다.

### 프론트

- roadmap node가 명시적인 `journeyStageRef`를 보존한다. 경력 의미는 backend/AI 계약에서 받고
  rank 추론은 과거 snapshot fallback에만 사용한다.
- 메인 지도에는 프로젝트 과제를 독립 챕터로 표시하지 않는다.
- 하나의 백엔드 여정에서 진입 프로젝트·기회, 관련 취업, 24~48개월 경력 구간, 경력직 프로젝트·
  기회를 이어서 표시한다.
- 프로젝트 drawer에서 과제 DAG 순서, 직접 원자 역량, 선수 역량, 완료 기준, 상태와 증거를 제공한다.
- 기존 파란색 제품 UI, 레인·분기, 확대·축소 동작은 유지한다.

## 계획과 다른 의도적 선택

- 별도 `V3JourneyProjectionService`를 만들지 않았다. 기존 compiler가 이미 관계를 결정적으로
  합성하므로 이름뿐인 wrapper보다 그 경계를 강화했다.
- 별도 `V3ProjectTaskController`를 만들지 않았다. 프로젝트 과제는 roadmap aggregate의 하위
  자원이므로 기존 `V3RoadmapController`에 배치했다.
- Capability Graph validator를 새 규칙으로 전면 수정하지 않았다. 기존 불변 검사가 필요한 조건을
  이미 보장하므로 `seed.v2` 전용 테스트로 신규 관계와 분리를 고정했다.

## 검증

- Spring 전체 테스트: 성공
- 통합 AI: `983 passed`, warning 1개
- fixture corpus: `40/40`, P0 `22`
- Capability Graph: `26 passed`, warning 1개
- 프론트: node `8 passed`, Vitest `1 passed`, production build 성공
- Playwright E2E: `3 passed`
- 격리 PostgreSQL: 전체 마이그레이션과 `7`개 통합 시나리오 성공
- 최종 명령: `powershell -ExecutionPolicy Bypass -File C:\JOBIS\scripts\check.ps1`

## 남은 라이브 수용 검사

자동 테스트는 구조와 불변 규칙을 검증하지만 실제 LLM의 공고 해석 품질은 보장하지 않는다. 사용자의
로컬 인증 환경에서 다음을 한 번 확인한다.

1. 이스트게임즈 신입 백엔드 공고를 분석·적용한다.
2. 네이버웹툰 경력 2~4년 백엔드 공고를 추가한다.
3. 같은 백엔드 커리어 그래프에서 관련 취업·24~48개월 경력 구간 뒤에 네이버웹툰이 놓이는지 본다.
4. 회사별 프로젝트는 하나이고 과제와 원자 역량은 상세에만 나타나는지 본다.
5. 과제 상태와 증거를 저장한 뒤 새로고침해 유지되는지 본다.

Git commit, Push, 브랜치 변경과 사용자 DB 초기화는 이번 구현에서 수행하지 않았다.
