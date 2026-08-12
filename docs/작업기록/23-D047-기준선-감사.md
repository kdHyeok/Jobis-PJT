# 23. D047 최신 팀 AI 기준선 감사

- 감사일: 2026-08-06
- 결정: `D047 · 최신 팀 에이전트와 v3 기능을 단일 AI 서버로 통합한다`
- 최신 팀 기준: `C:\S15P11C202`, `develop`, `20b5a5b66434dc091cdab1262a8440c80d4ecb9e`
- v3 비교 기준: `C:\jobiss-service-v3-integration-lab`
- 통합 작업공간: `C:\JOBIS`

## 1. 결론

`TASK.md`의 `READY_FOR_BASELINE_AUDIT`는 감사 시작 시점의 실제 상태와 일치했다. 다만
“통합 구현 미시작”은 **최신 팀 AI를 기반으로 한 단일 서버 통합**에 한해서만 맞다.
작업공간에는 이전 AI-v3 통합 실험에서 만든 Spring 이중 AI client, v3 DB/로드맵/검증 흐름,
확장 채팅 UI와 계약 fixture가 이미 존재한다.

따라서 다음 작업은 기존 `C:\JOBIS\AI`를 그대로 확장하는 것도, 최신 `AI`를 통째로 덮어쓰는
것도 아니다.

1. 최신 팀 AI의 오케스트레이터·세션·provider·평가 하네스를 실행 기반으로 사용한다.
2. 현재 JOBIS의 확장 채팅·공고 접수 계약은 Spring/프론트 호환 경계로 보존하되, Python 모델을
   `service_contract.py`가 덮어쓰는 이중 정본 구조는 제거한다.
3. AI-v3의 복수 포지션·원문 확인·적합도 증거 상태·프로젝트 우선 설계·원자 역량 정규화·
   Capability Graph·로드맵 proposal을 같은 Python 프로세스의 내부 모듈과 전문 에이전트로 이식한다.
4. 동등성 검증 뒤 Spring의 `V3AiClient`와 별도 8500 런타임을 제거한다.

## 2. 문서와 실제 파일의 차이

| 항목 | 문서 기록 | 실제 확인 | 판정 |
|---|---|---|---|
| 최신 원본 브랜치 | 일부 AI 작업로그는 feature 브랜치 표기 | Git은 깨끗한 `develop...origin/develop` | 작업로그가 오래됨 |
| 최신 AI 테스트 | `작업로그/지금상태.md`에 763건 | 원본을 캐시 없이 실행해 800건 통과 | 문서가 오래됨 |
| AI-v3 README | Phase 1, 주요 기능 미구현 | pipeline·project·normalization·graph·roadmap·assessment와 162개 테스트 존재 | README가 오래됨 |
| 현재 JOBIS 통합 | `TASK.md`에 아직 시작하지 않음 | 이전 실험의 dual client·v3 Spring/DB/UI가 이미 존재 | D047 관점에서만 미시작 |
| Git 상태 | JOBIS는 저장소 아님 | 실제 `.git` 없음 | 일치 |

실제 코드와 테스트를 정본으로 사용하고, 위 상태 문서는 통합 중 갱신 대상이다.

## 3. 파일·테스트 기준선

실행 산출물, `.env`, SQLite, 로그, egg-info를 제외하고 최신 AI와 현재 JOBIS AI를 해시 비교했다.
감사 시작 시점 기준으로 최신에만 36개, JOBIS에만 18개, 공통 경로 중 내용이 다른 파일이 69개였다.

최신에만 있는 핵심 구현:

- `codex_llm.py`, `codex_oauth_adapter/`: 현행 Codex provider
- `grade_decision.py`, `grade_judge.py`: 하이브리드 적합도 등급 판정
- `posting_detection.py`, `readiness.py`: 공고 인입·분석 준비도
- `v2bridge/assessment.py`, `v2bridge/enrich.py`: 현행 역량 평가·제안 생산자
- 관련 신규 테스트 11개

현재 JOBIS에만 있던 핵심 구현:

- `v2bridge/service_contract.py`: Spring 실험판 확장 계약
- `v2bridge/role_catalog.py`, `v2bridge/taxonomy.py`: 서비스 경계 직무·로드맵 재분류
- `webbridge/`: 폐기된 별도 WebSocket/개발 UI 경로
- `/v1/posting-imports`, `/v1/competency-learning`과 확장 채팅 계약 테스트

검증 결과:

