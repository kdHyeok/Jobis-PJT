# 07. 결정 기록

- 목적: 이미 확정한 방향을 구현 중 다시 묻거나, 과거 규칙이 이유 없이 되살아나는 것을 막는다.
- 상태 표기: `ACCEPTED`, `DEFAULT`, `DEFERRED`, `REJECTED`
- 변경 원칙: 결정이 바뀌면 기존 항목을 삭제하지 않고 새 결정과 변경 이유를 추가한다.

## D001 · 새 의미 판정 코어를 별도 작업공간에서 만든다

- 상태: `ACCEPTED`
- 결정: 기존 실제 AI 프로젝트 안에서 규칙을 하나씩 제거하지 않고 새 v3 의미 판정 코어를
  독립적으로 만든다.
- 이유: 의미 규칙이 코어, graph, v2bridge, 백엔드에 분산되어 있어 부분 수정 시 숨은 규칙이
  다시 결과를 바꿀 위험이 크다.
- 보호: 기존 실제 AI는 비교 기준과 롤백 대상으로 보존한다.

## D002 · 팀 작업은 모듈 단위로 재사용한다

- 상태: `ACCEPTED`
- 결정: provider, orchestrator, trace, source fetch, RAG, 구조 검증과 평가 하네스는 공개 계약과
  의존성을 확인한 뒤 재사용한다.
- 이유: 새로 만들 이유가 없는 검증된 기반이며, 팀 작업의 핵심 성과다.
- 금지: 기존 코드를 통째로 복사한 후 의미 규칙을 지워 나가는 방식.

## D003 · 의미 후보와 최종 무결성의 책임을 분리한다

- 상태: `ACCEPTED`
- 결정: LLM은 직무·경력·요건 후보와 원문 근거를 제안하고, 결정론적 코드는 계약·범위·참조·
  계산·권한을 검증한다.
- 이유: 계산과 권한은 재현성이 중요하지만 임의 공고의 의미는 단어 규칙으로 확정할 수 없다.
- 거부한 대안: 모든 판단을 LLM에 맡기기, 모든 의미를 키워드 규칙으로 확정하기.

## D004 · 추출된 원문은 사용자 확인 후 분석한다

- 상태: `ACCEPTED`
- 결정: URL·HTML·이미지·OCR/VLM 추출은 `SourceDocument`이며, 사용자가 확인한
  `VerifiedPostingSnapshot`만 분석 입력이 된다.
- 이유: OCR 오류가 자기 추출 텍스트를 근거로 통과하는 문제를 차단한다.
- 적용: 채팅과 채용공고 페이지 모두 같은 계약을 사용한다.

## D005 · 공고는 복수 포지션 구조다

- 상태: `ACCEPTED`
- 결정: 공고는 `positions[]`를 가지며 직무·경력·업무·필수·우대요건을 포지션별로 저장한다.
- 이유: 프론트/백엔드, 신입/경력 등이 한 공고에 함께 존재할 수 있다.
- 거부한 대안: 단일 `roleCategory`를 먼저 고른 뒤 나머지 내용을 버리는 방식.

## D006 · taxonomy는 열린 정규화 사전이다

- 상태: `ACCEPTED`
- 결정: taxonomy는 alias, canonical ID, 중복 후보를 제공한다. 사전에 없는 기술과 직무는
  `NEW_CANDIDATE`로 보존한다.
- 이유: 새로운 기술을 모두 사전에 미리 준비할 수 없으며, 단어 존재는 문맥의 최종 답이 아니다.
- 최종 권한: 공용 taxonomy 병합·분리·승인은 운영자.

## D007 · 공고 해석과 로드맵 커리큘럼을 분리한다

- 상태: `ACCEPTED`
- 결정: 공고의 AtomicRequirement를 먼저 저장하고, 별도 Curriculum Proposer가 학습 가능한
  역량과 프로젝트 후보를 만든다.
- 이유: 공고 문장은 기술, 업무, 도메인, 정성 요소가 섞여 있어 바로 학습 노드가 될 수 없다.

## D008 · 사용자 역량은 세 축으로 저장한다

- 상태: `ACCEPTED`
- 결정: `CLAIMED`, `EVIDENCED`, `VERIFIED`를 독립 상태로 관리한다.
- 이유: 이력서에 기술이 있다는 사실과 실제로 검증된 수준은 다르다.
- 적용: 적합도는 근거 중심, 로드맵 공식 완료는 검증 중심으로 계산한다.

## D009 · 외부 효과와 공개 지도는 사람의 승인 대상이다

