# Phase 5 실제 모델 평가

- 실행일: 2026-08-04
- provider: Claude Code CLI
- model: `sonnet`
- matcher: `fit-matcher-3.0.0`
- policy: `fit-policy-0.1`
- 결과: 8/8 통과
- 실행 명령: `ai-v3\.venv\Scripts\python.exe ai-v3\scripts\eval_phase5_live.py`

## 목적

자동 계약 테스트만으로는 모델이 단어가 비슷한 역량을 과도하게 연결하는지 확인할 수 없다.
그래서 기존 서비스에서 실제로 문제가 됐던 범위 침범과 정성 요소 오인식을 중심으로 평가했다.

## 결과

| ID | 공고 요건 | 사용자 검증 역량 | 기대 | 결과 |
|---|---|---|---|---|
| FIT-001 | Java 개발 경험 | Java 언어 범위 | 직접 연결 | `VERIFIED_MET` |
| FIT-002 | Java 문법·객체지향 | Spring 트랜잭션 | 연결 금지 | `UNKNOWN` |
| FIT-003 | Kafka 비동기 메시징 | Linux 운영 | 연결 금지 | `UNKNOWN` |
| FIT-004 | 게임 열정·책임감 | Unity | 연결 금지 | `UNKNOWN` |
| FIT-005 | 사용자·제품 목표 중심 태도 | REST API | 연결 금지 | `UNKNOWN` |
| FIT-006 | JPA/Hibernate ORM·도메인 설계 | Spring Boot | 직접 충족 금지 | `UNKNOWN` |
| FIT-007 | FluxionDB 스트림 저장소 운영 | 같은 범위의 신규 기술 | 직접 연결 | `VERIFIED_MET` |
| FIT-008 | C#·Unity 게임 클라이언트 | 게임 서버 네트워킹 | 직접 충족 금지 | `UNKNOWN` |

전체 실행 시간은 약 66초였다. 케이스별 모델 호출은 독립적이며 개발용 평가 시간이다.

## 확인된 성질

- 새로운 기술명이 사전에 없어도 정확한 scope가 같으면 연결할 수 있다.
- 기술명이나 분야가 가깝다는 이유만으로 검증 상태를 승격하지 않는다.
- Java 노드의 범위를 Spring 트랜잭션까지 넓히지 않는다.
- Unity 같은 기술 근거로 열정·책임감 같은 행동 요건을 충족 처리하지 않는다.
- 모델 출력은 후보일 뿐이며, 존재하지 않는 competency/fact ID는 컴파일러가 거부한다.

## 남은 한계

- 이 평가는 의미 연결 정확성에 집중했으며 실제 사용자 커리어 조각의 장문 품질은 Phase 8
  shadow 평가에서 다시 측정해야 한다.
- `fit-policy-0.1`의 준비도 임계값은 제품 확정값이 아니다. Spring 통합 전 실제 데이터로
  재조정하고 정책 버전을 별도로 올려야 한다.
