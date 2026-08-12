# 18. 이전 프로젝트 동작 보존 감사와 로드맵 복원 계획

작성일: `2026-08-05`

최종 갱신: `2026-08-06`

상태: `REVIEW_REQUIRED · IMPLEMENTATION_NOT_STARTED`

이 문서는 `C:\jobiss-service`의 기존 서비스 동작과
`C:\jobiss-service-v3-integration-lab`의 V3 통합 동작을 비교해, 새 AI·원자 역량 계약으로
전환하는 과정에서 보존해야 할 제품 규칙이 누락되었는지 확인하기 위한 기준이다.

이 문서는 구현 완료 보고서가 아니다. 아래 항목 중 `확인된 사실`은 코드로 확인한 내용이고,
`검토 필요`와 `수정 후보`는 실제 데이터 흐름과 제품 결정을 확인한 뒤 확정해야 한다.

## 1. 이번에 확인된 핵심 사실

### 1.1 이전 프로젝트는 전체 커리어 여정을 다시 조립했다

기존 `RoadmapService`는 사용자가 등록한 모든 목표 공고를 함께 읽고 다음 요소를 하나의
지도 snapshot으로 조립했다.

```text
공통 기초
→ 직무별 필수·우대 역량
→ 회사 맞춤 프로젝트
→ 신입·경력무관 회사 기회
→ 관련 직무 취업
→ 실무 경력 구간
→ 경력직 회사 맞춤 프로젝트
→ 경력직 회사 기회
```

확인된 기존 동작:

- 직무 track별 `관련 {직무} 취업` 게이트를 생성한다.
- 최소 경력 개월을 모아 2년·3년·5년 등의 경력 milestone을 생성한다.
- 같은 직무 track의 신입·경력무관 회사 기회를 관련 취업 게이트로 합류시킨다.
- 회사별 맞춤 프로젝트와 회사 지원 기회를 분리한다.
- 우대 역량은 필수 진행을 막지 않는 선택 경로로 연결한다.
- 새 공고가 추가되면 모든 목표를 기준으로 전체 지도를 재조립한다.

근거 코드:

- `C:\jobiss-service\backend\src\main\java\com\jobiss\roadmap\RoadmapService.java`
  - 취업·경력 게이트 생성: 약 498~584행
  - 회사 프로젝트와 기회 생성: 약 586~703행
  - 신입 회사에서 관련 취업으로 합류: 약 705~737행

### 1.2 현재 V3는 공고별 변경안을 누적한다

현재 V3는 한 공고를 분석할 때 다음 변경만 제안한다.

```text
현재 로드맵
+ 이번 공고의 원자 역량과 선수관계
+ 이번 회사 맞춤 프로젝트
+ 이번 공고의 경력·자격 게이트
+ 이번 회사 기회
= 다음 로드맵 버전 초안
```

확인된 현재 동작:

- AI가 회사 맞춤 프로젝트와 2~8개의 과제를 설계한다.
- 과제를 승인된 원자 역량에 매핑한다.
- Capability Graph에서 선수관계 closure를 조회한다.
- 이미 검증된 원자 역량은 탐색 경계 및 진행 상태로 재사용한다.
- 기존 canonical capability와 동일한 노드는 재사용한다.
- 회사 프로젝트, 경력·자격 게이트, 회사 기회를 공고별로 만든다.
- AI는 초안만 제안하며 Spring의 결정적 compiler가 버전과 관계를 검증해 적용한다.
- 현재 사용자 진행 상태는 AI proposal로 덮어쓰지 않는다.

### 1.3 현재 V3에는 기존의 전체 커리어 조립 의미가 일부 없다

코드로 확인된 차이:

- V3에는 `관련 직무 취업`이라는 명시적인 합류 노드가 없다.
- 경력직 기회는 실제 취업 사건이 아니라 이전의 더 낮은 경력 회사 `지원 기회`에서 경력
  게이트로 직접 연결될 수 있다.
- 자동 경력 연결은 `roleFamily`와 `roleSpecialization`이 모두 정확히 같고 최소 경력이 낮은
  기회 중 가장 가까운 단계만 사용한다.
- 현재 V3 `OpportunitySpec`은 최소 경력 개월을 저장하지만 최대 경력 개월은 보존하지 않는다.
- 새 공고 적용은 현재 snapshot에 변경안을 누적하며, 모든 목표를 제품 의미에 따라 처음부터
  다시 조립하는 전용 사용자 커리어 여정 assembler는 없다.

### 1.4 프론트 관계 소실에 대한 이전 진단은 현재 코드 기준으로 정정한다

현재 `frontend/src/roadmap/v3-adapter.ts`는 V3 snapshot의 `relations`를 읽어 화면 edge로
변환한다. 따라서 현재 코드에 대해 “어댑터가 모든 관계를 버리고 정렬된 앞뒤 노드를 강제로
일렬 연결한다”라고 단정하면 안 된다.

다만 기본 `여정 보기`는 실제 edge를 그대로 그리지 않고 `domain`, `displayRank`, 경력 gate,
posting ID를 이용해 별도의 chapter 모델을 재구성한다. 따라서 상세 그래프에 관계가 존재해도
기본 여정 화면이 동일한 의미를 표현한다고 보장되지 않는다.