- 상태: `ACCEPTED`
- 결정: AI는 공고 구조, 적합도, 로드맵을 초안으로 제안한다. 저장·적용·병합·전송의 최종
  권한은 Spring과 사용자 또는 운영자에게 있다.
- 이유: AI 오류가 사용자 커리어 데이터와 공개 로드맵을 자동 변경하지 못하게 한다.

## D010 · legacy와 v3를 feature flag로 병행한다

- 상태: `ACCEPTED`
- 결정: `legacy | v3 | shadow` provider 모드를 지원하고, 새 버전 검증 전 legacy를 삭제하지 않는다.
- 이유: 비교 평가와 즉시 롤백이 필요하다.
- 주의: shadow mode의 사용자 자료 이중 전송은 로컬 또는 명시적으로 승인된 환경에서만 수행한다.

## D011 · 공용 분석과 사용자별 평가를 분리한다

- 상태: `ACCEPTED`
- 결정: 검증된 공고 구조는 공용 캐시로 재사용할 수 있지만 사용자 이력·준비도·로드맵은 매번
  해당 사용자 데이터로 계산한다.
- 이유: 분석 속도를 줄이면서 사용자 데이터 누출을 방지한다.

## D012 · 진행 UI는 실제 경계를 표시한다

- 상태: `ACCEPTED`
- 결정: 고정 타이머나 고정 에이전트 수가 아니라 실행별 stage 배열과 progress event를 표시한다.
- 이유: 호출되는 에이전트와 단계 수가 매번 다르며, 내부 반복이 사용자에게 멈춤처럼 보였다.
- 제한: chain-of-thought는 표시하지 않는다.

## D013 · 추가 질문은 결과를 바꾸는 모호함에만 사용한다

- 상태: `ACCEPTED`
- 결정: 실제 복수 포지션, 경력 충돌, 핵심 사용자 근거처럼 결과를 바꾸는 질문만 한 번에 하나씩
  묻는다.
- 이유: 불필요한 질문 반복과 키워드 기반 가짜 복수 직무 질문을 줄인다.
- 상한 후 처리: 임의 확정이 아니라 `UNKNOWN` 보존.

## D014 · 현재 목표와 최종 목표를 분리한다

- 상태: `ACCEPTED`
- 결정: 현재 목표는 현실적으로 지원 가능한 형식 조건과 핵심 통과 범위에, 최종 목표는 미래
  확장 학습에 사용한다.
- 이유: Java 노드에서 Spring 트랜잭션처럼 범위를 벗어난 문제가 핵심 통과를 막지 않게 한다.

## D015 · 구현 기술 기본값

- 상태: `DEFAULT`
- 기본값: Python 3.12, FastAPI, Pydantic, NDJSON progress stream, Spring DB 정본.
- 변경 조건: 기존 재사용 모듈과의 명확한 호환성 문제 또는 측정된 운영상 이점이 있을 때.
- 의미: 이 기본값은 제품 방향이 아니므로 구현 전에 매번 사용자에게 다시 묻지 않는다.

## D016 · 신뢰된 직접 출처의 자동 확인 범위

- 상태: `DEFERRED`
- 임시 기본값: URL HTML, 이미지, OCR/VLM은 사용자 확인이 필요하다. 공식 구조화 API처럼 원문
  정확성을 계약으로 보장하는 출처만 `TRUSTED_DIRECT_SOURCE` 후보가 될 수 있다.
- 결정 시점: Source Acquisition 구현과 실제 출처별 품질 측정 후.
- 구현 차단 여부: 없음. 초기 버전은 모두 사용자 확인으로 안전하게 진행한다.

## D017 · 신규 기술 운영자 자동 승인 임계값

- 상태: `DEFERRED`
- 임시 기본값: 신규 기술과 애매한 병합은 모두 운영자 검토 대상이다.
- 결정 시점: 후보 발생률과 운영 부담을 측정한 후 exact alias 자동 승인 범위를 조정한다.
- 구현 차단 여부: 없음.

## D018 · 적합도 점수 가중치

- 상태: `DEFERRED`
- 임시 기본값: 필수·우대·경력의 기존 정책은 표시용 기준선으로 유지하되, v3의 세분화된 상태로
  실제 데이터를 모은 뒤 조정한다.
- 고정된 것: AI가 최종 백분율을 임의로 만들지 않고 정책 버전을 가진 서버 계산을 사용한다.
- 구현 차단 여부: 없음. requirement별 평가를 먼저 정확히 만든다.

## D019 · 모델 선택과 비용 상한

