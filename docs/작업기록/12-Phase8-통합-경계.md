# Phase 8 통합 경계와 현재 구현

## 결론

v3 AI 서버는 분석 의미와 단계 이벤트를 만들고, Spring은 사용자·DB·작업 수명주기·공개
로드맵을 소유한다. 기존 `C:\jobiss-service-real-agent-lab`은 아직 수정하지 않았다.

## v3에 구현된 통합 진입점

### 동기 결과

`POST /v1/analysis-pipeline/run`

확인된 `SourceDocument`와 `VerifiedPostingSnapshot` 한 revision을 받아 다음 순서를 실행한다.

1. 복수 포지션 공고 구조화
2. 포지션 또는 신입/경력 트랙 질문 판정
3. 사용자 근거 기반 적합도 분석
4. Capability Graph의 승인된 원자 역량 catalog 조회와 정규화
5. 회사 맞춤 프로젝트 과제 및 과제별 원자 역량 선택
6. 선택된 원자 역량의 승인된 graph closure 조회
7. 기존 진행도를 보존한 로드맵 초안 컴파일

질문이 필요하면 이후 단계를 실행하지 않고 `AWAITING_CLARIFICATION` 또는
`AWAITING_USER_EVIDENCE`로 반환한다. 완료 결과의 로드맵 상태는 항상 `DRAFT`다.

### 진행 스트림

`POST /v1/analysis-pipeline/stream`

- media type: `application/x-ndjson`
- event type: `PROGRESS | RESULT | ERROR`
- 모든 event는 증가하는 sequence를 갖는다.
- 공개 가능한 단계·상태·경과 시간만 포함하고 내부 chain-of-thought는 포함하지 않는다.
- `X-Request-ID`, `X-Trace-ID`, `X-JOBIS-AI-CONTRACT`을 유지한다.
- 프록시 버퍼링을 막기 위해 `X-Accel-Buffering: no`를 반환한다.

## Spring이 해야 할 일

### Provider 선택

```text
AI_PROVIDER=legacy | v3 | shadow
LEGACY_AI_BASE_URL=http://127.0.0.1:8200
V3_AI_BASE_URL=http://127.0.0.1:8300
```

- `legacy`: 기존 API만 호출한다.
- `v3`: 원문 확인 후 v3 pipeline을 호출한다.
- `shadow`: 사용자에게는 primary 한 결과만 보여주며 shadow 결과는 DB 변경·메시지·알림을
  만들지 않는다.
- v3 실패를 조용히 legacy 성공으로 바꾸지 않는다. 사용자가 재시도 또는 legacy 재분석을
  선택하게 한다.

### 작업 수명주기

기존 Spring의 queue, lease, stale recovery, cancel, retry를 재사용한다. AI 서버에 두 번째 작업
DB를 만들지 않는다.

- 요청 전에 사용자 RLS 범위 안에서 증거 묶음과 현재 로드맵 snapshot을 만든다.
- 각 NDJSON progress를 `(job_id, sequence)` unique key로 저장한다.
- 같은 sequence의 재전송은 성공으로 취급하되 중복 insert하지 않는다.
- 질문 결과는 작업을 `WAITING`으로 바꾸고 lease를 해제한다.
- 답변 후 같은 verified snapshot과 ambiguity ID로 새 실행 revision을 시작한다.
- 취소 시 HTTP 호출을 중단하고 늦게 도착한 RESULT는 job revision·status 조건부 update로 버린다.
- 서버 재시작 시 만료된 RUNNING lease만 회수한다.

### 로드맵 미리보기·적용·취소

`compiler_reference.py`는 Spring 컴파일러가 맞춰야 할 의미 기준이다.

- proposal의 `basedOnRoadmapVersion`과 현재 공개 버전이 다르면 `409`로 거부한다.
- canonical 역량은 기존 node ID와 진행 상태를 유지한다.
- 신규 회사는 목표 프로젝트·경력/자격 관문·기회만 추가한다.
- 같은 직무의 가장 가까운 낮은 경력 단계 회사와 새 경력 관문 사이에
  `CAREER_STAGE_ORDER`를 만든다.
- 미리보기는 다음 버전 snapshot을 계산하지만 공개 버전을 바꾸지 않는다.
- 적용은 한 트랜잭션에서 optimistic version check 후 수행한다.
- 취소는 proposal만 `CANCELLED`로 바꾸며 공개 snapshot과 진행 상태를 건드리지 않는다.