### 1.5 현재 여정 화면에는 V3 node type 호환 결함이 있다

현재 V3 adapter는 경력 gate를 다음과 같이 변환한다.

```text
type = GATE
stage = EXPERIENCE
```

그러나 `frontend/src/roadmap/journey.ts`의 `isExperienceGate`는 다음을 기대한다.

```text
type = MILESTONE
stage = EXPERIENCE
```

따라서 V3 경력 gate가 snapshot에 있어도 기본 `여정 보기`에서 경력 chapter로 인식되지 않을
수 있다. 이는 제품 결정이 아니라 수정해야 할 계약·표현 호환 결함이다.

## 2. 현재 로드맵과 목표 로드맵의 차이

현재 V3는 다음 구조에 가깝다.

```text
필요 역량 → 회사 맞춤 프로젝트 → 회사 기회
경력 게이트 ───────────────────→ 회사 기회
```

목표 커리어 그래프는 다음 의미를 가져야 한다.

```text
공통 기초
→ 현재 목표에 필요한 학습 chapter
→ 회사 맞춤 프로젝트
→ 같은 단계의 관련 회사 기회들
→ 실제 관련 직무 취업
→ 관련 경력 구간
→ 다음 목표에 필요한 추가·심화 chapter
→ 다음 회사 맞춤 프로젝트
→ 다음 회사 기회
```

중요한 불변 규칙:

- 특정 신입 회사 합격이 다음 회사로 가는 유일한 선행조건이 아니다.
- 여러 관련 신입 기회는 실제 관련 취업이라는 사건으로 합류할 수 있다.
- 회사 지원 기회, 실제 취업, 경력 축적은 서로 다른 사건이다.
- 프로젝트 완료, 필수 지원조건 충족, 지원 추천 가능은 서로 다른 상태다.
- 같은 경력 수준만으로 회사를 같은 병렬 경로로 묶지 않는다.
- 원자 역량은 주 화면의 모든 독립 단계가 아니라 chapter 내부의 검증 가능한 세부 퀘스트다.
- 공용 Capability Graph 전체를 사용자 화면에 노출하지 않고 현재 목표에 필요한 부분 그래프만
  사용한다.
- 공고 해석은 역량 사전에 맞춰 요건을 축소하지 않고 원문에서 실제 업무·기술·경력·비학습 조건을
  먼저 보존한다.
- 회사 맞춤 프로젝트 과제를 먼저 설계하고, 과제에 필요한 원자 역량과 선수관계는 그 다음에
  연결한다.
- 공용 그래프에 없는 역량은 누락하지 않고 원문과 프로젝트 과제에 연결된 사용자 범위의 검토
  후보로 표시한다.
- 같은 수행 범위의 공용 역량은 도메인마다 복제하지 않는다. 하나의 canonical node를 재사용하되
  관련 프로젝트와 section 안에서 문맥별 참조로 표시한다.
- 협업·책임감 같은 정성 조건과 학위·경력 같은 hard gate를 기술 학습 node로 만들지 않는다.
- 사용자에게는 내부 provider·model 이름이 아니라 실제 JOBIS 에이전트 역할과 제품 단계를
  표시한다.
- 사용자가 명시적으로 취소한 작업은 화면 재진입이나 서버 복구로 다시 실행하지 않는다.

## 3. 이전 프로젝트 동작 보존 리뷰 범위

로드맵 한 화면만 비교해서는 충분하지 않다. 새 AI·V3 경로가 기존 실행 경로를 우회하는 모든
영역에서 다음 분류를 수행한다.

```text
PRESERVE   기존 제품 의미와 동작을 그대로 보존
IMPROVE    기존 의미를 유지하면서 V3 계약으로 개선
REPLACE    근거가 있는 새 동작으로 의도적으로 교체
REMOVE     명시적인 제품 결정으로 제거
MISSING    의도 없이 누락
CONFLICT   두 설계가 충돌하여 사용자 결정 필요
```

### 3.1 공고 수집과 분석

- URL·본문·이미지의 원문과 정리문 분리
- 복수 직무와 복수 경력 track 질문
- 사용자 확인 전 프로젝트·로드맵 생성을 금지하는 관문
- 같은 공고 fingerprint의 공용 구조화 결과 재사용
- 사용자별 이력·답변·적합도 결과 분리
- 마감 공고와 장기 목표의 구분
- 분석 중복 실행과 대기열 처리
- 서버 종료·재시작 후 RUNNING 작업 복구
- 실패·재시도·취소 후 늦은 응답 처리
- 역량 사전 입력 전 원문 requirement의 완전한 추출과 근거 보존
- project task를 먼저 설계한 뒤 원자 역량을 연결하는 순서
- 공용 그래프 미등록 역량의 provisional candidate 보존
- 기술·업무·프로젝트 경험·경력·학위·정성 조건의 분리

### 3.2 채팅과 비동기 사용자 경험