- 상태: `DEFERRED`
- 임시 기본값: 기존 provider adapter를 사용하고 모델 이름은 환경 변수로 선택한다.
- 결정 시점: fixture 정확도, 안정성, p95 시간과 비용을 함께 측정한 후.
- 구현 차단 여부: 없음.

## D020 · 기존 AI 제거

- 상태: `REJECTED`(현 단계)
- 결정: v3 설계·구현 과정에서 기존 AI를 삭제하거나 덮어쓰지 않는다.
- 재검토 조건: 모든 수용 기준, 실제 사용자 제한 실험, 롤백 훈련을 통과하고 팀이 별도로 승인한 뒤.

## D021 · 공용 역량 지식 그래프를 로드맵의 기반으로 사용한다

- 상태: `ACCEPTED`
- 결정: 기술 이름, 학습 단위, 필수·권장·조건부 선행관계, 구성·선택·대체 관계, 직무·수준별
  관련성, 출처·신뢰도·검토 상태·버전을 가진 공용 Capability Knowledge Graph를 구축한다.
- 작업 분리: 그래프 자체는 별도 `C:\jobiss-capability-graph-lab`에서 개발하고, AI v3는
  Phase 6.5에서 승인된 그래프를 읽기 전용으로 조회한다.
- 로드맵 방식: 공고의 목표 역량에서 선행관계를 역방향 탐색하고, 사용자의 VERIFIED 역량까지
  올라간 뒤 남은 노드를 조건에 맞게 정렬해 초안을 만든다.
- 이유: AI가 공고마다 학습 순서를 처음부터 창작하지 않게 하고, 여러 회사에서 같은 역량과
  완료 상태를 안정적으로 재사용하기 위해서다.
- 제한: 하나의 유일한 정답 순서를 저장하지 않는다. `HARD_PREREQUISITE`,
  `RECOMMENDED_FOUNDATION`, `CONDITIONAL_PREREQUISITE`, `PART_OF`, `ALTERNATIVE_TO`,
  `ROLE_RELEVANT` 등 관계 의미를 구분한다.
- 승인: AI가 제안한 신규 노드와 관계는 운영자 검토 전 공용 정답으로 사용하지 않는다.
- 통합 권한: 별도 그래프 작업은 기존 JOBIS DB와 v3 코드를 직접 수정하지 않으며, 최종 계약
  검증과 서비스 연결은 이 v3 작업에서 수행한다.

## D022 · 수집 결과와 검증 원문을 분리한다

- 날짜: 2026-08-04
- 상태: `ACCEPTED`
- 결정: 채팅과 채용공고 페이지는 같은 `POST /v1/sources/acquire` 계약을 사용한다. 수집 결과는
  `SourceDocument/AWAITING_VERIFICATION`이며, 사용자 또는 운영자가 확인한 뒤 별도의
  `VerifiedPostingSnapshot`을 만든다.
- 근거: 이미지의 `신입`을 `19년`으로 읽거나 로그인 페이지를 공고로 해석한 실제 회귀를 분석
  이전에 차단해야 한다.
- 보안: URL 수집은 공인 http/https 주소만 허용하고 redirect마다 재검사하며 응답 크기를 제한한다.
- 영속성: AI 서버는 서비스 DB를 소유하지 않는다. Spring이 revision과 snapshot 체인을 보존한다.
- 영향받는 계약·테스트: `SourceAcquisitionRequest`, `SourceDocument`,
  `SourceVerificationRequest/Result`, SRC-001~004, source API smoke.

## D023 · 신입 경력 수치는 0이 아니라 null로 표현한다

- 날짜: 2026-08-04
- 상태: `ACCEPTED`
- 결정: `NEW_GRADUATE`는 경력 종류 자체가 신입임을 나타내므로 `minMonths=null`을 사용한다.
  숫자 0은 요구 경력의 수치가 아니라서 저장하지 않는다.
- 근거: `ExperienceKind`와 수치 범위를 동시에 사용하면서 0을 넣으면 `NO_RESTRICTION` 및
  `NEW_GRADUATE_OR_EXPERIENCED`와 의미가 섞인다.
- 변경: 회귀 fixture EXP-003의 신입 `minMonths=0`을 `null`로 바로잡고 QA 직무 표기를
  계약의 specialization인 `QA_ENGINEERING`으로 통일한다.

## D024 · 구조 질문은 한 번에 하나씩 순서대로 묻는다

- 날짜: 2026-08-04
- 상태: `ACCEPTED`
- 결정: 복수 포지션이면 포지션 선택을 먼저 묻고, 선택된 포지션이 신입·경력 동시 모집일 때만
  경력 트랙을 다음 질문으로 묻는다. 단일 포지션과 단일 경력 트랙은 자동 선택한다.
