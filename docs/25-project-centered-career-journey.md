# 프로젝트 중심 사용자 커리어 그래프 수정 계획

- 작성일: `2026-08-07`
- 상태: `IMPLEMENTED · LIVE_ACCEPTANCE_PENDING`
- 결정: `D048`
- 수용 fixture: `contract-fixtures/scenarios/d048-estgames-naver-career-journey.json`
- 설명 자료: `C:\Users\SSAFY\Downloads\mermaid-diagram.svg`

## 1. 목적

JOBIS의 메인 로드맵을 공고에서 추출한 기술과 프로젝트 과제를 길게 나열하는 화면이 아니라,
사용자가 목표 회사에 지원하기까지 거쳐야 하는 학습·프로젝트·취업·경력·다음 기회를 하나의
커리어 그래프로 보여 주는 화면으로 수정한다.

회사 맞춤 프로젝트는 JOBIS의 핵심 차별점으로 유지한다. 다만 프로젝트의 세부 과제와 원자 역량을
메인 지도에 모두 펼치지 않고, 회사 맞춤 프로젝트 노드의 상세 내용으로 제공한다.

## 2. 현재 코드에서 확인된 사실

현재 통합 파이프라인에는 다음 기반이 이미 있다.

- 공고별 `TARGET_PROJECT`, `OPPORTUNITY`, `CAREER_GATE` 노드
- 실제 취업을 표현하는 `EMPLOYMENT_EVENT`
- 관련 실무 경력을 표현하는 `EXPERIENCE_INTERVAL`
- `UNLOCKS_PROJECT`, `UNLOCKS_OPPORTUNITY`, `POTENTIAL_CAREER_ENTRY`,
  `STARTS_EXPERIENCE`, `SATISFIES_EXPERIENCE_GATE` 관계
- 공용 원자 역량과 사용자별 진행 상태 분리
- 프로젝트의 `tasks`, `capabilityKeys`, `requirementIds`, `acceptanceCriteria`
- 로드맵 제안·미리보기·적용·버전 보존

현재 프론트 어댑터는 과거처럼 정렬 결과를 앞뒤로 임의 연결하지 않고 실제 `relations`를 사용한다.
따라서 최신 문제를 단순히 “프론트가 모든 관계를 버린다”라고 진단해서는 안 된다.

현재 화면을 가장 크게 망가뜨리는 직접 원인은
`AI/src/jobis_ai/career_pipeline/roadmap/service.py`의 `_section_memberships()`다. 이 함수는 원자 역량을
프로젝트 과제에 배치할 때 다음 조건을 OR로 사용한다.

```text
capabilityKey가 과제에 직접 포함됨
또는
원자 역량과 과제가 같은 requirementId를 참조함
```

하나의 공고 요건을 여러 과제가 공유하면 같은 원자 역량 묶음이 모든 과제에 반복된다. 이어서
`frontend/src/roadmap/v3-adapter.ts`가 프로젝트 과제명을 메인 `MILESTONE` 제목으로 사용하므로,
프로젝트 상세 과제 다섯 개가 메인 로드맵 챕터 다섯 개처럼 나타난다.

## 3. 최종 로드맵 정의

> JOBIS 로드맵은 기술 목록이 아니라, 회사 맞춤 프로젝트에 필요한 역량과 선수지식, 사용자가
> 검증한 기존 역량, 실제 경력 조건, 여러 회사의 지원 시점을 하나의 사용자 커리어 그래프로
> 조립한 결과다.

메인 지도에서 사용하는 단위는 다음 여섯 가지다.

1. 공통 기초 학습 챕터
2. 직무 학습 챕터
3. 회사 맞춤 프로젝트
4. 회사 지원 기회
5. 관련 직무 취업
6. 관련 실무 경력 구간

프로젝트 상세에서 사용하는 단위는 다음과 같다.