- 사용자 메시지를 먼저 영속화하고 즉시 표시
- 질문, 선택 답변, 에이전트 진행 상태, 결과를 대화 기록에 보존
- 페이지를 이동해도 백그라운드 작업 유지
- 새로고침 후 현재 분석 상태 복구
- 같은 분석의 질문 중복 저장 방지
- 공고 분석 모달에서 URL 또는 본문을 제출하면 모달을 즉시 닫고, 대화창에 같은 공고 분석 요청을
  보낸 것과 동일한 영속 메시지와 에이전트 작업 생성
- 모달 안에서 수집·AI 정리를 기다리지 않고 완료 후에도 모달을 자동 재개방하지 않음
- 직무·경력 질문과 `PostingReview` 확인을 모달이 아닌 지속되는 대화 기록 안에 표시
- 공고 모달과 일반 대화 요청의 수집·질문·확인·백그라운드 분석·오류·재시도 동작 일치
- 대화 재진입은 상태 조회와 스트림 재구독만 수행하고 `CANCELLED_BY_USER` 작업을 재실행하지 않음
- 사용자 화면에서 Codex·Claude·GPT 등의 provider·model 이름을 제거하고 JOBIS 에이전트 역할을
  표시
- 긴 대화의 내부 스크롤과 최신 메시지 위치 복원

### 3.3 커리어 저장소와 사용자 근거

- 이력서와 자료를 파편화한 커리어 조각 저장
- 저장·수정·삭제·재분석·재시도
- 분석 중 삭제 제한과 사용자 안내
- broad 기술 기록과 원자 역량 검증 상태의 분리
- 사용자 주장을 자동 VERIFIED로 승격하지 않는 규칙
- 증거·평가 결과·로드맵 노드의 역추적

### 3.4 로드맵과 목표 관리

- 모든 목표를 하나의 커리어 그래프로 조립
- 같은 역량 및 기존 검증 진행 상태 재사용
- 관련 취업 합류점과 경력 구간
- 같은 단계의 관련 회사 병렬 배치
- 회사 맞춤 프로젝트와 회사 기회 분리
- 필수·우대 역량의 차이
- 최소·최대 경력과 관련 직무 범위 보존
- 현재 공고와 장기 회사·직무 목표 분리
- 새 초안 미리보기·적용·취소
- 공고 목표 제거·전체 초기화·과거 버전 재현
- 공용 그래프 버전 변경 시 기존 로드맵과 사용자 증거 보존
- 공고 업무로 회사 맞춤 project task를 먼저 만들고 task별 필요 원자 역량과 선수 closure 연결
- 미등록 역량을 누락하지 않고 사용자 범위의 검토 후보로 표시
- 동일한 공용 역량을 여러 도메인에 복제하지 않으면서 각 project section에 문맥별 참조 표시
- 기존 검증 범위와 새 프로젝트 요구 범위를 비교해 부족한 원자 범위만 추가
- 정성 조건과 hard gate를 학습 역량 node에서 분리

### 3.5 데이터·보안·운영

- 사용자별 RLS와 다른 사용자의 분석·로드맵 접근 차단
- 공용 공고·공용 역량과 사용자 데이터의 경계
- 공고 canonicalization 및 중복 회사명 정규화
- 운영자 승인 전 임시 역량을 공용 node로 사용하지 않는 규칙
- 적용·취소·진행 상태 변경의 감사 이벤트
- 분석 provider와 비용·시간·재시도 관찰 가능성
- 삭제·초기화의 참조 정합성과 복구 가능성
- 운영자 `역량 사전 검토함`의 승인·수정 후 승인·병합·보류·반려와 감사 이력
- 후보의 공고 원문·project task·유사 역량·선수관계 제안·영향 사용자 수 역추적
- 승인된 후보를 공용 그래프 새 버전으로 발행하고 과거 로드맵·검증 증거를 보존하는 migration
- provider·model·effort·token·비용은 운영 로그에만 보존하고 사용자 진행 계약과 분리
- 사용자 취소, 연결 중단, 서버 장애, 재시도 가능 실패의 상태와 자동 복구 정책 분리

## 4. 수정 전에 수행할 사실 추적

실제 분석 한 건을 다음 단계에서 동일한 ID로 추적한다.

```text
VerifiedPostingSnapshot과 선택 position
→ 원문에서 추출한 requirement 전체
→ CompanyProjectBlueprint.projectTasks
→ taskCapabilityMappings와 provisional candidates
→ Capability Graph prerequisite closure
→ AI V3 AnalysisPipelineResult.roadmapProposal
→ ai_v3_roadmap_proposals에 저장된 JSON
→ Spring compiler의 compilation preview
→ Roadmap workspace API 응답
→ v3-adapter 변환 결과
→ JourneyModel 및 상세 그래프 렌더링 모델
```

각 단계에서 다음을 비교한다.

- node ID, node kind, canonical key, target ref
- 최소·최대 경력 및 role identity
- project·gate·opportunity의 분리 여부
- relation type과 from/to endpoint
- graph version과 roadmap version
- 사용자 진행 상태와 evidence set
- 필수·우대 및 임시 후보 상태
- requirement → project task → capability 또는 hard gate의 역추적
- canonical capability와 도메인별 화면 projection의 구분
- 사용자 취소·중단·재시도 상태 전이와 동일 job의 attempt
- 사용자용 agent role과 운영용 provider·model metadata의 분리
- 프론트에서 group으로 합쳐지거나 사라지는 node와 edge

