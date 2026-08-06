# 04. 단계별 구현 체크리스트

- 원칙: 이전 단계의 완료 게이트를 통과하기 전 다음 단계의 서비스 연결을 시작하지 않는다.
- 현재 상태: Phase 0~7 완료, Phase 8 AI 측 pipeline·통합 참조 compiler 완료
- 체크 표시 기준: 코드가 존재하는 것이 아니라 자동 테스트와 수동 수용 기준을 모두 통과한 상태

## 확정된 제품 결정

- [x] 기존 실제 AI 실험판은 기준선과 롤백 대상으로 보존한다.
- [x] 새 의미 판정 코어는 별도 작업공간에서 만든다.
- [x] URL·이미지 추출 결과는 사용자가 확인한 뒤 분석한다.
- [x] 공고는 복수 `positions[]`를 지원한다.
- [x] AI는 의미 후보와 근거를 제안하고 규칙은 계약·무결성·계산을 담당한다.
- [x] taxonomy는 정규화·중복·신규 후보 관리에 사용하고 단어로 최종 직무를 확정하지 않는다.
- [x] 공고 분석과 사용자 적합도, 기술 정규화, 로드맵 생성을 분리한다.
- [x] 사용자 주장·근거·검증 완료를 서로 다른 상태로 저장한다.
- [x] 로드맵은 초안으로 생성하며 사용자 승인 전 공개 지도를 바꾸지 않는다.
- [x] 기존 AI가 잘 만든 provider·orchestrator·trace·도구·RAG 기반을 선별 재사용한다.
- [x] 공용 역량 지식 그래프는 별도 작업에서 구축하고 v3는 승인된 그래프를 조회한다.

## 구현 기본값

다음은 별도 이견이 생기기 전까지 사용할 기본값이다.

- Python 3.12, FastAPI, Pydantic 기반 계약
- AI 서버는 서비스 PostgreSQL 자격 증명을 가지지 않음
- Spring이 사용자 권한·RLS·큐·공용 캐시·로드맵 버전의 정본
- AI 진행 이벤트는 NDJSON stream과 상태 조회 API를 함께 제공
- 추가 질문은 한 번에 하나, 동일 ambiguity 반복 금지
- 사용자 확인 전에는 source extraction까지만 자동 실행
- 공고 원문과 구조화 결과의 revision을 덮어쓰지 않고 새 버전으로 저장
- 신규 기술은 누락하지 않고 운영자 검토 후보로 보존
- 내부 chain-of-thought는 저장하거나 UI에 노출하지 않음
- Git 커밋과 Push는 사용자의 별도 요청 전까지 수행하지 않음

## Phase 0. 기준선과 설계 동결

### 산출물

- [x] 현재 시스템 기준선 작성
- [x] 재사용·개선·교체 매트릭스 작성
- [x] 목표 아키텍처 작성
- [x] 핵심 계약과 상태 전이 초안 작성
- [x] 회귀 시나리오 fixture 출처와 기대 결과 확정
- [x] 구현·통합·롤백 계획 최종 검토
- [x] 문서 간 용어와 enum 일관성 검사

### 완료 게이트

- 모든 기존 사용자 진입점이 기준선에 기록돼 있다.
- 기존 팀 자산 중 무엇을 재사용하고 무엇을 교체하는지 모호한 항목이 없다.
- 공고 수집부터 로드맵 초안까지 모든 단계의 입력과 출력이 정의돼 있다.
- 실제로 방향을 바꾸는 미확정 제품 결정이 문서에 숨겨져 있지 않다.

Phase 0 fixture는 `contract-fixtures/regression-corpus.json`에 40건(P0 22건)으로
고정했으며 `scripts/validate-fixtures.py`가 문서의 케이스 ID, 중복, 출처, 개인정보 포함 여부와
기본 구조를 검사한다.

## Phase 1. 독립 스캐폴드와 계약 검증

### 구현

- [x] `ai_v3` Python package 생성
- [x] FastAPI health·version endpoint 생성
- [x] Pydantic 계약 정의
- [x] JSON Schema export 생성
- [x] Java DTO 호환 검증 fixture 생성
- [x] 계약 버전 negotiation 구현
- [x] 구조화 응답 validator와 제한된 repair 구현
- [x] 공통 error envelope 구현
- [x] request ID·trace ID 전파 구현
- [x] 환경 설정과 비밀값 검증 구현

### 자동 검증

- [x] 모든 예시 JSON이 Pydantic과 JSON Schema를 모두 통과
- [x] 잘못된 enum·누락 evidence·깨진 참조가 거부됨
- [x] unknown 필드 정책이 계약 버전별로 일관됨
- [x] 비밀값 누락 시 명시적 기동 오류
- [x] AI 서버에 DB URL이 없어도 정상 기동

