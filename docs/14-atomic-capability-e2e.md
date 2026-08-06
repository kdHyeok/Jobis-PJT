# 원자 역량 상태·검증 로컬 E2E

## 목적

Capability Graph의 원자 역량이 Spring, PostgreSQL RLS, AI-v3 계약, Vue API 경계까지
연결되는지 확인한다. Docker가 없는 개발 환경에서 Testcontainers 테스트가 건너뛰어지는
상황을 보완하기 위한 격리 검증이다.

## 실행 환경

- 날짜: `2026-08-04`
- PostgreSQL: `localhost:58432`, Flyway `v42`
- Spring: `localhost:8381`
- 결정적 검증 AI: `localhost:8511`
- 검증 AI 파일: `AI-v3/scripts/mock_atomic_assessment_server.py`
- 기존 `8380` 프로세스와 원본 작업공간은 변경하지 않았다.

결정적 검증 AI는 로컬 E2E 전용이다. 실제 provider를 대체하거나 운영 경로에 포함하지
않으며, 질문·채점 HTTP 계약과 Spring 상태 전이를 재현하는 데만 사용한다.

## 확인 결과

| 시나리오 | 결과 |
| --- | --- |
| `SELF_CONFIRM` 기초 원자 직접 확인 | `VERIFIED` |
| `ASSESSMENT` 원자의 자기 확인 시도 | `409 Conflict` |
| `SELF_CONFIRM` 원자의 문제 검증 시작 | `409 Conflict` |
| 승인된 방법 2개를 가진 원자의 문항 수 | 2문항 |
| 두 문항 각 80점 | `PASSED`, 평균 80, 원자 `VERIFIED` |
| 두 문항 각 50점 | `NEEDS_STUDY` |
| 실패 세션 이의신청 | `REVIEW_REQUESTED` |
| 운영자 승인 | 세션 `PASSED`, 원자 `VERIFIED`, `OPERATOR_REVIEW` 이벤트 |
| 재로그인 후 최신 세션 조회 | 완료 상태 복원 |
| 다른 사용자의 원자 검증 시작 | `404`, 타 사용자 상태 비노출 |
| 타 사용자 최신 세션 조회 | `200`, 빈 본문 |
| legacy broad 역량 연결 승인 | 후보 `CONFIRMED`, 원자 `EVIDENCED` |
| legacy 연결의 자동 인증 여부 | `VERIFIED`로 승격되지 않음 |

검증 종료 후 E2E 계정과 종속 데이터를 삭제하고 `8381`, `8511`, `58432`를 종료했다.

## 전체 회귀

`scripts/check.ps1` 결과:

- Spring 전체 테스트 통과
- legacy AI `695 passed`
- regression fixture `40`건 통과
- Capability Graph `23 passed`
- AI-v3 전체 테스트 통과
- Vue `vue-tsc`와 Vite production build 통과

Testcontainers 기반 PostgreSQL 테스트 11개는 로컬 Docker 부재로 자동 건너뛰어졌다.
따라서 위 실제 PostgreSQL HTTP E2E를 별도로 수행했으며, 이를 skipped 테스트의 통과로
표현하지 않는다.