이 추적을 완료하기 전에는 “AI 문제”, “백엔드 문제”, “프론트 문제” 중 하나로 단정하지 않는다.

## 5. 수정 후보와 권장 구현 순서

아래는 확정 구현이 아니라 리뷰 후 적용할 수정 후보이다.

### Phase A · 행동 기준선 고정

- 이전 프로젝트와 V3에서 동일한 공개 공고·사용자 상태 fixture를 준비한다.
- 동일 시나리오의 DB, API JSON, 화면 모델 결과를 저장한다.
- 각 차이를 `PRESERVE|IMPROVE|REPLACE|REMOVE|MISSING|CONFLICT`로 판정한다.
- 의도적인 변경이 아닌 `MISSING`부터 회귀 테스트를 작성한다.
- `test3`의 이스트게임즈·네이버웹툰 경력 배치와 4년 경력 AI 보안 공고를 기준 fixture로 추가한다.
- 분석 취소 후 대화 재진입, 공고 모달 제출, provider 이름 노출 여부를 사용자 경험 fixture로
  고정한다.

### Phase B · 사용자 커리어 여정 assembler 복원

- 역량 사전과 무관하게 보존된 공고 requirement와 회사 맞춤 project task를 입력의 시작점으로
  사용한다.
- project task에 승인된 원자 역량을 매핑하고 필수·권장 선수 closure를 조회한다.
- 매핑되지 않은 requirement는 누락하지 않고 `PROVISIONAL_CANDIDATE`로 보존한다.
- 모든 활성·장기 목표를 함께 읽어 사용자 커리어 그래프를 결정적으로 조립한다.
- 관련 신입 기회가 합류하는 명시적 `EMPLOYMENT` 사건을 추가한다.
- `EMPLOYMENT → EXPERIENCE_INTERVAL → 다음 기회` 관계를 표현한다.
- 경력직 회사의 지원 기회에서 직접 경력이 생기는 관계를 제거한다.
- 같은 단계 병렬 기회는 경력 개월뿐 아니라 role family, 관련 직무 인정 범위, 재사용 가능한
  핵심 역량과 프로젝트 증거를 함께 비교한다.
- 협업·책임감 같은 정성 조건은 기술 chapter에서 제외하고 프로젝트·면접·지원 준비 근거로
  투영한다.

### Phase C · 경력·기회 계약 보강

- `minimumExperienceMonths`와 `maximumExperienceMonths`를 모두 보존한다.
- 관련 경력으로 인정되는 role scope와 원문 evidence를 저장한다.
- 현재 공고 instance와 장기 회사·직무 target을 분리한다.
- 마감 공고는 삭제하지 않고 `REOPENING_PREPARATION` 장기 목표로 사용할 수 있게 한다.
- 프로젝트 준비 완료, hard gate 충족, 지원 추천 가능 상태를 별도 계산한다.

### Phase D · 프론트 표현 모델 통합

- `EXPERIENCE` node type 계약을 V3 adapter와 JourneyModel에서 일치시킨다.
- 기본 여정 보기도 실제 관계와 경력 사건을 입력으로 chapter를 구성하게 한다.
- 주 화면에는 foundation, learning chapter, company project, opportunity, employment,
  experience interval을 표시한다.
- 원자 역량은 chapter 상세에서 필수·권장·검토 대기·검증 상태로 펼친다.
- 동일 canonical 역량은 완료 상태를 하나로 유지하면서 백엔드·보안 등 관련 project section에
  문맥별 참조로 표시한다.
- `PROVISIONAL_CANDIDATE`는 공고 근거와 함께 `검토 중 역량`으로 표시한다.
- 상세 관계 보기는 원본 relation을 손실 없이 표시하고, 접힌 group의 edge 집계 규칙을 테스트한다.

### Phase E · 기존 기능 회귀 복원

- 공고 삭제, 목표 제거, 전체 초기화 후 로드맵과 버전의 정합성을 검증한다.
- 분석 작업 복구, 중복 분석, 질문 이력, 대화 진행 상태를 이전 제품 행동과 비교한다.
- 커리어 저장소와 원자 역량 상태의 이전 기록 호환을 검증한다.
- RLS 및 다른 사용자 데이터 격리를 실제 PostgreSQL 통합 테스트로 검증한다.
- 공고 분석 모달은 제출 즉시 닫고 같은 채팅 요청을 생성하며 완료 후 재개방하지 않게 한다.
- `CANCELLED_BY_USER`를 terminal 상태로 고정하고 화면 재진입·worker recovery가 되살리지 못하게
  한다.
- 진행 UI에는 JOBIS 에이전트 역할만 표시하고 provider·model 정보는 운영 로그로 제한한다.

### Phase F · 운영자 역량 사전 검토함 추가