### 완료 게이트

- LLM 없이 계약 테스트가 전부 통과한다.
- Spring과 Python이 같은 fixture를 읽고 같은 필드 의미를 갖는다.
- 기존 서비스나 DB를 수정하지 않고 독립 실행할 수 있다.

Phase 1 검증은 `scripts/check-phase1.ps1`로 실행하며 45개 테스트, 9개 공개 Schema와
예시의 양방향 일치, 실제 Uvicorn health·contract smoke를 통과한다.

## Phase 2. 공고 수집과 원문 검증

### 구현

- [x] `SourceDocument` 생성 API
- [x] URL 직접 텍스트 수집 adapter 이식
- [x] HTML·iframe 수집 adapter 이식
- [x] 이미지 VLM adapter 이식(OCR provider 추가는 필요 시 같은 port 사용)
- [x] 붙여넣기 원문 adapter 구현
- [x] extraction segment·source locator 보존
- [x] 이미지 타일 overlap dedup 구현
- [x] 수집 경고와 신뢰도 보존
- [x] 추출 결과 교정·확인 API
- [x] `VerifiedPostingSnapshot` 생성 API
- [x] 원문 revision과 hash 계산
- [x] 사용자 확인 전 분석 요청 차단 gate
- [x] URL 사설망·자격증명·응답 크기 제한

### 자동 검증

- [x] 같은 입력과 extractor 버전은 같은 extraction cache key
- [x] 이미지 타일 중복 문장이 raw text에서 제거되고 원본 segment 관계는 표시됨
- [x] 확인 snapshot의 모든 문장에 char locator가 생기고 구조화 결과는 그 evidence ID만 사용
- [x] 낮은 신뢰도는 실패가 아니라 확인 필요 상태
- [x] snapshot ID와 `previousSnapshotId`가 불변 이력 저장을 지원함
- [x] 확인되지 않은 snapshot으로 분석 요청 시 `SOURCE_NOT_VERIFIED`

`source locator`와 의미 필드의 참조 검증은 의미 필드가 생기는 Phase 3 validator에서 완료한다.
snapshot의 실제 영속 보존은 Spring 연결이 이루어지는 Phase 8 수용 테스트에서 재검증한다.

### 수동 수용

- [ ] 채팅과 채용공고 페이지가 같은 추출 API를 사용
- [ ] URL 입력 후 추출 원문을 보고 수정·확인 가능
- [ ] 이미지 원본과 경력·직무 근거 영역을 함께 확인 가능
- [ ] 새로고침 후에도 확인 대기 상태 복원

### 완료 게이트

- 잘못 추출된 `신입/19년`을 사용자가 분석 전에 교정할 수 있다.
- 사용자 확인 없이 적합도 작업이 큐에 들어가지 않는다.

## Phase 3. 복수 포지션 공고 구조화

### 구현

- [x] `StructuredPosting` 생성 agent
- [x] `positions[]`와 shared conditions 추출
- [x] 포지션별 role·experience·responsibility 추출
- [x] 필수·우대·정보성 요건 구분
- [x] 복합 문장을 `AtomicRequirement`로 분해
- [x] 모든 의미 필드에 verified evidence ID 연결
- [x] confidence와 warnings 보존
- [x] taxonomy role catalog는 후보 제공·known ID 검증에만 사용
- [x] 사전에 없는 role을 `NEW_CANDIDATE`로 보존
- [x] 의미 규칙이 LLM 후보를 키워드로 덮어쓰는 경로 금지
- [x] Claude CLI와 OpenAI-compatible JSON provider port
- [x] 계약 오류 제한 재시도와 공급자 오류 명시화

### 자동 검증

- [x] 모집 직무와 협업 대상 언급을 구분
- [x] 포지션별 경력 조건이 서로 섞이지 않음
- [x] 회사 업력·서비스 연수를 요구 경력으로 사용하지 않음
- [x] 필수·우대 문장 원문과 obligation 구조 보존
- [x] evidence 없는 확정 필드는 validator에서 거부
- [ ] 동일 snapshot·모델·프롬프트 버전의 반복 안정성 측정

### 완료 게이트

- 회귀 시나리오의 직무·경력 P0 케이스를 모두 통과한다.
- 복수 포지션 공고를 단일 `roleCategory`로 축약하지 않는다.

직무·경력·요건의 고유 실모델 회귀 10건은 Claude Code `sonnet`에서 모두 통과했다. 최초 실패
2건은 검증기를 완화하지 않고 nullable 전체 제목과 responsibility의 `sourceText/atomicText`
분리로 계약을 보완해 해결했다. 상세는 `08-phase3-live-evaluation.md`에 기록한다.

## Phase 4. 모호함 해소와 질문

### 구현

