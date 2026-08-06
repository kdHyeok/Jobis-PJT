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

- 상태: `SUPERSEDED BY D047`
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
- 상태: `IMPLEMENTED_CONTRACT`
- 결정: v3는 공용 그래프 DB나 파일을 직접 읽거나 수정하지 않는다. 별도 서비스의
  `POST /v1/graph/prerequisites`가 반환한 목표 역량 또는 프로젝트 과제의 역방향 학습 closure만
  read-only port로 받는다.
- 계약: 노드·간선은 승인 상태, 출처 ID, 원자 범위, 검증 방법, 신뢰 구간을 포함한다. 간선 방향은
  `fromCapabilityKey(선행) → toCapabilityKey(목표)`로 고정한다.
- 무결성: graph version, canonical content hash, target·boundary 노드, source 참조,
  hard prerequisite 순환을 검증한다. 조건부 선행관계는 명시적 조건이 없으면 거부한다.
- 장애: 그래프가 없거나 계약이 틀리면 AI가 임의 선행관계를 공용 정답으로 대신 만들지 않는다.
- 검증: `C:\jobiss-capability-graph-lab`의 `0.1.0-alpha.1`을 실제 기동해 AI v3 HTTP port로
  15개 원자 노드·17개 관계·10개 학습 층 closure를 수신하고 전체 응답 hash를 검증했다.
- 후속 구현: D031에서 Spring의 기술 묶음 입력을 제거하고 그래프 catalog와 프로젝트 과제
  설계기를 직접 연결했다.
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

## D030 · 고정 수준 대신 원자 역량과 프로젝트 과제로 경로를 계산한다

- 날짜: `2026-08-04`
- 상태: `ACCEPTED`
- 결정: 공용 그래프의 완료 단위는 `Java L2` 같은 기술별 고정 수준이 아니라 하나의 목표와
  독립적인 검증 범위를 가진 원자 역량이다. 기술 이름은 분류 컨테이너이며 완료 처리하지 않는다.
- 프로젝트: 공고 업무를 회사 맞춤 프로젝트 과제로 바꾸고 각 과제가 `REQUIRED`,
  `RECOMMENDED`, `EXTENSION` 원자 역량을 선택한다. 선택된 역량에서 선수 관계를 역방향으로
  탐색하고 사용자의 VERIFIED 경계를 만나면 탐색을 중단한다.
- 호환성: AI v3의 공용 그래프 노드와 신규 roadmap operation에서 고정 `level`을 제거했다.
  기존 공개 snapshot의 level은 마이그레이션 기간 동안 읽기 호환성으로만 유지하며 새 원자
  노드의 정체성이나 완료 판정에 사용하지 않는다.
- 검증: Capability Graph 22개 테스트와 AI v3 전체 회귀 테스트를 통과했고 실제 HTTP closure
  호출을 확인했다.
- 후속: 운영자 승인과 원자 역량별 평가 rubric, Spring 사용자 상태의 원자 역량 마이그레이션을
  이어서 구현한다.
- 변경되는 이전 결정: D021·D027의 `수준`을 공용 정답으로 해석한 부분과 D028의 프로젝트 역량
  참조 방식은 이 결정으로 대체한다.
- 영향받는 계약·테스트: `CapabilityGraphNode`, `CapabilityGraphQueryRequest`,
  `CapabilityGraphClosure`, `RoadmapOperation`, `HttpCapabilityGraphPort`,
  `test_capability_graph_contract.py`, `test_roadmap_draft.py`.

## D031 · 공고를 회사 맞춤 프로젝트 과제와 원자 역량으로 먼저 변환한다

- 날짜: `2026-08-04`
- 상태: `ACCEPTED`
- 결정: Spring의 넓은 `competency_catalog`를 AI v3 입력의 공용 정답으로 사용하지 않는다.
  AI v3가 Capability Graph의 승인된 원자 역량 catalog를 읽고, 선택된 공고 직무의 요구사항과
  업무를 하나의 회사 맞춤 프로젝트 및 0~12개 과제로 변환한다.
- 과제 계약: 각 과제는 목표, 관찰 가능한 완료 기준, 원문 requirement ID, `REQUIRED` 또는
  `RECOMMENDED` 원자 역량 키를 가진다. 필수·우대 학습 요구사항은 과제에 연결되거나 명시적으로
  미분류 상태가 되어야 하며 조용히 누락될 수 없다.
- 안전 경계: AI가 반환한 모든 capability key와 requirement ID를 코드로 대조한다. catalog에
  없는 키, 관계없는 requirement 참조, 누락된 필수 요구사항은 계약 오류로 거부한다. 적절한
  원자 역량이 없으면 비슷한 키를 고르지 않고 사용자 범위의 검토 대상으로 남긴다.
- 경로 계산: 프로젝트 과제가 선택한 원자 역량만 graph closure의 target이 된다. 이미 검증된
  원자 역량은 boundary로 전달하되 기존 broad 사용자 역량 키는 graph boundary에서 제외한다.
- 중복 제거: 프로젝트 내용 생성을 graph 조회 뒤 다시 실행하지 않는다. 프로젝트 설계 결과를
  roadmap composer가 결정적으로 컴파일하므로 동일 분석에서 두 번째 LLM 프로젝트 생성이 없다.
- UI: 프로젝트 노드 상세에서 과제 순서, 필수·추천 상태, 완료 기준과 연결된 원자 역량을 표시한다.
- 검증: 원자 catalog 69개를 실제 HTTP로 읽고 `spring.mvc-controller`의 15개 노드·10개 학습층
  closure를 다시 확인했다. broad Java 요구사항을 복수 원자 역량으로 분해하는 테스트, 미등록 키
  거부, 누락 요구사항 거부, 미분류 검토 흐름을 추가했다.
- 영향받는 계약·테스트: `CapabilityGraphCatalog`, `CompanyProjectBlueprint`,
  `ProjectPlanningService`, `AnalysisPipelineRequest/Result`, `ProjectSpec`,
  `V3AnalysisRequestFactory`, `test_project_planning.py`, `test_analysis_pipeline.py`.

## D032 · 사용자 진행 상태를 승인된 원자 역량 정체성에 결합한다

- 날짜: `2026-08-04`
- 상태: `ACCEPTED`
- 결정: 신규 진행 상태는 `(userId, canonicalKey)` 단위의 `user_atomic_capabilities`에 저장한다.
  노드는 생성 당시 Capability Graph 버전, 노드 버전, 기술 컨테이너, 독립 범위와 검증 방법을
  함께 보존한다. 공개 로드맵을 읽을 때 snapshot의 오래된 진행값보다 이 사용자 상태를 우선한다.
- 상태: `NOT_STARTED`, `CLAIMED`, `EVIDENCED`, `VERIFIED`를 구분하며 상태 변경은 별도 event에
  기록한다. 다음 공고 분석에서 graph 탐색 경계를 멈출 수 있는 상태는 `VERIFIED`뿐이다.
- 기존 데이터: `user_competencies`의 기술 단위 완료·레벨은 증거로 계속 읽되 원자 역량 완료로
  자동 승격하지 않는다. 기술 컨테이너 키가 정확히 일치하는 경우에도
  `user_atomic_migration_candidates`의 `PENDING_REVIEW` 후보만 만든다.