- 중복 방지: ambiguity ID는 verified snapshot과 후보 ID로 계산하며 답변은 그 ID를 참조한다.
- stale 처리: 다른 revision이나 선택 경로의 답변은 `ANALYSIS_STALE_RESULT`로 거부한다.
- 이유: 질문을 한꺼번에 쏟거나 결과에 영향 없는 내용을 묻지 않으면서, 사용자가 선택하지 않은
  직무·경력 기준으로 적합도를 계산하는 오류를 막는다.

## D025 · 의미 연결과 사용자 상태 판정을 분리한다

- 날짜: 2026-08-04
- 상태: `ACCEPTED`
- 결정: 모델은 공고 requirement와 요청 안의 competency/formal fact ID 사이에 `DIRECT` 또는
  `PARTIAL` 의미 연결만 제안한다. `CLAIMED/EVIDENCED/VERIFIED/NOT_MET` 상태, 분모 포함 여부,
  준비도와 판정안은 결정론적 컴파일러가 계산한다.
- `UNKNOWN`: 관련 근거를 찾지 못한 경우다. 사용자에게 없다는 뜻이 아니며 점수 분모에서 제외한다.
- `NOT_MET`: 사용자가 명시적으로 없다고 답했거나, 검증된 형식 자격·경력 수치가 기준에
  미달할 때만 사용한다.
- 질문: 필수 경력·자격처럼 지원 가능성을 바꾸는 형식 요건만 한 번에 하나씩 묻고, 기술 근거가
  없다는 이유로 연속 질문을 만들지 않는다.
- 개인정보 경계: AI 서버는 DB를 조회하지 않는다. Spring이 RLS 범위 안에서 조립한
  `UserEvidenceBundle` 한 개만 요청에 넣으며, 사용자 적합도 결과는 공용 공고 캐시에 넣지 않는다.
- 검증: 85개 자동 테스트와 실제 Claude 의미 연결 8개 회귀 케이스를 통과했다.
- 영향받는 계약·테스트: `FitAnalysisRequest/Result`, `UserEvidenceBundle`,
  `RequirementAssessment`, `FitAudit`, `test_fit_analysis.py`, `eval_phase5_live.py`.

## D026 · exact 별칭도 문장 전체를 대신하지 않는다

- 날짜: 2026-08-04
- 상태: `ACCEPTED`
- 결정: 자동 정규화는 원자 요건 전체가 승인된 canonical key·표시명·별칭과 동일할 때만 허용한다.
  문장 일부의 기술명 발견은 후보 검색 신호일 뿐 최종 매핑이 아니다.
- AI 후보: catalog scope와 requirement scope를 비교해 기존 후보 또는 신규 후보를 제안한다.
  기존 후보도 운영자 검토 전 공용 catalog에 병합하지 않는다.
- 신규 기술: 가장 가까운 기존 기술이나 `기술 활용` 같은 일반 노드로 바꾸지 않고 안정적인
  candidate ID, 학습 가능 scope, 원문 evidence와 함께 보존한다.
- 비기술 분리: 업무·포트폴리오는 회사 맞춤 프로젝트 재료, 경력·자격은 관문, 행동 요소는
  적합도 전용, 고용 조건은 표시 정보로 분리한다.
- 연속 사용: 운영자 검토는 공용 catalog 승인을 막지만 사용자별 분석 초안 생성을 막지 않는다.
- 검증: 100개 자동 테스트와 실제 Claude 정규화 9개 회귀 케이스를 통과했다.
- 영향받는 계약·테스트: `CapabilityCatalogSnapshot`, `RequirementNormalization`,
  `NormalizationReviewDecision`, `test_capability_normalization.py`, `eval_phase6_live.py`.

## D027 · 외부 역량 그래프는 검증된 read-only closure로만 소비한다

- 날짜: 2026-08-04
- 상태: `PARTIALLY_IMPLEMENTED`
- 결정: v3는 공용 그래프 DB나 파일을 직접 읽거나 수정하지 않는다. 별도 서비스의
  `POST /v1/graph/closure`가 반환한 목표 역량의 역방향 학습 closure만 read-only port로 받는다.
- 계약: 노드·간선은 승인 상태, 출처 ID, 범위, 수준, 신뢰도를 포함한다. 간선 방향은
  `fromCapabilityKey(선행) → toCapabilityKey(목표)`로 고정한다.
