# 06. 통합·전환·롤백 계획

- 목표: 기존 실제 AI를 손상시키지 않고 v3를 병행 검증한 뒤 선택적으로 전환한다.
- 원칙: additive migration, feature flag, 사용자 승인, 즉시 롤백

## 1. 작업공간 전략

### 설계·초기 구현

```text
C:\jobiss-service-ai-v3-lab
├─ README.md
├─ docs/
├─ ai-v3/                 # Phase 1부터 생성
│  ├─ src/jobis_ai_v3/
│  ├─ tests/
│  ├─ evals/
│  └─ pyproject.toml
├─ contract-fixtures/
└─ scripts/
```

기존 `C:\jobiss-service-real-agent-lab`은 비교 기준으로만 사용한다. 새 코드가 기존 폴더의
절대경로 import에 의존하지 않도록 한다.

### 재사용 코드 이식 원칙

1. 재사용 매트릭스에서 `REUSE` 또는 `ADAPT`로 승인된 모듈만 가져온다.
2. 가져오기 전에 공개 입력·출력, 외부 상태, 환경 변수, 하위 프로세스를 문서화한다.
3. 의미 판정 규칙이 함께 딸려오지 않는지 dependency graph를 확인한다.
4. 원본 경로·기준 commit 또는 snapshot hash를 provenance 파일에 기록한다.
5. 원본 테스트를 함께 가져오되 새 계약에 맞춘 adapter 테스트를 추가한다.
6. 팀 코드의 저작권·작성자 기록과 Git 이력은 실제 저장소 통합 시 보존한다.

기존 코드를 통째로 복사한 뒤 불필요한 규칙을 지우는 방식은 사용하지 않는다. 필요한 기반을
작은 단위로 가져오고 새 인터페이스 뒤에 둔다.

## 2. 런타임 병행 구조

```text
Spring Backend
  └─ AiGateway
      ├─ LegacyAiClient
      ├─ V3AiClient
      └─ ShadowComparator
```

환경 설정 제안:

```dotenv
AI_PROVIDER=legacy          # legacy | v3 | shadow
LEGACY_AI_BASE_URL=http://127.0.0.1:8200
V3_AI_BASE_URL=http://127.0.0.1:8300
AI_SHADOW_STORE_RESULTS=false
```

### legacy

현재 사용자 응답과 저장 흐름을 그대로 사용한다.

### v3

새 계약과 확인 흐름만 사용한다. v3가 지원하지 않는 기능을 조용히 legacy로 성공 처리하지
않고 명시적인 capability 상태를 반환한다.

### shadow

- 사용자에게 보여주는 결과는 지정된 primary provider 하나만 사용한다.
- 다른 provider 결과는 비교 전용이며 DB 변경과 사용자 메시지를 만들지 않는다.
- 사용자 자료를 두 공급자에 전달하는 것은 로컬·승인된 평가 환경에서만 허용한다.
- 비교 결과에는 개인정보 원문 대신 field diff와 fixture ID를 저장한다.

## 3. 기존 계약 호환 전략

새 AI 계약을 기존 `v2bridge` 응답으로 바로 축약하지 않는다. 정보 손실이 발생하기 때문이다.
Spring에 v3 DTO를 추가하고, 프론트엔드가 전환되는 동안 필요한 최소 표시만 compatibility
view로 제공한다.

```text
v3 native contract
  ├─ v3 backend persistence
  ├─ v3 UI
  └─ legacy compatibility view (읽기 전용, 손실 명시)
```

호환 view에서 표현할 수 없는 값은 다음처럼 처리한다.

- 복수 포지션: 사용자가 선택한 포지션만 legacy view에 투영
- evidence spans: legacy 설명문으로 합치지 않고 상세 링크로 보존
- 신규 기술 후보: 기존 기술 ID를 임의 생성하지 않고 pending 상태
- 사용자 확인 상태: legacy 분석 실행 전 별도 gate로 강제

## 4. DB 마이그레이션 원칙

- 기존 테이블과 컬럼을 삭제하거나 의미를 바꾸지 않는다.
- v3용 source document, snapshot, position, evidence, ambiguity, analysis revision을 additive로 추가한다.
- 모든 사용자 테이블에 RLS와 소유권 인덱스를 적용한다.
- 공용 구조와 사용자별 평가를 다른 테이블 또는 명확한 소유 경계로 분리한다.
- migration은 실제 PostgreSQL에서 실행·롤백 검증한다.
- 기존 공고를 자동으로 v3 verified 상태로 승격하지 않는다.
- 기존 분석은 `LEGACY_IMPORTED`로 표시하고 필요할 때 사용자 재확인을 통해 v3로 전환한다.

예상 논리 엔터티:

```text
source_documents
source_document_segments
verified_posting_snapshots
posting_analysis_revisions
posting_positions
posting_requirements
analysis_ambiguities
analysis_answers
user_fit_assessments
capability_normalization_candidates
roadmap_proposals
ai_progress_events
```

실제 테이블명과 기존 스키마 재사용 여부는 Phase 8 전에 ERD와 migration review로 확정한다.

## 5. API 전환 순서

### 5.1 읽기 전용 준비

- v3 health·capabilities·contract version 조회
- SourceDocument 생성과 조회
- snapshot 확인과 수정
- 구조화 결과 조회
- progress snapshot과 event 조회

### 5.2 신규 분석 흐름

- 채용공고 페이지의 새 등록 한정으로 v3 선택 옵션 제공
- 내부 사용자만 활성화
- 결과는 기존 로드맵에 자동 반영하지 않음
- legacy와 field diff 검토