- 프로젝트 과제
- 과제의 직접 필요 원자 역량
- 선수 원자 역량
- 완료 조건
- 제출 결과물과 검증 상태

## 4. 이스트게임즈와 네이버웹툰의 기대 흐름

```text
프로그래밍 · Git · CS 기초
→ HTTP · API · 데이터베이스
→ Java · Spring Boot
   ├→ 이스트게임즈 맞춤 프로젝트 → 이스트게임즈 신입 지원 기회
   ├→ A사 맞춤 프로젝트 → A사 신입 지원 기회
   └→ B사 맞춤 프로젝트 → B사 경력무관 지원 기회
        → 관련 백엔드 취업
        → 관련 백엔드 실무 경력 2~4년
        → 설계 · 운영 · 장애 대응 심화
        → 네이버웹툰 맞춤 프로젝트
        → 네이버웹툰 경력 지원 기회
```

이스트게임즈 합격은 네이버웹툰의 필수 선행조건이 아니다. 이스트게임즈는 관련 백엔드 경력을
시작할 수 있는 여러 진입 기회 중 하나다.

## 5. 핵심 불변 규칙

### 5.1 메인 지도와 프로젝트 상세 분리

- 공고 하나는 메인 지도에 회사 맞춤 프로젝트 하나와 회사 기회 하나를 만든다.
- 프로젝트의 과제명은 메인 지도 챕터명이 될 수 없다.
- 원자 역량은 공통·직무 학습 챕터 내부 또는 프로젝트 상세에만 나타난다.
- 프로젝트 노드를 선택하면 과제 DAG, 필요 역량, 완료 조건과 증거를 연다.

### 5.2 직접 역량과 선수 역량 분리

- AI는 각 과제를 수행하는 데 직접 필요한 `capabilityKeys`만 선택한다.
- 선수 역량은 Capability Graph의 승인 관계로 확장한다.
- 같은 선수 역량을 모든 프로젝트 과제에 복사하지 않는다.
- 필수 선수관계와 권장 선수관계는 완료 계산과 화면에서 구분한다.

### 5.3 공용 진행 상태와 문맥별 표현 분리

- canonical capability와 사용자 진행 상태는 하나다.
- 같은 Docker 역량은 백엔드와 보안 레인에 문맥 참조로 각각 표시할 수 있다.
- 두 화면 표현은 같은 사용자 완료 상태와 검증 증거를 사용한다.
- 보안에서 더 넓은 Docker 수행 범위를 요구하면 이름이 같다는 이유로 재사용하지 않고 범위 차이만
  별도 원자 역량으로 만든다.

### 5.4 회사와 경력 배치

- 같은 경력 수준만으로 회사를 병렬 배치하지 않는다.
- 직무 계열, 역량 겹침, 프로젝트 증거 재사용 가능성, 관련 경력 인정 범위를 함께 확인한다.
- 신입·경력무관 기회는 관련 직무의 진입 단계에 놓을 수 있다.
- 경력 공고는 관련 취업과 `EXPERIENCE_INTERVAL` 뒤에 놓는다.
- 최소·최대 경력, 관련 직무 범위와 증거 요구를 모두 보존한다.
- 마감 공고는 `REOPENING_PREPARATION` 장기 목표로 남기며 현재 지원 가능 상태와 구분한다.

### 5.5 완료 의미 분리

- 원자 역량 검증 완료와 프로젝트 과제 완료는 다르다.
- 프로젝트 완료와 형식적 지원조건 충족은 다르다.
- 지원 추천과 실제 합격 가능성은 다르다.
- 프로젝트는 필수 과제, 완료 기준, 결과물 증거와 필수 원자 역량 검증이 모두 충족돼야 완료된다.

## 6. 책임 분리

### AI가 담당한다

- 공고의 복수 직무와 경력 조건 의미 해석
- 선택 직무의 실제 업무와 도메인 해석
- 회사 맞춤 프로젝트와 과제 설계
- 과제에 직접 필요한 승인 원자 역량 선택
- 공용 그래프에 없는 역량 후보와 근거 제안

