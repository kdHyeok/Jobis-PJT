# AI 에이전트 연동 가이드

이 문서는 JOBISS 백엔드와 AI 에이전트 사이의 현재 계약을 고정합니다. AI 팀은
내부 오케스트레이터와 역할 구성을 자유롭게 바꿀 수 있지만, 아래 HTTP 입출력과
이벤트 의미는 유지해야 합니다.

## 책임 경계

AI 서버가 담당하는 일:

- 공고의 모호함 판단과 한 번에 한 가지 추가 질문 생성
- 회사·직무·경력 조건, 표준 역량 후보, 필수·우대·업무 관계 추출
- 회사 맞춤 프로젝트 제안
- 자유 대화, 커리어 자료 파편화, 결과물 증빙 검토
- 목표 공고 맥락을 반영한 역량 검증 문제와 답변 평가
- 공고 분석 에이전트 단계와 현재 상태 이벤트 전달

Spring 백엔드가 담당하는 일:

- 사용자 인증, PostgreSQL RLS, 원문과 결과 영속화
- AI 출력 스키마·참조·범위·수준 재검증
- 동일 역량 정규화와 공용 카탈로그/사용자 진행 상태 분리
- 검증된 역량과 경력 조건으로 최종 지원 판단 계산
- 통합 로드맵의 노드·간선·경력 관문·좌표 계산
- 작업 큐, 동시 실행 수, 재시도, 알림과 공개 버전 관리
- 실제 공고 카탈로그에서 대체 공고 검색

AI는 로드맵 좌표나 간선을 만들지 않으며, 백엔드는 모델의 내부 사고 과정을
요구하거나 저장하지 않습니다.

## 내부 HTTP 엔드포인트

모든 요청은 `X-JOBISS-AI-SECRET` 헤더가 필요합니다.

| 경로 | 용도 |
| --- | --- |
| `POST /v1/analyses/stream` | 공고 분석과 진행 이벤트, 권장 경로 |
| `POST /v1/analyses` | 스트림 미지원 구현을 위한 호환 경로 |
| `POST /v1/chat` | 자유 대화 |
| `POST /v1/career-extractions` | 이력서·프로젝트 자료 파편화 |
| `POST /v1/competency-assessments` | 기술 역량 문제 생성과 답변 평가 |
| `POST /v1/evidence-verifications` | 프로젝트·자격·경험 결과물 검토 |
| `GET /v1/health` | 프로세스 상태 |
| `GET /v1/ready` | 공급자 설정을 포함한 준비 상태 |

Python의 기준 모델은 `ai-server/app/models.py`, Java의 대칭 모델은
`backend/src/main/java/com/jobiss/analysis/AiContracts.java`입니다. 필드를
추가할 때는 두 모델과 계약 테스트를 같은 변경 단위로 수정합니다.

## 공고 분석 스트림

응답 형식은 `application/x-ndjson`입니다. 줄바꿈은 이벤트 경계이므로 한 이벤트를
여러 줄로 출력하면 안 됩니다. 모든 이벤트는 같은 `runId`를 사용하고 `sequence`를
엄격히 증가시킵니다.

첫 줄은 전체 실행 계획입니다.

```json
{"type":"RUN_STARTED","runId":"5dd04f6b-a633-42f4-a46e-8aca04ce49f1","sequence":1,"occurredAt":"2026-07-31T07:00:00Z","stages":[{"id":"context","label":"맥락 정리","role":"공고와 사용자 정보를 정리합니다","message":"분석할 범위를 확인하고 있어요.","color":"#1CB0F6"},{"id":"requirements","label":"요구 역량 분석","role":"공고의 기술과 조건을 구조화합니다","message":"필수·우대 조건을 분리하고 있어요.","color":"#CE82FF"},{"id":"validation","label":"결과 검증","role":"계약과 참조 무결성을 검사합니다","message":"지도에 안전하게 반영할 수 있는지 확인해요.","color":"#FF9600"}],"stage":null,"result":null,"errorCode":null,"errorMessage":null}
```

단계 상태는 `PENDING`, `RUNNING`, `WAITING`, `COMPLETED`, `FAILED` 중 하나입니다.

```json
{"type":"STAGE_UPDATED","runId":"5dd04f6b-a633-42f4-a46e-8aca04ce49f1","sequence":2,"occurredAt":"2026-07-31T07:00:01Z","stages":[],"stage":{"id":"context","status":"RUNNING","message":"공고의 직무와 경력 조건을 확인하고 있어요."},"result":null,"errorCode":null,"errorMessage":null}
```

정상 종료는 기존 `/v1/analyses` 응답 전체를 `result`에 담습니다.

```json
{"type":"RESULT","runId":"5dd04f6b-a633-42f4-a46e-8aca04ce49f1","sequence":9,"occurredAt":"2026-07-31T07:00:15Z","stages":[],"stage":null,"result":{"status":"NEEDS_INPUT","question":{"key":"primary_track","text":"어느 직무로 분석할까요?","reason":"복수 직무 공고입니다.","options":[{"value":"backend","label":"백엔드","description":"Java·Spring 직무 기준"},{"value":"frontend","label":"프론트엔드","description":"TypeScript·React 직무 기준"}]},"job":null,"evaluation":null,"competencyProposal":null},"errorCode":null,"errorMessage":null}
```