- [x] 구조 기반 ambiguity detector
- [x] source verification 질문과 position 선택 질문 구분
- [x] 신입/경력 동시 모집의 experience track 질문
- [x] user evidence 질문
- [x] 질문별 candidate·evidence·blocking 이유 저장
- [x] 같은 ambiguity ID 안정화와 반복 금지
- [x] 답변 이력을 요청 계약과 verified snapshot 기반 ID에 연결
- [x] 구조로 선택지를 확정할 수 없는 항목은 질문을 만들지 않고 unknown 보존

### 자동 검증

- [x] 실제 복수 직무일 때만 포지션 선택 질문
- [x] 백엔드 공고의 “프론트엔드와 협업”은 질문을 만들지 않음
- [x] 같은 답변 후 같은 ambiguity ID가 반복되지 않음
- [ ] “없음” 답변과 미입력을 구분
- [x] 질문 흐름에서 임의의 not_met 생성 금지

`user evidence` 질문은 필수 경력·자격처럼 지원 가능성을 바꾸는 형식 요건에만 한 번에 하나씩
생성한다. 명시적인 “없음”은 `NOT_MET`, 미입력과 “모름”은 `UNKNOWN`으로 구분한다.

### 완료 게이트

- 추가 질문이 결과를 바꿀 때만 나타난다.
- 질문 후 작업이 정확한 revision에서 재개된다.

## Phase 5. 사용자 적합도 분석

### 구현

- [x] 확인된 커리어 조각만 기본 근거로 사용
- [x] `CLAIMED/EVIDENCED/VERIFIED` 분리
- [x] requirement별 관련 근거 후보 생성
- [x] 관련성 confidence와 reason 저장
- [x] unknown과 not_met 분리
- [x] 형식적 지원 자격과 기술 준비도 분리
- [x] 서버 정책 기반 필수·우대 점수 계산 입력 생성
- [x] verdict proposal과 판정 근거 생성
- [x] 이의제기·재검토용 audit payload 생성

### 자동 검증

- [x] 기술명 한 번 언급만으로 VERIFIED가 되지 않음
- [x] 자료 없음이 NOT_MET으로 계산되지 않음
- [x] 경력·자격증 같은 형식 요건과 학습 가능한 기술 공백이 분리됨
- [x] 다른 사용자의 근거가 공용 캐시에 포함되지 않음
- [x] 같은 공고라도 사용자별 평가는 독립적임

### 완료 게이트

- 판정의 각 문장이 공고 근거와 사용자 근거를 모두 추적할 수 있다.
- 준비도와 로드맵 완료가 같은 상태값을 공유하지 않는다.

## Phase 6. 공용 기술 정규화

### 구현

- [x] exact canonical key lookup
- [x] alias normalization
- [x] AI 유사 후보 제안
- [x] 신규 기술 후보 생성
- [x] 기술·업무·도메인·자격·정성요건 분리
- [x] 운영자 검토 큐 계약
- [x] 병합·분리·보류·되돌리기 감사 기록
- [ ] 신규 role 후보 검토도 같은 패턴 적용

### 자동 검증

- [x] Java와 JavaScript가 혼합되지 않음
- [x] 새로운 기술이 `기술 활용` 같은 일반 노드로 조용히 바뀌지 않음
- [x] 정성적 요건이 학습 기술 후보가 되지 않음
- [x] AI가 공용 기술을 자동 병합하지 못함
- [x] 사용자 요청은 운영자 검토 완료를 기다리지 않음

### 완료 게이트

- taxonomy에 없는 기술도 손실 없이 저장된다.
- 공용 정규화와 사용자 진행 상태가 분리된다.

## Phase 7. 로드맵 초안 생성

### Phase 6.5 선행조건 · 공용 역량 지식 그래프 연동

- [ ] 별도 `C:\jobiss-capability-graph-lab`의 계약과 버전 확인
- [x] canonical capability 조회 API adapter
- [x] 필수·권장·조건부 선행관계 역방향 조회 adapter
- [x] 직무·언어·목표 수준 조건 전달
- [x] 사용자 VERIFIED 노드 제외 입력
- [x] 그래프 응답의 출처·검토 상태·버전 검증
- [x] 그래프 장애 시 AI가 임의 선행관계를 공용 정답으로 생성하지 않음

Phase 6.5는 별도 세션의 그래프 결과물을 서비스에 직접 병합하는 단계가 아니다. 먼저 계약과
회귀 테스트로 검증한 뒤 v3의 읽기 전용 port로 연결한다.

2026-08-04 확인 시 `C:\jobiss-capability-graph-lab`은 아직 존재하지 않았다. 따라서 외부 계약과
실제 버전 확인은 미완료 상태로 남겼다. v3에는 `jobis.capability-graph.v1alpha1` 수신 계약,
HTTP read-only port, 버전·내용 해시·출처 참조·승인 상태·hard prerequisite 순환 검증을 먼저
구현했다.