| 대상 | 결과 | 해석 |
|---|---:|---|
| 최신 원본 AI | 800 passed | 원본 파일에 캐시·세션을 쓰지 않는 설정으로 실행 |
| 통합 전 JOBIS AI | 705 passed | 외부 LLM을 쓰지 않는 결정론 회귀 |
| AI-v3 | 162 passed | fixture/provider stub 기반 |
| Spring | 75 tests, 0 failure, 19 skipped | 56개 실행; PostgreSQL 통합 19개는 성공으로 간주하지 않음 |
| 프론트 | node 4 + vitest 1 passed, production build 성공 | Playwright는 이번 감사에서 미실행 |
| 회귀 corpus | 40 cases, P0 22, documented 40 | 구조 검증 통과 |

## 4. 기능별 분류

판정은 `PRESERVE | IMPROVE | REPLACE | REMOVE | MISSING | CONFLICT`를 사용한다.

| 기능/경계 | 최신 팀 AI | 현재 JOBIS / AI-v3 | 판정 | 통합 처리 |
|---|---|---|---|---|
| 자유 대화·플래너·관찰 | 현행 오케스트레이터와 800개 회귀 | 이전 버전, 확장 응답 adapter | `REPLACE` | 내부 실행은 최신으로 교체하고 사용자향 확장 응답은 adapter에서 유지 |
| 세션 상태 전이 | `AgentResult.sessionUpdates`, SQLite/memory store | workspaceState와 Spring JSONB 정본 | `IMPROVE` | Spring snapshot으로 hydrate하고 오케스트레이터만 상태를 갱신 |
| ChatResponse 계약 | `collected.outputs.sessionState` 중심 | plan/workProducts/actions/warnings 중심 | `CONFLICT` | 하나의 명시적 서비스 계약으로 합치고 `models.py` import 덮어쓰기 제거 |
| 공고 URL·원문·이미지 접수 | URL fetch·붙여넣기 승격 | AI-v3 source/snapshot 검증, 현재 posting-import endpoint | `IMPROVE` | 모든 진입점을 SourceDocument→사용자 확인 snapshot으로 통일 |
| 단일 `NormalizedJobPosting` | 한 직무·한 경력 중심 | AI-v3 `positions[]` | `REPLACE` | 원본 분석 정본은 `StructuredPosting.positions[]` 사용 |
| 복수 직무 질문 | 최신 계약은 질문을 표현 가능하나 코어는 단일 구조 | AI-v3가 직무→경력 질문을 한 번에 하나씩 수행 | `PRESERVE` | v3 resolution을 오케스트레이터 확인 단계로 이식 |
| 공고 선택 전 분석 게이트 | readiness/질문 계약 | posting review와 confirmed review ID | `IMPROVE` | 원문·직무·경력 확인 뒤에만 fit/project 실행 |
| 적합도 계산 | 하이브리드 grade와 unknown 보존 | v3 CLAIMED/EVIDENCED/VERIFIED/NOT_MET/UNKNOWN | `CONFLICT` | 최신 실행 경로에 v3 증거 상태를 넣고 최종 점수는 결정론 계산 |
| 회사 맞춤 프로젝트 | `targetProject` 요약 생성 | v3가 project task를 먼저 설계 | `REPLACE` | v3 project-first 설계를 전문 에이전트로 이식 |
| 원자 역량 정규화 | 폐쇄 taxonomy/adapter 분류 | 승인 catalog, 신규 후보, 운영자 검토 | `REPLACE` | v3 normalization을 사용하고 미등록 역량을 누락하지 않음 |
| Capability Graph 조회 | 없음 | version/hash 검증 read-only closure | `MISSING` | v3 port를 내부 tool로 이식; 임의 fallback graph 금지 |
| 커리어 그래프 proposal | competencyProposal과 Spring legacy assembler | v3 roadmap proposal + Spring compiler | `IMPROVE` | v3 의미를 보존하되 현재 목표 전체를 재조립하는 Spring compiler 유지 |
| 분석 진행 이벤트 | `/v1/analyses/stream`, 실제 trace | v3 pipeline progress, Spring 영속 복원 | `PRESERVE` | 내부 이벤트를 현재 NDJSON `runId/sequence` 계약 하나로 투영 |
| 역량 검증 | 최신 `/v1/competency-assessments` | v3 원자 범위·부분 재시험·idempotency | `IMPROVE` | 원자 scope 계약을 최신 assessment agent에 적용 |
| 역량 학습 가이드 | 최신에 없음 | 현재 JOBIS `/v1/competency-learning` | `MISSING` | 서비스 호환 endpoint를 보존하고 실제 학습 agent로 명시 |
| LLM provider | 현행 Codex OAuth와 provider 경계 | 구 `codex_cli_llm.py`, AI-v3 별도 provider | `REPLACE` | 최신 provider 창구 하나만 사용, 역할별 tier는 설정으로 관리 |
| Webbridge | 최신에서 폐기 명시 | 현재 JOBIS에만 잔존 | `REMOVE` | 회귀 확인 뒤 코드·문서·script 제거 |
| 별도 AI-v3 서버 | 없음 | 8500 포트와 `V3AiClient` | `REMOVE` | 기능 이식 완료 전까지만 비교 원본으로 보존 |
| Spring dual/shadow provider | 최신은 단일 `AiAnalysisClient` | `AiAnalysisClient` + `V3AiClient` + shadow | `CONFLICT` | parity 동안 비교만 유지하고 최종 client/base URL을 하나로 축소 |
| 프론트 provider 분기 | 없음 | `?provider=v3`와 V3 전용 표현 일부 | `REMOVE` | 사용자에게 provider를 숨기고 하나의 실행/지도 모델로 통합 |
| DB·RLS·큐·버전·승인 | 최신 Spring과 실험판 모두 보유 | v3 migration·compiler·operator review 확장 | `PRESERVE` | AI 제안/사용자 승인 경계를 유지하고 SQL 실제 PostgreSQL 검증 |