### 5.3 채팅 연결

- URL+분석 요청을 SourceDocument 생성으로 연결
- 확인 카드 응답 후에만 v3 분석 시작
- 기존 `ANALYZE_POSTING` action은 verified snapshot ID가 없으면 실행 거부
- 포지션 선택과 user evidence 질문을 대화 상태에 연결

### 5.4 로드맵 연결

- v3 RoadmapProposal을 기존 graph compiler의 별도 입력 adapter로 전달
- 공개 버전에는 기존과 동일한 사용자 적용 버튼 사용
- legacy와 v3 proposal을 같은 로드맵에 동시에 적용하지 않음

## 6. 데이터와 캐시 전환

- 기존 exact duplicate 판정은 유지한다.
- v3 공통 분석 캐시는 verified snapshot hash와 interpreter version을 포함한다.
- 같은 원문이라도 사용자가 다른 포지션을 선택하면 position 분석은 분리한다.
- 추가 답변과 원문 정정이 바뀌면 새 revision을 만든다.
- 사용자 적합도 캐시는 career evidence revision과 competency verification revision을 포함한다.
- legacy 분석 캐시를 v3 분석 캐시로 간주하지 않는다.

## 7. 관찰 가능성

모든 v3 작업에 다음을 남긴다.

- request ID, trace ID, user-scoped job ID
- provider, model, prompt version, contract version
- source revision, selected position ID
- 단계별 시작·종료·경과 시간
- LLM 호출 수와 재시도 수
- contract validation 및 repair 횟수
- 질문 수, 사용자 원문 수정 여부
- 캐시 적중 범위(common/user)
- warning과 fallback 이유
- 취소·lease 만료·stale result

대시보드 지표:

- source verification 수정률
- 직무 선택 질문률과 변경률
- 경력 정정률
- 구조화 실패율
- P50/P95 분석 시간
- 사용자별·공통 캐시 적중률
- roadmap proposal 취소율
- 신규 taxonomy 후보 발생률
- legacy 대비 field diff

## 8. 단계적 롤아웃

### Stage A · fixture only

- 실제 사용자 연결 없음
- 회귀 시나리오와 공개·비식별 공고만 사용
- P0 의미 오류와 계약 오류를 먼저 제거

### Stage B · 개발자 내부

- 개발자 계정에만 v3 provider 노출
- 원문 확인부터 로드맵 초안까지 수동 검토
- 모든 diff와 수정 이유 기록

### Stage C · 제한된 실험 사용자

- 명시적으로 v3 실험을 선택한 사용자만 사용
- 로드맵 적용 전 강한 확인
- fallback은 자동 전환이 아니라 재시도 또는 legacy 재분석 선택으로 제공

### Stage D · 기본값 전환

- 수용 기준 통과 후 신규 공고에 v3 기본 적용
- 기존 분석은 그대로 유지
- legacy provider와 롤백 절차를 한 릴리스 이상 보존

### Stage E · legacy 정리 검토

- v3가 모든 필수 능력을 대체했는지 별도 감사
- 재사용 중인 팀 모듈과 보존해야 할 eval 기록 확인
- 삭제는 별도 승인과 데이터 보존 계획 이후에만 수행

## 9. 롤백

롤백은 코드 복구가 아니라 설정 전환으로 가능해야 한다.

1. 신규 v3 작업 수신 중단
2. 실행 중 작업을 취소 또는 안전 종료
3. `AI_PROVIDER=legacy` 전환
4. v3가 만든 DRAFT 로드맵은 공개하지 않고 보존
5. v3 source·snapshot·audit 데이터는 삭제하지 않음
6. 기존 공개 로드맵과 사용자 진행 상태가 바뀌지 않았는지 검사
7. 원인 해결 후 같은 fixture와 작업 revision으로 재검증

롤백 훈련에서 확인할 것:

- 채팅 자유 대화
- 공고 등록과 legacy 분석
- 기존 로드맵 조회
- 사용자 로그인과 RLS
- v3 포트가 꺼진 상태의 백엔드 health
- 실행 중 v3 작업의 사용자 표시

## 10. Git과 협업

- 현재 문서 작성 단계에서는 Git 작업을 하지 않는다.
- 구현 시작 전 실제 팀 저장소의 기준 브랜치와 작업 범위를 다시 확인한다.
- 새 기능은 `feat/ai/...` 규칙에 맞는 별도 브랜치에서 작업한다.
- 공통 계약, DB schema, 환경 변수 변경은 AI·백엔드·프론트 담당자에게 공유한다.
- 한 MR에 의미 판정, DB migration, 전체 UI 변경을 모두 넣지 않는다.
- 재사용한 팀 코드의 원본 commit과 변경 이유를 MR에 기록한다.
- prompt 변경과 해당 eval 결과를 같은 변경 단위에 포함한다.
- 공유된 원격 브랜치에 force push하지 않는다.

## 11. 전환 승인 체크

- [ ] Phase 0~8 완료 게이트 통과
- [ ] P0 회귀 0건
- [ ] 실제 모델 반복 평가 통과
- [ ] 사용자 확인 없는 분석 0건
- [ ] RLS·CORS·CSRF·action 변조 테스트 통과
- [ ] lease·취소·재시도·새로고침 복구 통과
- [ ] legacy rollback 실검증
- [ ] 운영자 신규 기술·중복 검토 가능
- [ ] 사용자 문서와 실행 스크립트 준비
- [ ] 팀 검토와 전환 승인 기록

