# Phase 8 전체 pipeline 실제 모델 평가

- 실행일: 2026-08-04
- provider: Claude Code CLI
- model: `sonnet`
- 입력: 사용자가 확인한 단일 신입 게임 백엔드 공고
- 결과: 1/1 통과
- 전체 실행 시간: 약 146초
- 실행 명령: `ai-v3\.venv\Scripts\python.exe ai-v3\scripts\eval_phase8_pipeline_live.py`

## 결과

- 포지션 수: 1
- 정규화 요건 수: 6
- 목표 프로젝트: `게임 결제 이벤트 비동기 처리 API 시스템`
- roadmap proposal: `DRAFT`
- 회사 기회 최소 경력: 0개월
- progress event: 14개, sequence 누락·중복 없음

```text
POSTING_STRUCTURE          RUNNING → COMPLETED
PROFILE_ASSEMBLY           RUNNING → COMPLETED
FIT_ANALYSIS               RUNNING → COMPLETED
CAPABILITY_NORMALIZATION   RUNNING → COMPLETED
CAPABILITY_GRAPH_LOOKUP    RUNNING → COMPLETED
ROADMAP_PROPOSAL           RUNNING → COMPLETED
RESULT_ASSEMBLY            RUNNING → COMPLETED
```

## 실행 중 발견하고 바로잡은 계약 문제

첫 시도에서 `VerifiedPostingSnapshot`은 존재하지만 `SourceDocument.status`가
`AWAITING_VERIFICATION`인 불가능한 조합을 평가 스크립트가 만들었다. 기존 posting service가 이를
분석 전에 차단했으나 pipeline 요청 계약은 더 일찍 막지 못했다.

수정 후 `AnalysisPipelineRequest`는 `SourceDocument.status=VERIFIED`, 동일 source ID와 revision을
모두 요구한다. 따라서 snapshot만 붙여 검증 gate를 우회하는 요청은 Pydantic 단계에서 거부된다.

## 남은 성능 판단

146초는 기능 정확성 검증 결과이며 출시 성능 기준을 통과했다는 뜻은 아니다. 실제 운영 전에는
여러 공개 공고로 p50/p95, 단계별 LLM 시간, 공용 구조화 cache와 사용자별 적합도 cache 효과를
측정해야 한다. 진행 이벤트는 분석을 빠르게 만들지는 않지만 사용자가 멈춤으로 오해하지 않게 한다.