## 5. 계약 충돌의 핵심

현재 `C:\JOBIS\AI\src\jobis_ai\v2bridge\models.py`는 파일 끝에서
`service_contract.py`의 같은 이름을 `import *`로 덮어쓴다. 이 때문에 파일 앞부분의 모델과
런타임에서 실제 노출되는 모델이 다르다. 최신 팀 코드의 `models.py`를 가져오면 다음 충돌이
즉시 발생한다.

- 최신 chat은 `collected`와 `sessionState`를 사용하고 현재 Spring은 plan/work product를 기대한다.
- 최신 `JobContext`의 일부 필드는 아직 optional이고 현재 계약은 필수다.
- 현재 계약은 QA/EMBEDDED track, TEXT 질문, absence 확인, 학습 endpoint를 추가했다.
- 최신 응답은 legacy `changeProposal`을 함께 보존하지만 현재 서비스 계약은 제거했다.

통합 시 모델 이름 덮어쓰기를 유지하지 않는다. 내부 도메인 모델과 외부 서비스 DTO를 명시적으로
분리하고 mapping에서 누락을 오류로 드러낸다.

## 6. 회귀 fixture

통합 구현 전에 다음 fixture를 추가했다.

- `contract-fixtures/d047/multi-role-analysis-baseline.json`
- 최신 `/v1/analyses` 요청, `NEEDS_INPUT` 응답, 3개 NDJSON 진행 이벤트
- AI-v3의 두 `positions[]`와 결정론적 `POSITION_SELECTION` 질문

fixture는 다음을 막는다.

- 프론트엔드와 백엔드를 FULLSTACK 또는 하나의 직무로 병합
- 직무 선택 전에 적합도·프로젝트·로드맵 생성
- 협업 대상 언급을 모집 직무와 혼동
- 진행 이벤트의 다른 `runId` 또는 비연속 sequence

현재 AI 계약 테스트 2개와 AI-v3 계약 테스트 1개가 같은 JSON을 검증한다.

## 7. 구현 순서

1. **최신 코어 기준화**: 최신 AI의 변경 파일과 신규 테스트를 JOBIS로 가져오되 확장 서비스 계약을
   임시 adapter로 격리한다.
2. **내부 v3 모듈 이식**: source→interpretation→resolution→fit→project→normalization→graph→roadmap
   순서로 `jobis_ai` 내부에 옮기고 각 단계를 AgentSpec/tool manifest에 선언한다.
3. **단일 실행 상태**: v3 pipeline의 checkpoint를 별도 job state가 아니라 오케스트레이터 session
   asset으로 연결하고 Spring JSONB snapshot으로 복원한다.
4. **단일 HTTP 계약**: 현재 Spring/프론트가 필요한 확장 필드를 하나의 버전된 DTO로 정리한다.
5. **Spring 전환**: `V3AiClient` 호출을 `AiAnalysisClient`로 옮기고 같은 분석 job/event/cancel 경로를
   사용한다.
6. **런타임 정리**: 실제 PostgreSQL·브라우저·live provider parity 후 8500 서버, shadow provider,
   webbridge와 provider UI 분기를 제거한다.

## 8. 남은 검증·차단 요인

- PostgreSQL 통합 테스트 19개가 현재 환경 조건으로 skip됐다. DB 동작은 미검증 상태다.
- 최신 원본과 현재 JOBIS의 live LLM/RAG 호출은 이번 감사에서 실행하지 않았다.
- source/URL/image 실사이트, 사용자 확인 후 재개, 취소 전파, 새로고침 복원 Playwright가 필요하다.
- `C:\JOBIS`에 Git 메타데이터가 없어 대규모 기준화 전에 파일 단위 변경 목록과 테스트 결과를
  계속 `TASK.md`에 남겨야 한다.