### 구현

- [x] 학습 가능한 requirement만 curriculum 입력으로 선택
- [x] 기술별 level·scopeDefinition 제안
- [x] 기존 canonical node 재사용 후보
- [x] 선행관계와 보너스 확장 후보
- [x] 포지션별 회사 맞춤 프로젝트 제안
- [x] 경력 관문 입력 생성
- [x] excluded requirement와 이유 저장
- [ ] 백엔드 그래프 compiler 연결
- [ ] 미리보기·적용·취소 상태 연결

### 자동 검증

- [x] 정성적 조건이 노드로 생성되지 않음
- [x] 공고 문장 전체가 기술 노드 제목이 되지 않음
- [x] 같은 canonical skill은 한 번만 나타남
- [x] 완료 상태가 로드맵 재배치 후에도 유지됨
- [x] 회사별 필수·우대 관계가 노드 메타데이터에 남음
- [x] 경력직 공고가 관련 직무 경력 관문 입력을 가짐
- [x] 게임 서버와 웹 백엔드 경로가 직무 구조에 따라 구분됨
- [x] AI가 좌표나 공개 버전을 직접 확정하지 않음

### 완료 게이트

- 실제 실패 공고들로 생성한 로드맵을 사용자가 한눈에 이해할 수 있다.
- 초안을 취소하면 공개 지도와 사용자 진행 상태가 바뀌지 않는다.

## Phase 8. 서비스 통합과 UI

### AI 측 통합 코어

- [x] 확인된 snapshot부터 로드맵 초안까지 단일 pipeline 계약
- [x] 질문 발생 시 이후 단계 호출 없이 waiting 결과 반환
- [x] 실제 단계 기반 NDJSON progress stream
- [x] graph와 catalog 독립 버전 호환 검증
- [x] 기존 진행 상태와 회사 노드를 보존하는 참조 compiler
- [x] 같은 직무의 신입 회사와 경력 관문·경력 회사 순서 관계 생성
- [x] 실제 Claude 전체 pipeline의 14개 단계 이벤트와 DRAFT 결과 검증

이 참조 compiler는 Spring이 포팅할 의미 기준이며 AI API가 공개 지도를 적용한다는 뜻이 아니다.
기존 실험판 Spring·DB·Vue는 아직 변경하지 않았다.

### 구현

- [ ] `AI_PROVIDER=legacy|v3|shadow` 지원
- [ ] 채팅 진입점 연결
- [ ] 채용공고 페이지 진입점 연결
- [ ] 원문 확인 카드 UI
- [ ] 포지션 선택 카드 UI
- [ ] 실제 단계 기반 진행 시각화
- [ ] 상세 실행 과정 접기/펼치기
- [ ] 상태 조회와 새로고침 복원
- [ ] 취소·재시도·서버 재시작 복구
- [ ] 분석 결과와 로드맵 초안 명칭 분리
- [ ] 운영자 신규 기술·이상 추출 검토 화면

### 자동 검증

- [ ] 채팅과 공고 페이지가 같은 공고에 같은 구조화 결과를 사용
- [ ] 페이지 이동과 새로고침 후 작업 상태 일치
- [ ] 취소된 작업의 늦은 응답이 성공으로 덮어쓰지 못함
- [ ] stale RUNNING 작업 lease 복구
- [ ] 동일 action 재전송이 중복 작업을 만들지 않음
- [ ] CORS·인증·RLS 회귀 없음

### 완료 게이트

- 사용자 시나리오 E2E 테스트가 두 진입점 모두 통과한다.
- 기존 프로젝트로 즉시 롤백할 수 있다.

## Phase 9. 비교 평가와 전환

- [ ] legacy와 v3에 같은 fixture를 실행
- [ ] 필드별 정확성·근거 완전성·안정성 비교
- [ ] 기존이 맞고 v3가 틀린 사례 분석
- [ ] 기존이 틀리고 v3가 고친 사례 기록
- [ ] 실제 모델 비용과 p50/p95 시간 측정
- [ ] shadow mode에서 개인정보 중복 전송 정책 확인
- [ ] 운영자·개발자 검토
- [ ] 제한된 내부 사용자에 v3 활성화
- [ ] 오류율·질문율·수정률 관찰
- [ ] 기준 통과 후 기본 provider 전환
- [ ] legacy 제거 여부는 별도 결정

### 최종 완료 게이트

- P0 회귀 오류 0건
- 계약 참조 무결성 100%
- 사용자 확인 없이 원문 분석 0건
- 공고 구조와 사용자 평가의 데이터 혼합 0건
- 기존 버전으로의 롤백 절차 실검증
- 운영자 감사와 사용자 승인 기록 확인