### Capability Graph가 담당한다

- 원자 수행 범위의 정체성
- 필수·권장·조건부 선수관계
- 기술 container와 역량 종류
- 검증 방법과 제외 범위
- 그래프 버전과 근거

### 결정적 코드가 담당한다

- 선수 closure 조회
- 기존 사용자 역량과 진행 상태 재사용
- 중복 제거
- 직무 레인과 경력 단계 계산
- 회사 프로젝트·회사 기회·취업·경력 게이트 연결
- 로드맵 버전 병합과 재현
- 메인 지도용 투영

AI는 화면 좌표를 만들지 않고, 프론트는 경력 요건을 추측하지 않는다.

## 7. 파일별 구현 계획

### 7.1 프로젝트 설계 계약과 프롬프트

#### 수정 파일

- `AI/src/jobis_ai/career_pipeline/contracts/project_planning.py`
- `AI/src/jobis_ai/career_pipeline/project_planning/draft.py`
- `AI/src/jobis_ai/career_pipeline/project_planning/service.py`

#### 변경

- `PlannedProjectTask`에 `dependsOnTaskKeys`를 추가해 과제 DAG를 명시한다.
- 프로젝트 업무를 먼저 설계하고 직접 역량을 뒤에서 연결하도록 생성 계약을 분리한다.
- Spring Boot 프로젝트처럼 핵심 framework가 프로젝트 목적에 있는데 직접 역량에서 빠진 결과를
  거부한다.
- 공고와 프로젝트에서 실제로 사용하지 않는 Redis·Kafka 등을 임의 필수 역량으로 넣지 못하게 한다.
- 백엔드 프로젝트의 HTML·CSS·JavaScript는 결과물 시연에 정말 필요한 경우에만 권장 또는 확장으로
  두고 무조건 필수로 만들지 않는다.
- 존재하지 않는 capability key, 과제 순환 의존성, `REQUIRED`가 `EXTENSION`에 의존하는 결과를
  계약 오류로 거부한다.

### 7.2 로드맵 section membership 수정

#### 수정 파일

- `AI/src/jobis_ai/career_pipeline/contracts/roadmap.py`
- `AI/src/jobis_ai/career_pipeline/roadmap/service.py`
- `AI/src/jobis_ai/career_pipeline/roadmap/draft.py`

#### 새 파일

- `AI/src/jobis_ai/career_pipeline/roadmap/chaptering.py`

#### 변경

- `_section_memberships()`에서 `requirementId` 교집합으로 과제 소속을 확장하는 조건을 제거한다.
- 과제 소속은 해당 과제의 직접 `capabilityKeys` 일치로만 만든다.
- membership의 `targetRef`는 회사 ID가 아니라 `직무 레인 + 경력 단계`를 가리킨다.
- 챕터는 과제명이 아니라 capability `kind`, `technologyKey`, 선수 깊이를 이용한 안정적인 범주로
  만든다.
- 기본 범주는 공통 기초, 언어·프레임워크, HTTP·API·데이터베이스, 테스트·품질,
  배포·운영, 도메인 심화다.
- 새 기술명을 모두 하드코딩하지 않는다. 공용 그래프의 기술 종류와 관계로 분류하고 분류 불가
  항목은 운영자 검토 후보로 남긴다.

### 7.3 Capability Graph 정비

#### 새 파일

- `C:\jobiss-capability-graph-lab\data\seed.v2.yaml`

#### 수정 파일

- `C:\jobiss-capability-graph-lab\src\jobis_capability_graph\validator.py`
- `C:\jobiss-capability-graph-lab\tests\test_validator.py`
- `C:\jobiss-capability-graph-lab\tests\test_service.py`
- `scripts/start-capability-graph.ps1`

#### 변경