- 적용 시점: 로드맵 미리보기는 사용자 상태를 만들지 않는다. 사용자가 초안을 적용할 때 승인된
  원자 노드를 등록하고, 초안을 취소하면 사용자 진행 상태는 변하지 않는다.
- 격리: 세 테이블 모두 사용자 RLS와 운영자 검토 정책을 가지며 기존 broad 기록, 임시 후보,
  승인된 원자 상태를 섞어 쓰지 않는다.
- 영향받는 계약·테스트: `ExistingRoadmapNode`, `RoadmapOperation`, `V3RoadmapCompiler`,
  `V3AtomicCapabilityStateService`, `V3AnalysisRequestFactory`, V39 migration,
  roadmap contract/compiler tests.

## D033 · 원자 역량 검증은 범위를 넓히지 않는 학습형 관문으로 운영한다

- 날짜: `2026-08-04`
- 상태: `ACCEPTED`
- 결정: 검증 문제와 채점은 Capability Graph가 제공한 `objective`, `scopeDefinition`,
  `excludedScope`, `verificationMethods`만 평가 범위로 사용한다. 현재 회사·직무·프로젝트와
  장기 목표는 문제의 상황 맥락에는 사용할 수 있지만 채점 범위를 넓힐 수 없다.
- 통과 기준: 검증 방법 수에 따라 2~3문항을 내며, 각 문항이 60점 이상이고 범위 위반이 없어야
  한다. 모든 문항이 통과하고 전체 평균이 75점 이상일 때만 원자 역량을 `VERIFIED`로 바꾼다.
  평균이 높더라도 한 문항이 실패하면 통과하지 않는다.
- 실패 처리: `NEEDS_STUDY`는 영구 차단이 아니라 부족한 기준과 다음 학습 행동을 보여 주는
  재도전 상태다. 사용자는 범위 또는 채점 오류에 대해 운영자 검토를 요청할 수 있으며,
  승인·거절과 상태 전이는 모두 감사 이벤트로 남긴다.
- 영향받는 계약·테스트: `AtomicCapabilityAssessmentContext`,
  `CapabilityAssessmentQuestion`, `CapabilityAssessmentGrade`, `V3AtomicAssessmentService`,
  V41 migration, AI assessment/API tests, Spring assessment and RLS tests.

## D034 · 완료 방식은 화면 위치가 아니라 그래프 노드 정책이 결정한다

- 날짜: `2026-08-04`
- 상태: `ACCEPTED`
- 결정: 각 원자 역량은 `completionPolicy=SELF_CONFIRM|ASSESSMENT`를 가진다. 프론트의
  경로·접두사·노드 위치로 기초 역량 여부를 추정하지 않는다.
- 자기 확인 범위: 초기 공통 기반인 파일·디렉터리, 명령줄, IDE·디버깅, Git 커밋 이력,
  브랜치·병합 노드만 `SELF_CONFIRM`이다. 그 밖의 기술 원자는 기본적으로 `ASSESSMENT`다.
- 이전 기록: legacy 기술 완료 기록은 일치 후보를 만들 수 있지만 사용자 확인 후에도
  `EVIDENCED`까지만 이동한다. 평가 또는 명시된 자기 확인 없이 자동 `VERIFIED`하지 않는다.
- 영향받는 계약·테스트: Capability Graph `CompletionPolicy`, roadmap operation/snapshot,
  `user_atomic_capabilities.completion_policy`, V42 migration, Career Map completion UI.

## D035 · AI 비교는 기존 완료 결과의 수동적 짝짓기부터 시작한다

- 날짜: `2026-08-04`
- 상태: `ACCEPTED`
- 결정: shadow 비교는 동일 사용자의 같은 공고 fingerprint에 대해 이미 완료된 LEGACY와 V3
  결과만 짝짓는 `PASSIVE_PAIRED`로 시작한다. 새 분석을 만들거나 공고·이력서 원문을 두 번째
  공급자에게 전송하지 않는다.
- 평가: 자동 비교기는 회사, 직무, 최소 경력, 지원 판정, 필수 요건 수, 역량 집합과 회사 맞춤
  프로젝트 존재 여부의 차이만 계산한다. 일치율은 정확도가 아니며 운영자가 원문과 사용자
  맥락을 확인해 우열·동등·판정 불가를 근거와 함께 결정한다.
- 저장: 비교 테이블에는 작업 ID, fingerprint, 정규화된 field diff, 처리 시간과 운영자 판정만
  저장한다. 공고 원문, 이력서 원문, 프롬프트와 내부 reasoning은 복사하지 않는다.
- 전환: 실제 paired 표본의 정확도·안정성·p50/p95·수정률을 관찰하기 전에는 기본 provider를
  바꾸지 않는다. active duplicate dispatch는 별도 개인정보·비용 승인과 구현 결정 없이는
  추가하지 않는다.
- 영향받는 계약·테스트: V43 migration, `AiProviderResultComparator`,
  `AiProviderComparisonService`, 운영 검토함 AI 결과 비교 탭,
  `provider-comparison-corpus.json`, 실제 PostgreSQL RLS E2E.

## D036 · 단일 실제 비교 후에도 V3 기본 전환을 보류한다

- 날짜: 2026-08-04
- 상태: `ACCEPTED`
- 결정: 공개 합성 공고 한 건의 실제 LEGACY/V3 paired 실행은 통합 경로 검증으로만 사용한다.
  `AI_PROVIDER` 기본값은 바꾸지 않으며, 제한된 내부 사용자 활성화도 별도 승인 전에는 진행하지 않는다.
- 근거: 두 공급자 모두 완료됐지만 직무·판정·필수 요건 수·역량 집합이 크게 달랐고,
  V3 마지막 활성 처리 시간은 184,530ms로 LEGACY 이벤트 구간 79,618ms보다 길었다. 또한 질문
  재개와 프로젝트 계획 과정에서 여러 계약·안정성 결함을 발견해 수정했으나 반복 표본으로
  재발 여부를 검증하지 못했다.
- 다음 게이트: 여러 공개 공고의 사람 판정, 기존 우세·V3 우세 사례, 오류율, 질문률, 사용자
  수정률, 비용과 p50/p95를 확보하고 롤백 리허설을 통과한다.
- 대안: 즉시 V3 전환, active duplicate shadow 전송. 표본·개인정보·비용 근거가 없어 채택하지 않았다.
- 영향받는 계약·테스트: `structuredPostingCheckpoint`, `requirementSelfReports`, V3 pipeline 3.0.1,
  passive comparison duration basis, `docs/16-phase9-live-provider-comparison.md`.
- 이전 결정: D035의 수동적 짝짓기와 전환 게이트를 실제 실행 결과로 재확인한다.

## D037 · 선택한 공고 범위를 확인한 뒤 프로젝트 설계를 시작한다

- 날짜: `2026-08-05`
- 상태: `ACCEPTED · IMPLEMENTED`
- 결정: 공고 원문은 수정하지 않은 감사 자료로 보존한다. AI가 모든 모집 포지션을 구조화한 뒤
  복수 직무면 직무를, 신입·경력 동시 모집이면 경력 트랙을 한 번에 하나씩 묻는다. 선택이
  끝나면 해당 포지션의 업무·필수·우대 요건만 결정적으로 투영한 `PostingReview`를 사용자에게
  보여 주며, 확인 전에는 회사 맞춤 프로젝트·역량 그래프·로드맵을 생성하지 않는다.