- 신규 역량 후보와 추출 공고·원문 근거·project task를 함께 조회한다.
- AI 제안 수행 범위, 직무·도메인, 기존 유사 역량, 필수·권장 선수관계와 영향 범위를 비교한다.
- 승인, 수정 후 승인, 기존 역량 병합, 보류, 반려를 제공하고 모든 결정을 감사 이벤트로 남긴다.
- 승인된 변경을 공용 Capability Graph 새 버전으로 묶어 미리보기 후 발행한다.
- 병합과 graph version 변경 뒤에도 사용자 검증 증거와 과거 로드맵 버전이 보존되는지 검증한다.
- 운영자는 모든 사용자 로드맵을 승인하지 않으며 새 지식과 의심스러운 분류만 검토한다.

## 6. 반드시 추가할 자동 수용 시나리오

1. 이스트게임즈 신입과 네이버웹툰 경력 공고가 하나의 사용자 커리어 그래프에 들어간다.
2. 이스트게임즈는 네이버로 가기 위한 필수 회사가 아니라 관련 신입 기회 중 하나다.
3. 다른 관련 주니어 백엔드 취업도 동일한 관련 취업 사건을 통해 네이버 경력 구간으로 이어질
   수 있다.
4. 관련 없는 경력무관 직무는 네이버 백엔드 경력 경로의 대체 기회가 되지 않는다.
5. 신입 기회에서 지원 버튼을 누른 사실만으로 관련 경력 gate가 진행되지 않는다.
6. 실제 관련 취업 증거와 재직기간이 경력 구간 진행의 근거가 된다.
7. 최소 2년·최대 4년 조건이 모두 snapshot과 화면에서 보존된다.
8. 이미 검증한 Java·Spring 원자 역량은 다음 회사 구간에서 반복되지 않는다.
9. 기존 검증 범위보다 넓은 수행 범위가 필요하면 부족한 원자 범위만 추가한다.
10. 같은 경력 수준의 관련 회사는 병렬 기회로 표시된다.
11. 필수 선수관계와 권장 선수관계가 계산과 화면에서 다르게 처리된다.
12. 공용 그래프에 없는 역량은 운영자 승인 전 사용자 범위의 검토 후보로만 표시된다.
13. 모든 roadmap node는 공고 requirement, 프로젝트 task 또는 career evidence까지 역추적된다.
14. 새 공용 그래프 버전이 배포돼도 기존 로드맵 버전은 자동 변형되지 않는다.
15. node 버전이 바뀌어도 명시적인 migration 없이 사용자 검증 증거가 사라지지 않는다.
16. 초안을 취소하면 현재 지도와 사용자 진행 상태가 변하지 않는다.
17. 공고 목표를 제거하면 해당 회사 project·opportunity 관계만 제거되고 공유 역량과 다른 목표는
    유지된다.
18. 서버 재시작 후 진행 중 분석이 영구 RUNNING으로 고착되지 않는다.
19. 채팅 질문과 사용자의 선택 답변이 분석 완료 후에도 대화 기록에 남는다.
20. 같은 공고의 공용 분석 재사용과 사용자별 적합도·로드맵 분리가 동시에 유지된다.
21. 사용자 화면과 대화 기록에는 Codex·Claude·GPT 등 provider·model 이름이 나타나지 않고 실제
    JOBIS 에이전트 역할이 표시된다.
22. 사용자가 취소한 분석은 같은 대화 재진입, 새로고침, 서버 재시작 뒤에도 자동 재개되지 않는다.
23. 서버 장애로 lease가 끊긴 `INTERRUPTED` 작업만 정책에 따라 복구되고 사용자 취소와 구분된다.
24. 공고 분석 모달에서 URL을 제출하면 모달이 즉시 닫히고 동일한 채팅 메시지·분석 작업이 하나만
    생성되며 완료 후 모달이 다시 열리지 않는다.
25. 4년 경력 AI 보안 공고는 보안 foundation·project task·관련 취업·경력 4년·AI 보안 심화·회사
    기회가 연결된 경로를 만들며 Docker·CI/CD와 회사 프로젝트 하나로 축약되지 않는다.
26. 동일 범위의 Docker는 공용 node 하나를 사용하지만 백엔드와 보안 project section에서 각각
    필요한 이유가 표시되고 완료 상태가 동기화된다.
27. 컨테이너 취약점 점검처럼 기존 Docker 범위를 넘는 요구는 부족한 보안 원자 범위로 추가된다.
28. 공용 그래프에 없는 AI 보안 역량은 사라지지 않고 공고 requirement와 project task에 연결된
    검토 후보로 표시된다.
29. 협업·책임감·열정은 기술 학습 node가 되지 않고 프로젝트 증거·면접·지원조건으로 분리된다.
30. 운영자가 후보를 병합·승인해 새 그래프 버전을 발행해도 기존 사용자 증거와 과거 로드맵이
    자동 변형되거나 소실되지 않는다.

## 7. 아직 결정하지 않은 항목

다음은 리뷰 결과를 본 뒤 사용자와 확정해야 한다.

- 관련 취업을 `GATE`, `EVENT`, `MILESTONE` 중 어떤 node kind로 계약할지
- 관련 경력 role scope를 deterministic taxonomy, 운영자 승인 데이터, AI 제안 중 어떤 조합으로
  판정할지