- 기존 `seed.v1.yaml`은 과거 버전 재현을 위해 수정하지 않는다.
- 트랜잭션 원자성, 멱등 처리, 동시 갱신 제어와 상태 전이는 일반 백엔드 역량으로 둔다.
- 가상재화 지갑·원장, 게임 구매 상태와 취소 정합성은 게임 결제 도메인 적용으로 둔다.
- 일반 역량에서 도메인 적용으로 이어지는 관계를 추가한다.
- project template은 참고·승인 자산이며 새 회사 공고를 기존 이스트게임즈 template에 강제로 맞추지
  않는다.

이 단계는 현재 중복 투영 버그 수정의 선행조건이 아니다. 먼저 계약과 투영을 고친 뒤 그래프 콘텐츠를
additive 버전으로 확장한다.

### 7.4 백엔드 커리어 그래프 합성

#### 수정 파일

- `backend/src/main/java/com/jobiss/analysis/v3/V3RoadmapCompiler.java`
- `backend/src/main/java/com/jobiss/analysis/v3/V3RoadmapService.java`
- `backend/src/main/java/com/jobiss/analysis/v3/V3RoadmapController.java`
- `backend/src/main/java/com/jobiss/analysis/v3/V3ProjectProgressService.java`

#### 새 파일

- `backend/src/main/java/com/jobiss/analysis/v3/V3JourneyProjectionService.java`
- `backend/src/main/java/com/jobiss/analysis/v3/V3ProjectTaskProgressService.java`
- `backend/src/main/java/com/jobiss/analysis/v3/V3ProjectTaskController.java`
- `backend/src/main/resources/db/migration/V63__project_task_progress.sql`

#### 변경

- canonical roadmap node·relation은 정본으로 유지하고 메인 지도 표현은 별도 journey projection으로
  생성한다.
- 동일 canonical capability를 재사용하되 직무별 membership은 병합한다.
- 같은 직무·진입 단계의 적절한 회사 기회를 병렬 분기로 묶는다.
- 관련 취업을 여러 진입 기회의 공통 경력 시작점으로 연결한다.
- 경력직 프로젝트와 기회를 관련 `EXPERIENCE_INTERVAL` 뒤에 둔다.
- 과거 published roadmap은 자동 변형하지 않고 새 분석은 차이 proposal을 만든다.
- 프로젝트 과제 상태와 결과물 증거를 사용자 단위로 저장하고 RLS를 적용한다.

### 7.5 프론트 메인 지도와 상세

#### 수정 파일

- `frontend/src/types.ts`
- `frontend/src/api.ts`
- `frontend/src/roadmap/v3-adapter.ts`
- `frontend/src/roadmap/journey.ts`
- `frontend/src/components/JourneyMap.vue`
- `frontend/src/views/CareerMapView.vue`

#### 변경

- 새 roadmap은 백엔드의 journey projection을 사용한다.
- `v3-adapter.ts`의 신규 경로는 비즈니스 순서와 경력 위치를 만들지 않고 타입 변환만 담당한다.
- 과거 roadmap version은 기존 adapter fallback으로 계속 열 수 있다.
- 프로젝트 과제명을 메인 `MILESTONE`으로 만들지 않는다.
- 메인 지도에는 학습 챕터, 프로젝트, 회사 기회, 취업, 경력 구간만 표시한다.
- 프로젝트 drawer에는 과제 DAG, 직접 역량, 선수 역량, 완료 조건, 결과물과 검증 상태를 표시한다.
- 현재 듀오링고풍 파란색 UI, 확대·축소, 레인·분기 표현은 유지한다.

## 8. 마이그레이션과 버전 정책

- 기존 published roadmap과 사용자 검증 상태를 삭제하거나 초기화하지 않는다.
- 기존 초안은 기존 계약으로 볼 수 있게 유지하되 새 알고리즘으로 적용하지 않는다.
- 새 분석은 새 proposal을 만들고 사용자가 미리보기 후 적용한다.
- Capability Graph 새 버전이 배포돼도 과거 roadmap의 `graphVersion`은 유지한다.
- 범위가 넓어진 capability는 기존 완료를 지우지 않고 부족한 범위만 재검증 후보로 만든다.
- 개발 DB 초기화는 이 수정의 필수 단계가 아니며 사용자의 별도 요청이 있을 때만 수행한다.