- 무결성: graph version, canonical content hash, target·boundary 노드, source 참조,
  hard prerequisite 순환을 검증한다. 조건부 선행관계는 명시적 조건이 없으면 거부한다.
- 장애: 그래프가 없거나 계약이 틀리면 AI가 임의 선행관계를 공용 정답으로 대신 만들지 않는다.
- 현재 제한: `C:\jobiss-capability-graph-lab` 폴더가 아직 존재하지 않아 실제 외부 계약·버전
  호환성 확인은 미완료다. 수신 계약과 port만 6개 자동 테스트로 검증했다.
- 영향받는 계약·테스트: `CapabilityGraphQueryRequest`, `CapabilityGraphClosure`,
  `HttpCapabilityGraphPort`, `test_capability_graph_contract.py`.

## D028 · 회사별 프로젝트와 기회를 하나의 커리어 지도에 합친다

- 날짜: 2026-08-04
- 상태: `ACCEPTED`
- 결정: 공고 하나당 기술 노드를 복제한 별도 로드맵을 만들지 않는다. 승인된 canonical 역량과
  사용자 진행 상태는 하나만 재사용하고, 각 공고에는 회사 맞춤 목표 프로젝트 하나와 회사 기회
  하나를 추가한다.
- 필수·우대: 필수 역량은 프로젝트 완료의 진입 조건이며, 우대 역량은 완료를 막지 않는 보너스
  관계다. 경력과 자격증은 기술이 아니라 별도 관문이다.
- 경력 순서: 회사 기회는 role family·specialization, 원문 경력 종류, 사용자가 선택한 신입/경력
  트랙, 최소 경력 개월을 포함한다. Spring 컴파일러는 같은 직무군에서 신입·경력무관 회사를 같은
  초기 단계에 두고 2년·3년·5년 관문 뒤에 경력 회사를 배치한다.
- 프로젝트: 공고의 기술·업무·도메인을 결합한 미래 결과물이며 과거 이력서 프로젝트를 그대로
  복제하지 않는다. 프로젝트의 역량 참조는 정규화 입력으로 제한한다.
- 책임 경계: AI는 내용 초안만 만들고 좌표, 공개 버전, 적용·취소를 결정하지 않는다. 로드맵
  결과는 항상 `DRAFT`이며 Spring이 기존 버전과 병합하고 사용자가 승인한 뒤 적용한다.
- 검증: 116개 자동 테스트와 실제 Claude 회사 프로젝트 2개 회귀 케이스를 통과했다.
- 영향받는 계약·테스트: `RoadmapDraftRequest`, `RoadmapProposal`, `OpportunitySpec`,
  `RoadmapDraftService`, `test_roadmap_draft.py`, `eval_phase7_live.py`.

## D029 · Spring이 작업과 공개 상태를 소유하고 AI는 단계별 분석을 스트리밍한다

- 날짜: 2026-08-04
- 상태: `ACCEPTED`
- 결정: v3는 확인된 원문부터 로드맵 초안까지 한 pipeline과 실제 단계 NDJSON stream을
  제공한다. Spring은 queue, lease, retry, cancel, stale recovery, 사용자 RLS, 결과 저장,
  proposal 적용·취소와 공개 버전을 소유한다.
- 질문: 포지션·경력·사용자 근거 질문이 생기면 pipeline은 이후 단계를 호출하지 않고 waiting
  결과를 반환한다. Spring은 lease를 해제하고 답변 revision으로 재개한다.
- 진행 표시: UI에는 공개 가능한 단계·상태·경과 시간만 보이며 내부 reasoning은 노출하지 않는다.
- 중복 방지: progress는 `(jobId, sequence)`, 분석은 source/answer/evidence/roadmap revision으로
  멱등성을 보장한다. 취소된 revision의 늦은 결과는 저장하지 않는다.
- 검증: pipeline 동기·NDJSON stream과 unified roadmap 참조 compiler를 포함해 120개 자동
  테스트를 통과했고, 실제 Claude 전체 pipeline 1건에서 14개 단계 이벤트와 DRAFT 결과를
  약 146초에 생성했다.
- 영향받는 계약·테스트: `AnalysisPipelineRequest/Result`, `PipelineStreamEvent`,
  `AnalysisPipelineService`, `compile_preview`, `test_analysis_pipeline.py`,
  `test_roadmap_compiler_reference.py`.

## 변경 기록 방식

새 결정을 추가할 때 다음 형식을 사용한다.

```text
## D번호 · 제목
- 날짜
- 상태
- 결정
- 근거
- 대안
- 영향받는 계약·테스트
- 이전 결정을 변경한다면 해당 번호와 변경 이유
```