- 경력 기간의 시작·종료 증거와 역량 증거를 각각 어떤 통과 조건으로 사용할지
- 최대 경력을 지원 불가 hard gate로 사용할지, 공고 snapshot 정보로만 표시할지
- 전체 목표 변경 때마다 snapshot을 전부 재조립할지, stable node identity를 유지하는 증분
  compiler 위에 별도 projection을 둘지
- 주 화면 chapter의 묶음 크기와 원자 역량 펼침 기준
- 운영자 승인 변경을 후보별 즉시 발행할지 검토 묶음 단위의 graph version으로 발행할지
- 같은 canonical 역량의 문맥별 참조를 alias node, projection edge, chapter membership 중 어떤
  화면 계약으로 표현할지

## 8. 계획 작성 시점에 하지 않은 작업

- 로드맵 생성·컴파일·렌더링 코드를 수정하지 않았다.
- DB schema나 기존 데이터를 변경하지 않았다.
- 테스트를 추가하거나 실행하지 않았다.
- Git commit, push, branch 작업을 하지 않았다.

위 내용은 계획을 작성한 시점의 상태다. 이후 `2026-08-06`에 소스·DB를 변경하지 않는 실제 코드
추적과 자동 테스트를 수행했으며 결과는 다음 절에 기록한다.

## 9. 2026-08-06 전체 보존 감사 실행 결과

### 9.1 검증 범위와 자동 테스트 결과

- `scripts/check.ps1`을 실행해 Spring 테스트, legacy AI 697개 테스트, V3 회귀 fixture 40개,
  Capability Graph 테스트, AI V3 테스트와 프론트 production build가 통과했다.
- 별도로 `npm test -- --run`을 실행했으며 프론트 테스트 3개가 통과했다.
- Spring 테스트 결과는 총 64개 중 52개 실행 성공, PostgreSQL RLS 통합 테스트 12개는 Docker를
  사용할 수 없어 모두 `SKIPPED`였다. 따라서 이번 실행으로 tenant 격리가 실제 DB에서 검증됐다고
  말할 수 없다.
- `scripts/check.ps1`은 프론트 `npm test`를 실행하지 않고 build만 수행한다. 또한 현재 프론트
  테스트 파일은 `v3-adapter.test.ts` 하나뿐이어서 채팅 복구, 모달, 로드맵 적용·삭제·초기화,
  접근성 회귀를 보호하지 못한다.

### 9.2 출시 차단 수준으로 확인된 의미 결함

1. V3 통합 pipeline은 일반 `CapabilityNormalizationService.normalize`를 사용하지 않고
   `compile_project_normalization`을 사용한다. 프로젝트 계획기가 승인 catalog에서 역량을 찾지
   못하면 해당 요건은 `UNRESOLVED`가 되며 `NEW_CANDIDATE_PROPOSED`로 변환되지 않는다. 따라서
   공고에 실제로 존재하지만 공용 그래프에 없는 역량이 사용자 범위의 검토 후보로 보존되지 않고
   로드맵에서 빠질 수 있다.
2. 프로젝트 계획 프롬프트가 회사 프로젝트 과제 설계와 승인된 원자 역량 선택을 한 번에 수행하며
   전체 catalog를 입력한다. 이 구조는 프로젝트가 공고 업무에서 먼저 설계되기보다 현재 사전에
   존재하는 역량에 맞춰 축소될 위험이 있고 catalog가 커지면 96,000자 제한으로 분석 자체가
   실패한다.
3. V3 adapter는 경력 gate를 `type=GATE, stage=EXPERIENCE`로 만들지만 JourneyModel은
   `type=MILESTONE, stage=EXPERIENCE`만 경력 chapter로 인식한다. 경력 gate가 JSON에 있어도 기본
   여정 화면에서 신입 회사와 경력 회사가 같은 단계처럼 보일 수 있다.
4. V3 compiler는 같은 직무의 낮은 경력 회사 `지원 기회`를 다음 경력 gate에 직접 연결한다.
   실제 관련 직무 취업 사건과 경력 축적 구간이 없으므로 특정 회사 지원 기회가 경력을 만들어내는
   것처럼 보인다.
5. 공고 해석 계약에는 최소·최대 경력이 있지만 V3 `OpportunitySpec`은 최소 경력만 저장한다.
   `2년 이상 4년 이하` 같은 상한이 로드맵 snapshot에서 소실된다.

### 9.3 공고 수집·분석 수명주기

- `V3SourceService.startAnalysis`는 source에 `posting_id`가 있으면 최신 verified snapshot revision을
  비교하지 않고 그 공고의 가장 최근 V3 job을 그대로 반환한다. 사용자가 원문을 다시 고쳐 확인해도
  과거 성공·실패·취소 job을 재사용해 새 분석을 시작하지 못할 수 있다.
- legacy 공고 분석에는 공용 구조화 결과 cache와 lease가 있지만 V3 경로는 이를 사용하지 않는다.
  다른 계정이 같은 공고를 분석하면 구조화·프로젝트 계획을 다시 실행하므로 체감 시간이 동일하고
  비용도 반복된다.