## 9. 자동 테스트 계획

### AI

- `AI/tests/career_pipeline/test_project_planning.py`
- `AI/tests/career_pipeline/test_roadmap_draft.py`
- `AI/tests/career_pipeline/test_roadmap_contract.py`
- `AI/tests/career_pipeline/test_analysis_pipeline.py`

검증 내용:

- 과제의 직접 역량만 task membership에 들어간다.
- 공유 requirement 때문에 18~25개 역량이 모든 과제에 복제되지 않는다.
- Spring 프로젝트는 필요한 Spring 역량을 가진다.
- 프로젝트는 하나이며 과제는 상세 배열로 유지된다.
- 과제 DAG와 필수·권장·확장 의존 규칙을 지킨다.

### Spring

- `backend/src/test/java/com/jobiss/analysis/v3/V3RoadmapCompilerTest.java`
- `backend/src/test/java/com/jobiss/analysis/v3/V3ProjectProgressServiceTest.java`
- 새 파일: `backend/src/test/java/com/jobiss/analysis/D048ProjectCenteredJourneyTest.java`
- 새 파일: `backend/src/test/java/com/jobiss/analysis/v3/V3ProjectTaskProgressServiceTest.java`

검증 내용:

- 이스트게임즈와 네이버웹툰을 하나의 커리어 그래프로 합친다.
- 이스트게임즈를 네이버웹툰의 유일한 선행 회사로 만들지 않는다.
- 관련 취업과 24~48개월 경력 구간을 보존한다.
- 같은 역량의 진행 상태를 재사용한다.
- 프로젝트 과제 상태와 증거가 사용자별로 격리된다.

### 프론트

- `frontend/tests/v3-adapter.test.ts`
- 새 파일: `frontend/tests/unit/journey-map.spec.ts`
- 새 파일: `frontend/tests/e2e/estgames-naver-journey.spec.ts`

검증 내용:

- 메인 지도에 프로젝트 과제 다섯 개가 챕터 다섯 개로 나오지 않는다.
- 회사당 프로젝트 노드 하나와 기회 노드 하나가 나온다.
- 프로젝트 상세에는 모든 과제와 원자 역량이 보인다.
- entry 기회와 경력 기회가 취업·경력 구간을 통해 연결된다.
- 새로고침, 초안 미리보기와 적용 후에도 같은 그래프를 재현한다.

## 10. 구현 순서와 게이트

1. 이 문서와 D048 fixture를 코드 변경 전 수용 기준으로 고정한다.
2. 프로젝트 과제와 직접 역량 계약을 수정한다.
3. `_section_memberships()`의 requirement 기반 과잉 배치를 제거한다.
4. AI 계약 schema와 fixture를 다시 생성한다.
5. 백엔드의 회사·취업·경력 합성과 journey projection을 구현한다.
6. 프론트를 새 projection에 연결하고 프로젝트 상세를 분리한다.
7. 프로젝트 과제 진행 상태와 RLS를 추가한다.
8. 이스트게임즈 단독 시나리오를 검증한다.
9. 네이버웹툰을 추가해 하나의 커리어 그래프 시나리오를 검증한다.
10. AI 보안 4년 공고를 추가해 직무 레인과 공유 역량 투영을 검증한다.
11. 동작이 고정된 후 Capability Graph `seed.v2`를 additive로 확장한다.

각 단계는 관련 단위 테스트와 fixture가 통과한 뒤 다음 단계로 진행한다. 프론트만 먼저 임의 수정하거나
그래프 seed를 전면 재작성하지 않는다.

## 11. 완료 기준

