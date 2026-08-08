# Phase 6 실제 모델 평가

- 실행일: 2026-08-04
- provider: Claude Code CLI
- model: `sonnet`
- normalizer: `capability-normalizer-3.0.0`
- 결과: 9/9 통과
- 실행 명령: `ai-v3\.venv\Scripts\python.exe ai-v3\scripts\eval_phase6_live.py`

## 평가 결과

| ID | 입력 | 기대 | 결과 |
|---|---|---|---|
| NORM-001 | Java 개발 경험 | `lang.java` 후보 | 통과 |
| NORM-002 | Spring Boot 웹 서버 | `framework.spring-boot` 후보 | 통과 |
| NORM-003 | MySQL JOIN | 기존 MySQL 범위로 연결 | 통과 |
| NORM-004 | FluxionDB 스트림 저장소 | 신규 후보 보존 | 통과 |
| NORM-005 | Spring 트랜잭션 전파·격리·롤백 | Spring Boot가 아닌 transaction 범위 | 통과 |
| NORM-006 | 매치메이킹·상태 동기화 | 게임 클라이언트가 아닌 게임 서버 범위 | 통과 |
| NORM-007 | Celery와 REST API | 두 원자 요건으로 재분리 | 통과 |
| NORM-008 | 게임 열정·책임감 | 기술 노드 제외, `FIT_ONLY` | 통과 |
| NORM-009 | 회사 맞춤 프로젝트 완성 | 기술 노드 제외, `PROJECT_CONTEXT` | 통과 |

전체 실행 시간은 약 68초였다. 7~9번처럼 결정론적으로 처리 가능한 항목은 모델을 호출하지 않는다.

## 확인된 성질

- 사전에 없는 기술을 가장 가까운 기존 기술로 강제하지 않는다.
- catalog 이름뿐 아니라 scopeDefinition을 사용해 하위 주제와 전문 범위를 구분한다.
- AI의 기존 catalog 연결도 자동 승인하지 않는다.
- 복합 요건은 하나의 긴 기술 노드가 아니라 `SPLIT_REQUIRED`로 구조화 단계에 돌려보낸다.
- 행동 특성, 업무, 프로젝트, 경력, 자격을 학습 기술과 분리한다.

## 남은 한계

- 후보 catalog 검색은 현재 요청에 전달된 snapshot을 사용한다. 대형 catalog의 검색·버전·출처는
  Phase 6.5 외부 역량 지식 그래프 adapter에서 검증한다.
- 운영자 UI와 실제 병합/되돌리기 저장은 Phase 8 Spring 통합 범위다. 현재는 감사 계약까지만
  구현했다.