- 새 공고 화면의 본문 입력은 acquire 직후 사용자 확인 화면을 거치지 않고 즉시 verify·분석한다.
  URL·이미지 경로 및 채팅 경로와 같은 `PostingReview` 승인 관문이 아니다.
- 채팅의 공고 분석 모달은 현재도 수집·정리를 모달 안에서 기다리고, 완료된 action을 복구할 때
  다시 열 수 있다. D038에서 결정한 “제출 즉시 닫고 동일한 대화 요청으로 영속화하며 자동 재개방하지
  않음”이 구현되지 않았다.
- 분석 취소는 Spring Future를 interrupt하고 늦은 결과 저장을 revision/소유권으로 막지만, AI V3
  streaming endpoint는 별도 daemon thread를 만들고 client 연결 해제나 취소 신호를 확인하지 않는다.
  사용자 화면에서는 취소돼도 이미 시작한 LLM 작업이 서버에서 끝까지 실행될 수 있다.

### 9.4 채팅·비동기 복구

- 사용자 메시지는 optimistic UI로 즉시 나타나고 서버 저장 실패 시 대화를 다시 읽어 복구한다.
  긴 대화는 200개 최신 메시지와 이전 메시지 paging을 제공하며 채팅 내부 스크롤과 10줄 composer가
  구현돼 있다.
- 일반 chat reply job에는 사용자 취소 endpoint가 없다. 오래 걸리거나 잘못 실행된 자유 대화를
  사용자가 중단할 수 없다.
- chat job enqueue는 `trigger_message_id` 중복 upsert보다 먼저 AI 사용량을 차감한다. 동일 전송의
  네트워크 재시도는 새 작업을 만들지 않아도 quota를 한 번 더 소비할 수 있다.
- 공고 분석 질문·답변은 message와 analysis job을 다시 조회해 복원하지만, chat action 복구가
  과거 `POSTING_REVIEW` 실행을 다시 모달로 여는 동작과 결합되어 제품 결정과 충돌한다.

### 9.5 커리어 저장소

- 검색·정렬·수정·병합·보관·복원·삭제·원본 분석 취소·재시도와 올바른 빈 상태는 현재 구현돼
  있다. 이전 리뷰의 “관리 기능이 없다”는 현재 코드에는 적용되지 않는다.
- 사용자가 조각의 종류·제목·설명을 수정해도 숨은 `canonicalKey`와 `detail`은 원래 값을 그대로
  저장한다. 화면 의미와 내부 매칭 정체성이 달라져 후속 적합도·증거 판단을 오염시킬 수 있다.
- 병합은 같은 `kind`인지만 확인하고 첫 조각의 canonical key/detail을 유지한 채 나머지 조각을
  영구 삭제한다. 같은 종류지만 다른 수행 범위인 조각을 합칠 수 있고 preview, lineage, undo가 없다.

### 9.6 로드맵 목표·버전 관리

- V3 preview/apply는 expected roadmap version과 사용자 행 잠금을 사용해 동시 적용을 방어하며,
  적용 전 draft 경계는 보존한다.
- V3에는 목표 공고 제거, 전체 목표 초기화, 재조립, 버전 목록, 과거 버전 복원 API가 없다. 통합
  `CareerMapView`도 V3 모드에서는 이 버튼과 버전 이력을 숨긴다. 이전 로드맵에서 제공하던 목표
  수명주기 기능이 누락됐다.
- V3 변경 diff는 `removed`를 항상 빈 배열로 만든다. 삭제가 포함되는 계약으로 확장돼도 사용자가
  제거 내용을 검토할 수 없다.
- 홈은 legacy `/api/roadmap`만 읽는다. V3 초안·현재 지도·진행률과 홈의 다음 퀘스트가 서로 다른
  정본을 볼 수 있다.
- 공고 영구 삭제의 참조 검사는 legacy `roadmap_targets`와 `roadmap_versions`만 확인하고 V3
  roadmap version/proposal 참조는 확인하지 않는다. 현재 V3 지도에서 쓰는 공고를 삭제하거나
  snapshot에 고아 참조를 남길 위험이 있다.
- 같은 canonical 역량을 재사용할 때 최초 `sectionKey`를 보존하므로 Docker가 백엔드에서 처음
  생성되면 보안 프로젝트에서도 백엔드 section에만 남는다. canonical node를 복제할 것이 아니라
  완료 상태는 공유하고 프로젝트별 chapter membership/문맥 관계를 별도로 표현해야 한다.
- capability chapter 제목은 canonical key prefix의 하드코딩 목록으로 결정한다. 새 기술군은
  `기타 핵심 역량`으로 떨어져 사전 확장과 화면 분류가 다시 어긋난다.

### 9.7 검증 문제와 학습 가이드

- V3 문제 생성 계약은 `scopeDefinition`, `excludedScope`, 검증 방법을 입력하고 회사 맥락은 예시
  장식으로만 사용하도록 제한한다. 자바 역량에서 트랜잭션을 묻는 문제를 막기 위한 방향은 맞다.