- 근거: 원문 전체를 “필요한 내용만 정리한 결과”로 표시하면 복지·연락처와 다른 직무 요건이
  섞이고 사용자는 AI가 실제로 어느 직무를 분석하는지 확인할 수 없다. 반대로 요약문만 저장하면
  원문 감사와 수정 가능성을 잃는다.
- 재개: 구조화 결과와 질문 답변은 같은 분석 작업의 체크포인트로 저장한다. 최종 확인 ID는
  verified snapshot, 선택 포지션·경력 트랙과 구조화 내용으로 계산해 이전 결과의 확인을 재사용하지
  못하게 한다. 확인 후에는 구조화 LLM을 다시 호출하지 않는다.
- 직무 규칙: 한 공고에서 프론트엔드·백엔드를 함께 모집한다는 사실만으로 `FULL_STACK`으로
  합치지 않는다. 한 지원자가 양쪽을 모두 담당한다고 원문이 명시한 경우에만 full-stack이다.
- 영향받는 계약·테스트: `AnalysisPipelineRequest.confirmedPostingReviewId`,
  `PipelineStatus.AWAITING_POSTING_CONFIRMATION`, `PostingReview`, Spring V3 job checkpoint,
  Chat·Posting Detail 확인 UI, 다중 직무·경력 pipeline 회귀 테스트.
- 이전 결정: D004의 원문 검증을 유지하면서 D024 뒤에 사용자 의미 범위 확인 단계를 추가한다.

## D038 · 채팅 공고 모달은 분석 화면이 아니라 대화 요청 입력기로 사용한다

- 날짜: `2026-08-05`
- 상태: `ACCEPTED · IMPLEMENTED`
- 결정: 채팅의 공고 분석 모달에서 URL을 제출하면 모달을 즉시 닫고, 사용자가 대화창에
  `URL + 공고 분석해줘`를 보낸 것과 동일한 메시지·에이전트 작업을 만든다. URL 수집이나 AI
  정리가 끝날 때까지 모달 안에서 기다리지 않으며, 정리가 완료돼도 모달을 자동으로 다시 열지
  않는다.
- 사용자 경험: 수집·직무 및 경력 질문·공고 범위 확인·오류·재시도·최종 결과는 모두 지속되는
  대화 기록 안에 표시한다. 사용자는 분석 중 다른 대화나 페이지를 자유롭게 이용할 수 있고,
  백엔드 작업은 화면 이동과 무관하게 계속된다. 최종 확인은 기존 대화형 `PostingReview` 카드에서
  수행한다.
- 데이터 경계: 공고 원문은 감사 근거로 별도 보존하고, 에이전트 정리문이나 사용자 답변으로
  원문을 덮어쓰지 않는다. 원문 수집 경고나 사용자 수정이 반드시 필요한 경우에도 자동 재개방
  모달 대신 대화의 질문·확인 상태로 노출한다.
- 이유: 입력 모달에서 긴 AI 작업을 기다린 뒤 같은 모달이 다시 열리면 사용자가 작업이 끝난
  것으로 오해하고 다른 기능을 이용하기 어렵다. 동일한 공고 분석 요청이 입력 위치에 따라 서로
  다른 UX를 갖는 문제도 제거해야 한다.
- 영향받는 계약·화면: `ChatView.prepareAttachedPosting`, `openPostingReview`, 자동
  `ANALYZE_POSTING` 실행 처리, 채팅 공고 초안 복구 상태, 대화의 V3 질문 및 `PostingReview` UI.
- 이전 결정: D037의 포지션·경력 선택과 최종 확인 관문은 유지한다. 이 결정은 관문의 표시 위치를
  모달에서 지속되는 대화 기록으로 변경한다.

## D039 · V3 추가 수정 전에 이전 프로젝트 동작 보존 감사를 수행한다

- 날짜: `2026-08-05`
- 상태: `ACCEPTED · AUDIT_COMPLETED`
- 제안: V3 로드맵과 관련 통합 기능을 더 수정하기 전에 `C:\jobiss-service`와 현재 V3의 동일
  사용자 시나리오를 비교한다. 기존 동작을 `PRESERVE|IMPROVE|REPLACE|REMOVE|MISSING|CONFLICT`로
  분류하고, 의도 없이 누락된 동작에 대한 회귀 테스트를 먼저 작성한다.
- 발견 근거: 기존 로드맵은 모든 목표 공고를 재조립해 관련 직무 취업, 경력 구간, 같은 단계의
  회사 기회를 하나의 여정으로 구성했다. 현재 V3는 공고별 원자 역량·프로젝트·gate·opportunity
  변경안을 누적하지만 명시적 관련 취업 합류점과 전체 커리어 여정 assembler가 없다. 또한 V3의
  `GATE/EXPERIENCE`와 기본 JourneyModel의 `MILESTONE/EXPERIENCE` 기대가 달라 경력 chapter가
  누락될 수 있다.
- 정정: 현재 `v3-adapter.ts`는 snapshot relation을 화면 edge로 변환한다. 따라서 관계 소실을
  프론트 단독 원인으로 확정하지 않고 AI proposal부터 렌더링 모델까지 한 분석 건을 추적한다.
- 보존 방향: V3의 원자 역량, 선수관계, 회사 맞춤 프로젝트, 사용자 증거, graph version과
  Spring-owned 적용 규칙은 유지한다. 기존 프로젝트의 관련 취업 합류점, 경력 구간, 병렬 회사와
  전체 목표 재조립 의미는 복원 후보로 검토한다.
- 감사 범위: 공고 수집·중복·질문·백그라운드 복구, 채팅 기록, 커리어 저장소, 로드맵
  미리보기·적용·제거·초기화, 사용자 진행 상태, RLS와 공용·개인 데이터 경계를 포함한다.
- 상세 문서: `docs/18-legacy-behavior-preservation-audit.md`.
- 구현 상태: 이 결정은 감사와 수정 기준만 기록하며 코드·DB·실행 동작은 변경하지 않았다.
- 영향받을 수 있는 계약·테스트: `RoadmapProposal`, `OpportunitySpec`, career event/gate 계약,
  `V3RoadmapCompiler`, `V3RoadmapService`, `v3-adapter.ts`, `journey.ts`, 로드맵·비동기·RLS 회귀
  시나리오.

## D040 · 사용자 진행 화면에는 모델명이 아니라 JOBIS 에이전트 역할을 표시한다

- 날짜: `2026-08-06`
- 상태: `ACCEPTED · IMPLEMENTED`
- 결정: 사용자 화면과 영속 대화 기록에는 Codex, Claude, GPT 같은 provider·model 이름을 표시하지
  않는다. 진행 주체는 `공고 수집`, `공고 해석`, `프로젝트 설계`, `역량 연결`, `적합도 분석`,
  `로드맵 조립`처럼 사용자가 이해할 수 있는 JOBIS 에이전트 역할로 표현한다.