실패는 HTTP 스트림을 갑자기 닫지 않고 마지막 `ERROR` 이벤트로 전달합니다.

```json
{"type":"ERROR","runId":"5dd04f6b-a633-42f4-a46e-8aca04ce49f1","sequence":9,"occurredAt":"2026-07-31T07:00:15Z","stages":[],"stage":null,"result":null,"errorCode":"INVALID_AI_RESPONSE","errorMessage":"구조화 결과 검증에 실패했습니다."}
```

`RUN_STARTED.stages`는 1~12개까지 가능하므로 실제 에이전트 역할 수에 맞춰
동적으로 보낼 수 있습니다. 화면의 피자형 진행 표시는 이 목록과 각 단계의 고유
색을 그대로 사용합니다. 너무 빨리 끝난 단계를 보이게 하려고 서버가 허위 지연을
넣지는 않습니다.

현재 기준 단계는 단순 타이머가 아니라 실제 작업 경계를 나타냅니다.

- 공통: `CONTEXT_ASSEMBLY`
- 확인이 필요한 경우: `CLARIFICATION`
- 최초 분석: `POSTING_ANALYSIS`
- 동일 원문·동일 답변의 공통 분석을 재사용하는 경우:
  `SHARED_REUSE` 다음 `FIT_ANALYSIS`
- 완료 경로: `CONTRACT_VALIDATION` 다음 `RESULT_ASSEMBLY`

공통 분석 캐시는 공고 원문 지문과 추가 질문 답변 지문을 키로 사용하며, 회사·직무·
경력·요구 역량처럼 사용자와 무관한 구조만 저장합니다. 사용자의 커리어 근거,
준비도 판정, 대체 공고 결과는 캐시에 넣지 않고 매 요청마다 다시 계산합니다.

## 공고 분석 결과 원칙

- `status=NEEDS_INPUT`이면 `question`만 있고 최종 결과는 없어야 합니다.
- `status=COMPLETED`이면 `job`, `evaluation`, `competencyProposal`이 모두
  있어야 합니다.
- 역량은 이름만이 아니라 `canonicalKey + scopeDefinition + requiredLevel`로
  구분합니다.
- 모든 로드맵 대상 역량은 비어 있지 않은 `scopeDefinition`과
  `verificationMethod`를 가져야 합니다.
- 정성적 태도는 `roadmapEligible=false`로 반환하며 회사 맞춤 프로젝트의 필요
  역량으로 참조하지 않습니다.
- `requirements`와 `targetProject`의 역량 참조는 같은 응답의 `ref`를 가리켜야
  합니다.
- AI의 `evaluation`은 설명 자료이며 최종 지원 판정은 백엔드가 재계산합니다.

## 목표 기반 역량 검증

`POST /v1/competency-assessments` 요청에는 다음 세 종류의 문맥이 함께 옵니다.

- `competency`: 검증할 기술의 정확한 범위, 요구 수준, 평가 기준
- `target`: 현재 목표 공고, 회사·직무·도메인, 장기 최종 목표
- `turns`: 현재 세션에서 이미 출제한 문제, 사용자 답변, 저장된 점수
- `retainedScores`: 최근 30일 안에 같은 역량·같은 수준에서 이미 통과한
  `CONCEPT`, `CODE`, `SCENARIO` 영역과 점수

현재 목표는 문제의 핵심 범위와 난이도를 결정합니다. 최종 목표는 심화 예시를
고르는 보조 문맥일 뿐이며, 검증 대상 기술의 범위를 넘어선 개념을 필수 정답으로
요구하면 안 됩니다. 예를 들어 Java 언어 노드 문제에서 Spring 트랜잭션 지식을
통과 조건으로 삼지 않습니다.

백엔드는 새 시도에서 최대 5문항을 허용하고, 이월 점수와 현재 시도의 각 유형별
최고 점수로 평균 75점·각 유형 60점 기준을 다시 계산합니다. 답변 채점과 다음 문제
생성은 서로 다른 AI 호출로 분리되어, 사용자가 답변에서 언급한 인접 기술이 다음
핵심 문제의 필수 범위로 번지는 것을 막습니다. `coreCriteria`만 통과 점수에
반영하고 `futureExtensions`는 장기 목표에 연결한 학습 제안으로 보존합니다. AI가
직접 사용자 역량 완료 상태를 변경하지 않습니다. 재도전 문제는 이월되지 않은
유형 또는 아직 기준에 못 미친 유형의 새로운 변형이어야 합니다.

## 로컬 실행과 계약 테스트

AI 서버:

```powershell
cd C:\jobiss-service\ai-server
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

백엔드:

```powershell
cd C:\jobiss-service\backend
$env:JAVA_HOME="C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot"
$env:Path="$env:JAVA_HOME\bin;$env:Path"
.\gradlew.bat clean test
.\gradlew.bat bootRun
```

AI 팀 구현이 스트림 경로를 아직 지원하지 않으면 백엔드는 404/405에 한해서 기존
`POST /v1/analyses`를 사용합니다. 따라서 기존 분석을 깨뜨리지 않고 스트리밍을
추가할 수 있지만, 피자형 화면의 실제 역할·단계 표시를 사용하려면 스트림 계약을
구현해야 합니다.