- V3는 역량당 2~3문제를 만들고 모든 문항 통과와 평균 75점 이상을 요구한다. 다만 실패 뒤 새
  session을 시작하면 통과한 문항 유형을 30일간 승계하지 않아 전체를 다시 풀어야 한다. legacy
  검증에 있는 부분 승계 정책이 V3에는 없다.
- 동일 역량에 IN_PROGRESS session이 있으면 새 회사·프로젝트 target context를 무시하고 기존
  session을 반환한다. 사용자가 목표 회사를 바꿔도 이전 맥락 문제가 이어질 수 있다.
- 답변 채점은 DB lock 전에 LLM을 호출하므로 같은 문항을 동시에 제출하면 두 번 과금한 뒤 한 결과만
  저장할 수 있다. V3 답변 DTO에는 최대 길이 제한도 없다.
- V3 원자 역량에는 검증 UI만 있고 학습 가이드 생성 API가 없다. `CareerMapView`는 V3 역량을
  선택하면 legacy learning 호출 전에 return한다. “먼저 학습하고 검증”이라는 제품 흐름이 V3에서
  끊긴다.

### 9.8 보안·운영

- access cookie는 HttpOnly, SameSite=Lax이며 CSRF cookie/header와 credentialed explicit CORS를
  사용한다. RLS executor는 transaction-local `app.current_user_id`를 설정한다.
- 로그아웃은 브라우저 cookie만 지우고 auth token version을 올리지 않는다. 이미 탈취된 access
  token은 기본 12시간 만료 전까지 계속 유효하다.
- production validator는 legacy AI secret, JWT marker, secure cookie, CORS, repository token key,
  mail 설정을 검사하지만 V3 AI shared secret과 DB 기본 계정/비밀번호는 검사하지 않는다.
- URL 수집은 사설 IP와 redirect를 검증하고 크기를 제한하지만 DNS 검증과 실제 HTTP 연결 사이가
  분리돼 있어 DNS rebinding에 대한 연결 시점 고정이 없다.
- 이력서 원문, 공고 원문, 검증 답변은 RLS로 격리되지만 DB에는 평문으로 저장된다. 보존 기간,
  삭제 전파, 운영자 접근 감사와 백업 폐기 정책을 출시 전에 확정해야 한다.

### 9.9 현재 UI·UX와 접근성

- 사이드바 active 판정, 접기 버튼, 채팅 내부 스크롤, 10줄 composer, 저장소 빈 상태 등 과거에
  보고된 여러 UI 문제는 현재 코드에서 수정돼 있다.
- 상단의 초록 상태 `AI 작업은 다른 화면에서도 계속됩니다`는 실제 실행 작업 유무와 무관하게 항상
  표시된다. 유휴 상태에서도 진행 중이라는 인상을 준다.
- 공고 모달은 `role=dialog`를 갖지만 focus trap, 첫 포커스, Escape close와 닫힌 뒤 trigger focus
  복원이 없다. 여러 삭제·병합·이름 변경은 제품 dialog가 아니라 `window.confirm/prompt`를 사용한다.
- CSS에 8~10px 글자가 매우 많아 고해상도 데스크톱과 모바일에서 읽기 어렵다. 목표 설정 input은
  focus outline을 제거하면서 동등한 focus ring을 제공하지 않는다.
- 모바일 하단 navigation은 6열로 고정돼 있지만 운영자에게는 7번째 메뉴가 추가된다. 운영자
  모바일 화면에서 다음 줄로 밀리거나 68px 높이 안에서 잘릴 수 있다.
- CSS는 200KB가 넘는 단일 `base.css`에 과거 스타일과 현재 테마 override가 중첩돼 있고,
  라우터에서 사용하지 않는 `V3CareerMapView.vue`도 남아 있다. 같은 문제를 고친 스타일이 뒤에서
  다시 뒤집히기 쉬운 구조다.

### 9.10 종합 판정

현재 상태는 계약 검증과 단위 테스트는 강하지만 `출시 가능` 판정은 아니다. 특히 로드맵의 신규
역량 보존, 경력 사건, 최대 경력, V3 목표 관리, 홈과 V3 정본 통합, 취소 전파, 실제 PostgreSQL RLS
검증이 먼저 해결되어야 한다. 우선순위는 다음과 같다.

```text
1. requirement → project task → 승인 역량 또는 provisional candidate의 무손실 경로 복원
2. EMPLOYMENT·EXPERIENCE_INTERVAL·최소/최대 경력 계약과 JourneyModel 통합
3. V3 목표 제거·초기화·버전 이력 및 홈·삭제 참조의 단일 정본화
4. source revision, 동일 공고 공용 cache, 사용자 취소와 AI 실행 취소 전파
5. V3 학습→검증 흐름, target context, 부분 재시험과 동시 제출 보호
6. 운영자 역량 사전 검토함과 graph version 발행·migration
7. 실제 PostgreSQL RLS/E2E 및 프론트 사용자 흐름·접근성 자동 테스트
```

이번 감사에서는 소스 코드, DB schema와 사용자 데이터, Git 상태를 변경하지 않았다. 변경한 것은
이 리뷰 문서뿐이다.