- 운영 경계: provider, model, effort, token, 비용, 내부 재시도 정보는 운영 로그와 관리자 진단에만
  남긴다. 사용자에게는 실제 stage, 완료·대기·실패 상태와 다음 행동만 보여 주며 chain-of-thought는
  노출하지 않는다.
- 이유: 구현 공급자는 교체 가능한 내부 세부사항이며 `Codex가 결과를 생성하고 있어요` 같은 문구는
  JOBIS의 서비스 개념을 깨고 특정 공급자 장애·교체를 제품 상태처럼 보이게 한다.
- 영향받는 계약·화면: `ProgressEvent`, AI V3 NDJSON stage event, Spring 분석·채팅 작업 상태,
  `AgentExecutionMap`, `AnalysisProgressWheel`, 채팅 영속 이벤트와 운영 로그.
- 이전 결정: D012의 실제 실행 단계 표시 원칙을 사용자용 역할명과 운영용 provider 진단으로
  명확히 분리한다.

## D041 · 사용자가 취소한 분석은 자동 복구하지 않는다

- 날짜: `2026-08-06`
- 상태: `ACCEPTED · IMPLEMENTED`
- 결정: 사용자 취소, 연결 중단, 서버 장애, 재시도 가능 실패를 서로 다른 상태로 저장한다.
  `CANCELLED_BY_USER`는 terminal 상태이며 대화 재진입, 새로고침, 서버 재시작, worker 복구 작업으로
  다시 `PENDING`이나 `RUNNING`이 될 수 없다. 자동 복구 대상은 lease가 만료된 `INTERRUPTED` 또는
  명시적인 `RETRYABLE` 작업뿐이다.
- 동작: 화면을 다시 여는 행위는 상태 조회와 스트림 재구독만 수행한다. 실제 분석 재실행은 사용자가
  `다시 분석`을 명시적으로 선택했을 때 새 attempt 또는 새 job으로 시작하며, 취소된 job ID를
  되살리지 않는다. 취소 API는 반복 호출해도 같은 결과를 내야 한다.
- 이유: 취소한 채팅에 다시 들어갔을 때 분석이 재개되는 현상은 사용자의 명시적 의사를 위반하고
  비용·중복 결과·늦은 응답 덮어쓰기 문제를 만든다.
- 영향받는 계약·테스트: 분석·채팅 job 상태 enum, queue claim/recovery 함수, cancel API,
  `AnalysisWorker`, `ChatReplyWorker`, 화면 재진입 watcher, 사용자 취소·서버 장애 복구 통합 테스트.

## D042 · 로드맵은 프로젝트 우선의 하나의 사용자 커리어 그래프로 조립한다

- 날짜: `2026-08-06`
- 상태: `ACCEPTED · IMPLEMENTED`
- 결정: 공고 해석기는 공용 역량 사전과 무관하게 직무·업무·필수·우대·경력·비학습 조건을 먼저
  추출한다. 선택한 포지션의 실제 업무로 회사 맞춤 프로젝트와 과제를 설계한 뒤, 과제별 승인된
  원자 역량을 매핑하고 필수·권장 선수관계 closure를 조회한다. 사용자의 `VERIFIED` 범위를 제외한
  결과를 모든 활성·장기 목표와 함께 하나의 커리어 그래프로 조립한다.
- 경력 관계: 회사 지원 기회, 실제 관련 직무 취업, 관련 경력 구간은 서로 다른 node·event다.
  최소·최대 경력과 인정 가능한 role scope를 보존하며, 같은 경력 개월만으로 서로 다른 직무의
  회사를 병렬 기회로 묶지 않는다. 특정 신입 회사 합격을 다음 회사의 유일한 선수조건으로 만들지
  않고 여러 관련 진입 기회가 `EMPLOYMENT` 사건으로 합류할 수 있게 한다.
- 미등록 역량: 공고와 프로젝트 과제에 필요하지만 공용 그래프에 없는 역량은 누락하거나 임의의
  기존 node에 끼워 넣지 않는다. 원문 requirement와 project task에 연결된 사용자 범위의
  `PROVISIONAL_CANDIDATE`로 로드맵에 표시하고 운영자 승인 전에는 공용 node로 승격하지 않는다.
- 공유 역량: 동일한 수행 범위의 Docker 같은 원자 역량은 공용 node 하나를 재사용한다. 화면에서는
  백엔드·보안 등 각 프로젝트 문맥에 참조 projection을 둘 수 있고 완료 상태는 하나로 동기화한다.
  이미지 취약점 점검·네트워크 격리처럼 범위가 넓어지면 부족한 보안 범위만 별도 원자 역량으로
  추가한다.
- 비학습 조건: 협업, 책임감, 열정 같은 정성 조건은 기술 학습 node로 만들지 않고 프로젝트 증거,
  면접 준비, 지원조건으로 분리한다. 학위·자격·병역·경력도 기술 node가 아닌 hard gate다.
- 화면: 주 경로에는 foundation, learning chapter, company project, opportunity, employment,
  experience interval을 표시한다. 원자 역량은 chapter와 프로젝트 상세의 검증 가능한 퀘스트로
  펼치고 실제 relation을 보존한다.
- 영향받는 계약·테스트: `StructuredPosting`, `CompanyProjectBlueprint`, capability normalization,
  provisional candidate 계약, `RoadmapProposal`, `V3RoadmapCompiler`, 전체 목표 assembler,
  Roadmap workspace API, `v3-adapter.ts`, `journey.ts`, 이스트게임즈·네이버웹툰·AI 보안 수용 시나리오.
- 이전 결정: D006, D007, D021, D030~D034와 D039를 하나의 사용자 커리어 그래프 조립 규칙으로
  구체화한다.

## D043 · 신규 역량 후보는 사용자 흐름을 막지 않고 운영자 검토함에서 공용화한다

- 날짜: `2026-08-06`
- 상태: `ACCEPTED · PARTIALLY_IMPLEMENTED · GRAPH_ACTIVATION_PENDING`
- 결정: 공용 그래프에 없는 역량 후보는 사용자 로드맵에 `검토 중 역량`으로 즉시 표시할 수 있지만,
  운영자 승인 전에는 다른 사용자의 확정 선수관계나 공용 완료 기준으로 사용하지 않는다. 운영자
  페이지에 `역량 사전 검토함`을 추가해 후보의 승인, 수정 후 승인, 기존 역량 병합, 보류, 반려를
  처리한다.
- 검토 정보: 추출 공고와 원문 근거, 회사 맞춤 project task, AI 제안 수행 범위, 추천 직무·도메인,
  기존 유사 역량과 중복도, 필수·권장 선수관계 제안, 영향을 받는 공고·사용자 수를 함께 보여 준다.
- 발행: 승인된 변경은 공용 Capability Graph의 새 버전으로 묶어 미리보기 후 발행한다. 병합·분리·
  관계 수정은 감사 로그와 alias/migration 이력을 남기며 기존 사용자의 검증 증거와 과거 로드맵
  버전을 자동으로 삭제하거나 변형하지 않는다.
- 운영 범위: 운영자는 모든 사용자 로드맵을 수작업 승인하지 않는다. 승인된 node 재사용, 사용자
  완료 상태 제외, 결정적 경력 gate 조립은 코드가 수행하고 운영자는 새 지식과 의심스러운 분류만
  검토한다.