## 프론트가 해야 할 일

- URL·이미지 수집 후 원문 확인 카드가 먼저 나타나야 한다.
- `PROGRESS`의 실제 stage 수와 색으로 시각화한다. 고정된 5개 에이전트를 가장하지 않는다.
- 1초 미만 단계도 완료 흔적을 최소 표시 시간 동안 남기되 서버 실행을 인위적으로 늦추지 않는다.
- 질문은 한 번에 하나만 표시하고 답변한 ambiguity ID를 함께 전송한다.
- 분석 중 다른 페이지로 이동해도 Spring status/event API로 복원한다.
- 완료 후에는 분석 결과와 “새 로드맵 초안”을 구분한다.
- 미리보기 화면에 `적용`, `취소`, `현재 버전 보기`를 모두 제공한다.

## 2026-08-04 통합판 구현 상태

`C:\jobiss-service-v3-integration-lab`에 다음을 additive 방식으로 구현했다.

- Spring V3 client, source verification, pipeline worker와 사용자별 계약 원문 저장
- V35~V38 migration과 V3 source·snapshot·run·proposal·published roadmap RLS
- 실제 NDJSON stage 저장, 새로고침 복원, 질문 대기, 늦은 결과의 worker/revision 검사
- 채용공고 페이지의 TEXT·URL·IMAGE 접수와 사용자의 원문 확인 UI
- 기존 분석 상세 화면 안의 V3 원자 요건·근거 상태·동적 진행 단계
- Spring reference compiler와 DRAFT 미리보기·적용·취소·버전 발행 API
- 하나의 지도에서 section·display rank·진행 상태를 보여주는 V3 Vue 화면
- Spring broad catalog 입력 제거와 Capability Graph 원자 catalog 직접 조회
- 공고 요구사항을 프로젝트 과제·완료 기준·원자 역량으로 분해하는 계약 검증형 planner
- 프로젝트 노드 상세의 과제 목록과 연결 원자 역량 표시
- V39 사용자별 원자 역량 상태, 상태 event와 legacy broad 이관 후보 RLS 저장소
- 적용된 원자 노드의 graph 버전·기술 컨테이너·검증 방법 보존과 다음 분석 경계 반영
- V40~V42 원자 목표·제외 범위·완료 정책과 사용자 검증 세션·문항·운영 검토 RLS
- 그래프 범위 안의 2~3문항 검증, 재학습·재도전·이의신청·운영자 승인 상태 전이
- 그래프 `SELF_CONFIRM|ASSESSMENT` 정책 기반 완료 UI와 legacy 후보 사용자 확인 API

실제 브라우저에서 원문 접수 → 확인 → V3 작업 생성 → 명시적 provider 오류 표시를 확인했고,
테스트 초안으로 미리보기 v2 → PUBLISHED v2 적용을 확인했다. 사용자별 같은 contract ID 저장과
교차 조회 차단도 실제 PostgreSQL 트랜잭션에서 검증했다.

## 아직 남은 통합 경계

- 채팅 일반 발화에 포함된 URL·공고 본문을 자동 의도 분류한 뒤 V3 확인 카드로 전환
- `AI_PROVIDER=legacy|v3|shadow`의 전역 전환과 개인정보 승인된 shadow comparator
- 사용자 확인 대기 중인 source 화면을 새로고침 후 복원
- 실제 취소 HTTP 전파와 V3 전용 동시성·lease 통합 테스트 확대
- 운영자 신규 기술·이상 추출 검토 화면
- 공고별 프로젝트 과제 초안을 사용자 확인·운영자 승인 흐름과 연결
- 기존 사용자 broad 역량 이관 후보의 운영자 일괄 검토·취소 흐름
- 회사 맞춤 프로젝트 과제 결과물 검증 계약

외부 Capability Graph의 실제 catalog와 closure HTTP 계약은 연결되었다. 그래프가 없으면 전체
pipeline은 명시적으로 실패하며, 적절한 원자 역량이 없는 공고 요구사항은 사용자 범위의 검토
대상으로 남긴다. 이 상태에서 임의의 기술 선행관계를 생성하거나 legacy 결과로 조용히
대체하지 않는다.
