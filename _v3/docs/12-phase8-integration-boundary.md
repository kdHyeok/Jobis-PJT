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
4. 학습 역량 정규화
5. 승인된 역량 그래프 closure 조회
6. 회사 맞춤 로드맵 초안 생성

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

## 아직 구현하지 않은 것

- 기존 Spring DTO·client·DB migration·RLS policy
- Spring의 v3 provider flag와 shadow comparator
- 실제 PostgreSQL proposal/event 저장
- 기존 Vue 화면의 원문 확인 카드와 진행 복원
- 브라우저 E2E와 실제 취소 전파
- 외부 `C:\jobiss-capability-graph-lab` 계약 호환성

이 항목들은 기존 실험판을 수정해야 하므로, 별도 통합 작업에서 additive migration과 feature
flag로 진행한다. 현재 코드만으로 기존 서비스 동작이나 데이터는 바뀌지 않는다.