- 영향받는 계약·화면: capability candidate·review·graph version DB, 운영자 RLS·감사 이벤트,
  운영자 검토함 API/UI, 사용자 로드맵의 provisional 표시와 graph version migration 테스트.
- 이전 결정: D006의 `NEW_CANDIDATE`와 운영자 최종 권한, D017의 승인 경계를 실제 제품 흐름으로
  구체화한다.

## D044 · 보존 감사 결과를 V3 출시 전 수정 게이트로 채택한다

- 날짜: `2026-08-06`
- 상태: `ACCEPTED · IMPLEMENTED · LIVE_VERIFICATION_PENDING`
- 결정: `docs/18-legacy-behavior-preservation-audit.md`의 실제 코드 추적과 테스트 결과를 V3의 출시 전
  수정 기준으로 채택한다. Phase 0~8에서 코드가 존재하거나 격리 테스트를 통과했다는 사실만으로
  통합 서비스의 제품 동작이 완료됐다고 판단하지 않는다. 아래 수정 게이트를 모두 통과하기 전에는
  Phase 9의 기본 provider 전환과 출시 가능 판정을 진행하지 않는다.
- 감사 근거: 전체 `scripts/check.ps1`, legacy AI 697개 테스트, V3 회귀 fixture 40개,
  Capability Graph·AI V3 테스트와 frontend build는 통과했다. 별도 frontend test는 3개뿐이었고,
  Spring 64개 중 PostgreSQL RLS 통합 테스트 12개는 Docker 부재로 건너뛰었다. 따라서 계약·단위
  테스트 통과와 실제 사용자 흐름·tenant 격리 완료를 구분한다.

### 수정 게이트 0 · 실패 기준과 데이터 추적 고정

- 같은 분석 건을 `AI 원본 → Spring 저장 proposal → API 응답 → v3 adapter → JourneyModel`까지
  동일 ID로 추적할 수 있게 하고, 어느 경계에서 node·relation·경력·근거가 소실되는지 fixture로
  고정한다.
- 모든 로드맵 node와 relation은 공고 requirement, 회사 project task 또는 career evidence까지
  역추적할 수 있어야 한다.
- SVG는 설명 자료로만 사용한다. 공식 기준은 설계 결정, 데이터 계약, 불변 규칙과 자동 수용
  테스트다.

### 수정 게이트 1 · 프로젝트 우선 설계와 역량 무손실 보존

- 회사 프로젝트 과제 설계와 승인된 원자 역량 매핑을 의미상 분리한다. 프로젝트는 전체 catalog에
  맞춰 만들지 않고 선택한 공고의 실제 업무·도메인·필수·우대 근거에서 먼저 설계한다.
- `compile_project_normalization`에서도 catalog에 없는 학습 가능 요건을 `UNRESOLVED`로 버리지
  않는다. requirement와 project task에 연결된 사용자 범위의 `PROVISIONAL_CANDIDATE`로 남긴다.
- 승인 역량에만 선수관계 closure를 적용하며 임시 후보에 AI가 공용 선수관계를 지어내지 않는다.
- 기술, 업무, 도메인 지식, 자격·경력, 정성 조건을 구분한다. 협업·책임감·열정은 기술 학습 node가
  되지 않는다.
- 전체 catalog가 커져도 prompt 제한으로 프로젝트 생성이 실패하지 않는 조회·후보 축소 방식을
  사용한다.

### 수정 게이트 2 · 하나의 사용자 커리어 그래프 조립

- 모든 활성·장기 목표를 공고별 patch 모음이 아니라 하나의 사용자 DAG로 재조립한다.
- 학습 chapter, 회사 project, 지원 opportunity, 실제 관련 취업 event, 경력 interval을 서로 다른
  의미로 저장한다. 프로젝트 완료나 지원 버튼만으로 경력이 시작되지 않는다.
- 경력 조건의 최소·최대 기간과 관련 role scope를 proposal, snapshot, API와 화면 끝까지 보존한다.
- 병렬·대체 기회는 경력 숫자만이 아니라 직무 계열, 역량 겹침, 증거 재사용, 도메인, 지원조건과
  다음 목표와의 관련성으로 판정한다.
- 이스트게임즈는 네이버웹툰으로 가기 위한 필수 회사가 아니라 여러 관련 주니어 취업 기회 중
  하나다. 관련 없는 경력무관 직무는 네이버 백엔드 경력 구간의 대체 진입점이 될 수 없다.
- 같은 canonical 역량은 완료 상태를 하나만 유지하면서 여러 프로젝트·분야 chapter에 문맥별
  membership과 필요한 이유를 가질 수 있다. 기존 수행 범위를 넘는 요구만 부족한 원자 범위로
  추가한다.
- V3의 `GATE/EXPERIENCE`와 JourneyModel의 경력 chapter 판정을 한 계약으로 통일하고, 원자 역량은
  주 경로에 전부 나열하지 않고 chapter 상세 퀘스트로 표시한다.
- 구현 전에 관련 취업 node kind, 경력 시작·종료 증거, 최대 경력의 hard gate 여부와 전체 재조립
  방식을 별도 결정으로 확정한다.

### 수정 게이트 3 · V3 목표·버전 수명주기와 단일 정본

- V3 목표 공고 제거, 전체 목표 초기화, 활성 목표 재조립, 버전 목록과 과거 버전 복원을 제공한다.
- preview diff는 추가·변경뿐 아니라 제거될 node·relation과 영향을 보여 준다.
- 홈의 다음 퀘스트·진행률·초안 알림, 커리어 지도와 공고 참조 검사는 같은 V3 현재 버전을 정본으로
  사용한다.
- 공고 영구 삭제는 legacy 참조뿐 아니라 V3 proposal, version과 snapshot 참조를 검사한다.
- 목표를 제거하면 해당 회사 project·opportunity만 제거하고 공유 역량과 다른 목표는 유지한다.
- 새 공용 graph version이 발행돼도 기존 로드맵 snapshot과 사용자 검증 증거를 자동 변형하거나
  삭제하지 않는다.

### 수정 게이트 4 · 공고·채팅 작업 수명주기와 실제 취소

- 분석 시작 시 최신 verified snapshot revision/hash와 기존 job 상태를 비교한다. 원문을 고쳐 다시
  확인한 경우 과거 성공·실패·취소 job을 반환하지 않는다.
- 동일 공고의 사용자 비의존 구조화 결과는 공용 cache·lease로 재사용하고, 적합도·로드맵은
  사용자별로 계산한다.
- 붙여넣기, URL, 이미지, 채팅 진입점이 같은 원문 확인 관문을 거치게 한다.
- D038대로 공고 모달 제출 즉시 모달을 닫고 동일한 영속 채팅 요청을 한 번만 생성한다. 과거
  `POSTING_REVIEW` action이 화면 복원 때 모달을 다시 열지 않는다.
- `CANCELLED_BY_USER`와 장애성 `INTERRUPTED`를 분리하고, Spring 취소를 AI V3 worker와 실행 중
  provider 호출까지 전파한다. 사용자 취소는 재진입·새로고침·서버 재시작으로 부활하지 않는다.