- 이스트게임즈 단독 등록 시 공통 기초→백엔드 학습→이스트게임즈 프로젝트→기회가 보인다.
- 네이버웹툰 추가 시 별도 로드맵이 아니라 같은 그래프의 2~4년 경력 단계 뒤에 추가된다.
- 이스트게임즈 외 관련 주니어 취업도 같은 경력 시작점으로 연결할 수 있다.
- 원자 역량과 프로젝트 과제는 메인 경로를 압도하지 않고 상세에서 확인할 수 있다.
- 같은 Java·Spring 역량은 회사마다 새 진행 상태를 만들지 않는다.
- 같은 Docker 역량은 백엔드와 보안 문맥에 표시되더라도 완료 상태를 공유한다.
- 모든 표시 노드는 공고 요건, 프로젝트 과제 또는 Capability Graph 선수관계까지 역추적할 수 있다.
- 기존 published roadmap과 검증 증거는 새 버전 배포로 자동 변형되거나 사라지지 않는다.

## 12. 이번 수정에서 하지 않는 것

- SVG의 좌표와 디자인을 데이터 정본으로 저장하지 않는다.
- 모든 기술 이름을 코드 taxonomy에 나열하지 않는다.
- AI에게 그래프 병합과 화면 좌표를 전부 맡기지 않는다.
- 회사 프로젝트 완료만으로 경력·학위·자격 조건까지 충족했다고 판단하지 않는다.
- 기존 사용자 데이터와 로드맵을 초기화하지 않는다.
- `AI-v3` 비교 폴더 삭제와 내부 `V3*` 이름 정리는 별도 리팩터링으로 남긴다.

## 13. 구현 결과

- AI 프로젝트 과제에 안정적인 `taskKey`와 `dependsOnTaskKeys`를 추가하고 DAG, 미등록 참조,
  `REQUIRED → EXTENSION` 의존을 계약에서 거부한다.
- 과제 membership은 직접 `capabilityKeys`로만 만들며 공유 `requirementId` 때문에 역량이 모든 과제에
  복제되지 않는다.
- 과제명은 메인 학습 챕터로 승격하지 않고, 안정적인 학습 범주와 직무·경력 단계 membership을
  사용한다.
- 기존 `V3RoadmapCompiler`가 회사 기회, 관련 취업, 경력 구간과 다음 경력직 기회를 canonical
  relation으로 합성한다. 별도 이름뿐인 projection service를 만들지 않고 이 컴파일러를 결정적 합성
  경계로 유지했다.
- 프론트 adapter는 명시적인 `journeyStageRef`와 실제 relation을 소비한다. rank 기반 단계 추론은
  과거 snapshot 호환 fallback으로만 남겼다.
- 프로젝트 drawer에서 과제, 직접 역량, 그래프에서 조회한 선수 역량, 완료 기준, 상태와 증거를
  확인한다. 과제 상태와 증거는 사용자별 PostgreSQL 테이블과 RLS로 격리한다.
- 프로젝트 과제 API는 응집도를 위해 기존 `V3RoadmapController` 아래에 두었다. 별도 controller를
  만드는 것 자체를 완료 조건으로 삼지 않았다.
- Capability Graph의 기존 validator를 재사용하고 `seed.v1`을 보존한 채 `seed.v2`를 additive로
  추가했다. 일반 백엔드 원자 역량과 게임 결제 도메인 적용 역량을 분리했다.
- 공개 `company-project-blueprint` JSON Schema와 예제를 단일 AI 계약에 맞췄다.

세부 구현·검증 기록은 `docs/26-d048-project-centered-career-journey-implementation.md`를 정본으로
사용한다. 실제 Codex CLI로 이스트게임즈와 네이버웹툰 공고를 연속 분석하는 라이브 수용 검사는
사용자 환경에서 남아 있으므로 상태를 `LIVE_ACCEPTANCE_PENDING`으로 둔다.