- 일반 chat reply에도 취소를 제공하고, 중복 enqueue 여부를 확정한 뒤 quota를 한 번만 차감한다.
- 질문 카드, 사용자 선택, 완료·실패·재시도 기록은 새로고침 뒤에도 같은 순서와 UI 의미로 복원한다.
- 사용자 진행 화면에는 D040의 JOBIS 에이전트 역할만 표시하고 provider/model은 운영 로그에만 둔다.

### 수정 게이트 5 · 커리어 저장소와 학습·검증

- 커리어 조각의 표시 kind·제목·설명과 숨은 canonical identity·structured detail이 수정 후 서로
  달라지지 않게 재해석 또는 변경 제한 정책을 둔다.
- 병합은 같은 kind만 확인하지 않고 수행 범위와 근거 호환성을 검사하며 preview, lineage와 복구
  수단을 제공한다.
- V3 원자 역량에 학습 가이드 API·UI를 추가해 `학습 → 검증` 흐름을 연결한다.
- 문제와 학습 가이드는 `scopeDefinition` 안에서만 만들고 `excludedScope`를 넘지 않는다.
- 진행 중 assessment 재사용 시 회사·프로젝트 target context를 확인하고, 부분 재시험과 통과 항목
  유효기간 정책을 구현한다.
- 답변 제출은 idempotency와 DB 소유권을 확보한 뒤 한 번만 AI를 호출하며 입력 길이를 제한한다.

### 수정 게이트 6 · 운영자 사전·보안·RLS

- D043의 역량 사전 검토함에서 신규 후보의 원문, requirement, project task, 제안 scope, 유사
  canonical 역량을 함께 보고 승인·수정 승인·병합·분리·보류·반려할 수 있게 한다.
- 승인 변경은 공용 Capability Graph 새 version으로 미리보기 후 발행하고 alias·migration·감사
  이력을 남긴다.
- 로그아웃은 cookie 삭제뿐 아니라 기존 access token의 서버 측 유효성도 끊는다.
- production validator가 V3 AI shared secret과 기본 DB 계정·비밀번호 사용을 검사한다.
- 이력서·공고·검증 답변의 보존 기간, 삭제 전파, 운영자 열람 감사와 백업 폐기 정책을 확정한다.
- 실제 PostgreSQL에서 RLS tenant 격리와 null·중복·동시 요청·migration을 검증한다. Docker 부재로
  skip된 테스트는 성공 근거로 계산하지 않는다.

### 수정 게이트 7 · UI·접근성·릴리스 검증

- 상단 AI 진행 배너는 실제 활성 작업이 있을 때만 표시한다.
- modal에 첫 포커스, focus trap, Escape 닫기와 trigger focus 복원을 적용하고 `window.confirm/prompt`
  흐름을 일관된 제품 dialog로 교체한다.
- 8~10px 텍스트, 누락된 focus ring, 운영자 7번째 모바일 메뉴 잘림과 hover 전용 삭제 동작을
  접근성 기준에 맞게 수정한다.
- 중첩된 대형 `base.css` override와 라우터에서 사용하지 않는 `V3CareerMapView.vue`를 정리한다.
- `scripts/check.ps1`에 frontend test를 포함하고 채팅 복원, 공고 모달, 분석 취소, roadmap
  preview/apply/remove/reset/restore, 홈 정합성과 keyboard/mobile E2E를 추가한다.
- 정확성, 근거 완전성, 안정성, 오류율, p50/p95와 비용을 측정하고 제한된 내부 사용자 검증과
  롤백 실험을 통과한 뒤에만 V3를 기본 provider로 전환한다.

### 필수 수용 시나리오

1. 이스트게임즈 신입과 네이버웹툰 경력 공고가 하나의 커리어 그래프에 연결된다.
2. 실제 관련 취업 전에는 네이버 경력 구간이 진행되지 않으며 최소 2년·최대 4년이 보존된다.
3. 다른 관련 주니어 백엔드 취업도 같은 경력 구간의 진입 기회가 될 수 있다.
4. 이미 검증한 Java·Spring은 반복되지 않고 더 넓은 수행 범위만 추가된다.
5. 4년 경력 AI 보안 공고가 보안 foundation, 프로젝트 과제, 관련 취업, 경력 4년, AI 보안 심화,
   회사 기회로 이어지며 Docker·CI/CD·프로젝트 하나로 축약되지 않는다.
6. 공용 그래프에 없는 역량은 사라지지 않고 운영자 승인 전 사용자 범위의 검토 후보로 표시된다.
7. Docker는 완료 상태 하나를 공유하면서 백엔드·보안 프로젝트에서 각각 필요한 이유가 표시된다.
8. 초안 취소, 목표 제거, 전체 초기화와 과거 버전 복원이 공유 역량·증거를 잘못 삭제하지 않는다.
9. 원문 수정 후 새 revision이 분석되고 같은 공고 공용 구조화는 재사용되며 사용자 평가는 분리된다.
10. 사용자 취소 작업은 화면 재진입·서버 재시작 후에도 자동 재개되지 않고 실제 AI 실행도 중단된다.
11. 질문과 선택 답변, 진행 역할과 최종 결과가 분석 완료와 새로고침 뒤에도 대화에 남는다.
12. 홈, 로드맵, 채용공고와 운영자 화면이 같은 V3 정본과 graph version을 표시한다.
13. 마감 공고는 현재 지원 가능 상태와 분리된 `REOPENING_PREPARATION` 장기 목표로 등록할 수 있다.
14. 필수 요건 매핑이나 분석이 불완전하면 `필수 검증 0/0`, `준비도 —%`를 정상적인 0점처럼
    표시하지 않고 계산 불가 이유와 다시 분석·검토 행동을 제공한다.
15. 새 직무·도메인은 canonical key 접두사 하드코딩 때문에 `기타 핵심 역량`으로 떨어지지 않고
    roadmap projection의 section·membership에 따라 배치된다.
16. 실제 활성 lease가 없으면 대기 순서를 표시하지 않고, 중복·stale 작업과 실제 동시 실행 제한을
    구분한다.
17. 인증 만료·갱신·로그아웃은 하나의 세션 정책을 따르고, 사용 중 갑작스러운 로그아웃과 탈취
    token의 만료 전 재사용을 모두 방지한다.
18. URL 수집은 DNS 검증과 실제 연결 대상을 일치시키고, 민감 원문의 보존·삭제·백업·암호화 정책을
    운영 환경에서 검증한다.
19. 대체 공고가 정말 없는 상태와 추천 API 실패를 구분하고, 같은 대표 공고는 사용자에게 한 번만
    표시한다.
20. 사이드바, 현재 메뉴 표시, 채팅 내부 스크롤, 10줄 입력창, JOBIS 명칭과 파란색 제품 테마를
    핵심 기능 수정 뒤에도 회귀시키지 않는다.

- 구현 순서: `수용 fixture·JSON 추적 → 무손실 project/capability 경로 → career graph assembler →
  V3 목표·버전 정본 → source/chat/cancel → 저장소·학습·검증 → 운영자·보안·RLS → UI·E2E·전환`.
- 이유: 현재 가장 큰 위험은 AI 모델의 품질 자체가 아니라 통합 파이프라인이 이미 추출한 의미를
  버리거나, 경력과 지원 기회를 잘못 연결하거나, 화면별로 서로 다른 정본을 사용하는 것이다.
- 대안: 프론트만 수정, 기존 V3 patch 누적 유지, 공용 사전에 없는 역량 무시. 데이터 의미와 사용자
  목표 수명주기 결함을 남기므로 채택하지 않는다.
- 영향받는 계약·코드·테스트: `CompanyProjectBlueprint`, capability normalization과 provisional
  candidate, `OpportunitySpec`, employment/experience 계약, 전체 목표 assembler,
  `V3RoadmapCompiler`, `V3RoadmapService`, source/chat job과 cancel API, career repository,
  atomic learning/assessment, operator capability review, `v3-adapter.ts`, `journey.ts`, Home·Posting
  reference, 실제 PostgreSQL RLS와 frontend E2E.
- 이전 결정: D039의 감사를 완료 상태로 전환하고, D038·D040~D043을 포함한 실제 수정 순서와 출시
  차단 기준을 확정한다.

## D045 · 경계 정책과 현재 UI 동작을 명시적인 회귀 기준으로 고정한다

- 날짜: `2026-08-06`
- 상태: `ACCEPTED · IMPLEMENTED · THREE_POLICIES_OPEN · LIVE_VERIFICATION_PENDING`
- 결정: D044에 포함되지 않았던 마감 공고, 계산 불가 준비도, 동적 분야 배치, 대기열, 인증 세션,
  URL 연결 보안, 대체 공고 오류와 현재 UI 보존 규칙을 별도의 수용 기준으로 고정한다. 이미 구현된
  UI도 수정 대상에서 제외하는 데 그치지 않고 자동 회귀 테스트로 보호한다.

### 마감 공고와 장기 목표

- 마감된 공고도 사용자가 같은 회사·직무의 미래 재공고를 준비하려는 경우 로드맵 목표로 등록할 수
  있다. 이 상태는 `REOPENING_PREPARATION`으로 표현하고 `현재 지원 가능`과 구분한다.
- 원본 공고의 마감일과 당시 요구조건은 불변 snapshot으로 보존한다. 미래에 새 공고가 열리면 기존
  공고를 덮어쓰지 않고 새 revision 또는 새 posting으로 연결해 차이를 검토한다.
- 마감 공고를 삭제하거나 정상 지원 가능 공고처럼 표시하는 두 극단을 모두 금지한다.
- 이전 문서 충돌: `ui-ux-page-review.md`의 “마감 공고를 새 목표로 추가하지 않음”보다
  `docs/18-legacy-behavior-preservation-audit.md`의 장기 준비 목표 결정을 우선한다.

### 준비도와 검증 분모가 없는 경우

- `0/0`은 0점이 아니라 계산 대상 필수 요건을 정상적으로 구성하지 못했거나 아직 판정할 수 없는
  상태다. 이를 0% 또는 준비 완료처럼 계산하지 않는다.
- 필수 요건이 실제로 없는 공고, 구조화 실패, 역량 매핑 누락, 사용자 근거 부족을 서로 다른 reason
  code로 보존한다.
- 화면에는 `계산할 수 없음` 또는 `분석 보완 필요`와 구체적 이유를 표시하고 원문 재확인, 재분석,
  운영자 검토 중 적절한 다음 행동을 제공한다.
- 학습 진행률, 프로젝트 준비도, 형식적 지원조건과 지원 추천 가능성을 하나의 준비도 숫자로 합치지
  않는다.

### 분야·챕터 배치

- canonical capability의 정체성과 사용자 완료 상태는 하나로 유지하되, 화면의 분야·chapter는
  project task와 roadmap projection이 제공한 직무·도메인 `sectionMemberships`로 결정한다.
- canonical key prefix의 하드코딩 목록을 화면 분류의 정본으로 사용하지 않는다. 사전에 새 직무나
  도메인이 추가돼도 자동으로 `기타 핵심 역량`에 보내지 않는다.
- 동일 Docker 범위는 백엔드와 보안 chapter에서 문맥 참조로 각각 보일 수 있지만 완료 상태와
  검증 증거는 공유한다. 보안에서 더 넓은 Docker 수행 범위를 요구하면 그 차이만 별도 원자 역량으로
  만든다.

### 분석 동시 실행과 대기열

- 화면의 대기 순서는 실제 claim 가능한 선행 작업과 유효한 lease를 기준으로 계산한다. 사용자에게
  다른 실행 작업이 없는데 `대기 1번째`라고 표시하지 않는다.
- 동일 요청의 중복 job, 취소·실패 terminal job과 lease가 만료된 stale job은 대기 인원에 포함하지
  않는다.
- 사용자별·전체 동시 실행 제한, 공고 구조화 cache hit와 사용자별 후속 분석은 각각 구분해
  관측한다. 대기 중에도 사용자는 다른 화면과 대화를 이용할 수 있고 시작·완료 시 알림을 받는다.
- 미확정 정책: `사용자 한 명당 동시 분석 수`와 `서버 전체 worker 동시성`의 정확한 수치는 부하·비용
  측정 후 별도로 결정한다. 코드에 임의 상수를 제품 정책처럼 고정하지 않는다.

### 인증 세션

- 사용 중인 정상 사용자가 짧은 시간 안에 예고 없이 로그아웃되지 않게 하고, 만료 전에 재인증이
  필요하면 작성 중 입력을 잃지 않는 안내와 복구 경로를 제공한다.
- 로그아웃은 D044대로 cookie 삭제만 하지 않고 탈취된 access token의 서버 측 유효성도 끊는다.
- 미확정 정책: 현재 12시간 access token을 유지할지, 짧은 access token과 회전형 refresh token을
  사용할지, `remember me`를 제공할지는 보안 위협 모델과 실제 사용시간을 확인한 뒤 결정한다.

### URL 수집과 민감 원문 보호

- URL의 사설망·redirect·응답 크기 검증에 더해 DNS 검증 결과와 실제 socket 연결 대상을 묶어 DNS
  rebinding과 검증 후 주소 변경을 방어한다.
- 이력서, 공고 원문과 검증 답변의 보존 기간, 사용자 삭제 전파, 운영자 열람 감사, 백업 폐기 정책을
  출시 전에 확정한다.
- 미확정 정책: DB column 또는 application-level 암호화를 적용할 범위, 검색·중복 판별을 위한
  fingerprint와 암호화 원문의 분리 방식을 성능·키 관리 기준과 함께 결정한다. 평문 저장을 암묵적인
  기본값으로 두지 않는다.

### 대체 공고와 중복 공고

- 추천 결과가 0건인 정상 응답과 timeout·RAG·DB·API 실패를 다른 상태와 메시지로 표시한다. 실패를
  빈 추천 목록으로 조용히 바꾸지 않는다.
- 같은 대표 공고로 병합된 posting은 대체 공고에 한 번만 나타난다. 공고 canonical identity와 원문
  fingerprint를 사용하되 회사명 표기 차이만으로 다른 공고를 만들지 않는다.
- 운영자는 중복 후보의 원문, 회사·직무·경력·마감·출처 근거와 AI 판정 사유를 보고 동일 공고,
  관련 있지만 별도 공고, 무관 공고로 최종 판정한다.
- 사용자별 적합도와 추천 순위는 공용 분석을 재사용하더라도 각 사용자의 증거와 목표로 다시
  계산한다.

### 현재 UI의 보존 기준

- 서비스 명칭은 사용자 화면에서 `JOBIS`로 통일하고 현재 파란색 제품 테마를 유지한다. 듀오링고는
  정보 위계, 버튼 깊이, 피드백과 친근한 상호작용을 참고하는 디자인 기준이며 자산과 화면을 복제하지
  않는다.
- 데스크톱 사이드바는 접을 수 있고 현재 route만 활성화하며 계정·로그아웃 영역은 viewport 아래에
  고정한다. 접기 버튼과 테마 버튼은 겹치지 않는다.
- 채팅은 페이지 전체 높이를 늘리지 않고 대화 영역 내부에서 스크롤한다. 진입 시 최신 메시지를
  보여 주고 과거 메시지 paging을 유지한다.
- composer는 내용에 따라 최대 약 9~10줄까지 늘어난 뒤 내부 스크롤로 전환한다. 사용자 말풍선은
  내용 폭에 맞고 JOBIS 응답·에이전트 진행 카드는 왼쪽에 일관되게 배치한다.
- 질문 카드와 사용자의 선택 답변은 분석 완료 뒤에도 사라지지 않으며, 공고 전체 내용 펼치기
  control은 펼친 내용의 흐름과 맞는 위치에 놓는다.
- 저장소의 검색·정렬·수정·병합·보관·복원·삭제·분석 취소·재시도와 올바른 빈 상태를 이미 존재하는
  동작으로 보고 이후 수정에서 제거하지 않는다.
- 사이드바, 모바일 navigation, dialog focus, 최소 글자 크기와 touch action을 component/E2E
  회귀 테스트로 보호한다.

- 이유: 핵심 로드맵을 고치는 과정에서 이미 해결한 채팅·사이드바·저장소 UX가 다시 사라질 수 있고,
  마감·계산 불가·추천 실패 같은 경계 상태를 암묵적인 기본값으로 두면 사용자에게 사실과 다른
  결론을 보여 준다.
- 대안: 세부사항을 UI 리뷰 문서에만 남기기. 출시 수정의 단일 진입점인 결정 기록에서 누락돼 다시
  퇴행할 위험이 있어 채택하지 않는다.
- 영향받는 계약·코드·테스트: posting lifecycle·deadline state, readiness reason code,
  roadmap section membership/projection, queue lease·worker metrics, auth token·session policy,
  URL fetch transport, data retention/encryption, recommendation error envelope·posting identity,
  AppShell·ChatView·StorageView와 frontend component/E2E.
- 이전 결정: D011의 공용 공고 재사용, D012의 진행 UI, D014의 목표 분리, D022의 원문 보존,
  D038의 모달 동작, D041의 취소 정책, D042의 문맥별 공유 역량과 D044의 수정 게이트를 보완한다.

## 변경 기록 방식

## D046 · 잔여 구현과 운영 기본값을 일괄 확정한다

- 날짜: `2026-08-06`
- 상태: `ACCEPTED · INTEGRATION_LAB_IMPLEMENTED`
- 결정: D010, D016~D020, D035~D036, D043~D045에 남은 구현·검증·운영 기본값을
  `docs/20-bulk-completion-decisions.md`의 14개 항목으로 확정한다.
- 실행 권한: 통합 실험판 수정, Capability Graph의 additive 관리 API, 프론트 테스트 의존성,
  격리 테스트 DB와 최대 20회 공개·합성 공고 AI 비교 평가를 허용한다.
- 보호: Legacy와 기존 사용자 데이터는 보존하며 Git 작업과 데이터 초기화는 별도 요청 전까지
  수행하지 않는다.
- 출시 경계: 통합 실험판의 기능·자동 검증 완료와 실제 운영 V3 전면 전환은 같은 의미가 아니다.
  운영 전환은 실제 사용자 표본과 롤백 검증 후 별도 결정한다.
- 상세 문서: `docs/20-bulk-completion-decisions.md`.
- 구현·검증 기록: `docs/21-bulk-completion-implementation-record.md`.

## D047 · 최신 팀 에이전트와 v3 기능을 단일 AI 서버로 통합한다

- 날짜: `2026-08-06`
- 상태: `ACCEPTED · IMPLEMENTED`
- 결정: `C:\S15P11C202`의 `develop` 브랜치에 있는 최신 팀 에이전트를 기반으로 삼고,
  기존 v3의 회사 맞춤 프로젝트 설계·원자 역량 정규화·Capability Graph 조회·커리어 로드맵
  기능을 같은 Python 서비스의 내부 모듈과 전문 에이전트로 통합한다. Spring 백엔드는 최종적으로
  하나의 JOBIS AI API만 호출한다.
- 근거: 채팅이 JOBIS의 주 작업 공간이며 하나의 오케스트레이터가 공고 접수, 사용자 확인,
  적합도 분석, 프로젝트 설계와 로드맵 생성의 전체 실행 계획·세션·진행 이벤트를 알아야 한다.
  두 AI가 각각 공고를 파싱하고 상태를 소유하면 반복 답변과 상충하는 질문·결과가 생긴다.
- 보존: `C:\jobiss-service-v3-integration-lab`과 `C:\S15P11C202`는 비교 기준으로 수정하지 않는다.
  `C:\JOBIS\AI-v3`는 기능 이식과 회귀 확인이 끝날 때까지 원본으로 보존하지만 별도 AI 서버를
  최종 구조로 유지하지 않는다.
- 대안: 최신 대화 AI와 AI-v3를 독립 서버로 운영한 뒤 나중에 합치기. 경계 계약과 실행 상태가
  두 벌로 굳어질수록 통합 비용과 중복 분석이 커지므로 최종 방향에서 제외한다.
- 영향받는 계약·테스트: chat/analysis API, 세션 상태, 복수 직무 공고 계약, 사용자 확인 상태,
  진행 이벤트, LLM provider 설정, project planning, capability graph lookup, roadmap proposal,
  Spring AI client와 전체 대화·공고·로드맵 회귀 테스트.
- 구현 결과: 최신 팀 에이전트와 검증형 career pipeline이 `C:\JOBIS\AI`의 단일 FastAPI(8400)에서
  실행된다. Spring은 `AiAnalysisClient` 하나만 사용하며 별도 8500 실행기·provider 비교 UI·shadow
  실행 경로는 제거했다. DB의 현재 분석 식별값은 `UNIFIED`이고 `LEGACY`는 과거 데이터 호환을
  위해서만 남는다. 장기 분석의 역할 기반 진행 이벤트, 프로세스 취소, 재접속 복원과 실제 relation을
  보존하는 커리어 그래프 투영을 함께 적용했다.
- 검증: 통합 AI `976 passed`, Spring 강제 재실행 `69 tests`(실패 0, 환경형 19 skip), 격리
  PostgreSQL `6 passed`(skip 0), Capability Graph `24 passed`, 프론트 단위 테스트와 production build,
  Playwright E2E `2 passed`, fixture corpus `40/40`을 확인했다.

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
