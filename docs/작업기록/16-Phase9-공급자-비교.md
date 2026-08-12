# Phase 9 실제 공급자 비교 결과

## 결론

2026-08-04에 공개 합성 백엔드 공고 한 건을 LEGACY와 V3로 각각 실행했다. 두 분석은 모두 최종 완료됐고 passive paired 비교가 자동 생성됐다. 그러나 의미 결과 차이와 V3 처리 시간, 재개 과정에서 발견된 안정성 결함을 고려하면 **기본 공급자를 V3로 전환할 근거는 아직 부족하다.**

이번 결과는 한 건의 개발 검증이며 정확도나 p50/p95를 대표하지 않는다. 자동 일치율은 품질 점수가 아니고, 운영자의 원문·사용자 맥락 확인이 필요하다.

## 사용한 공개 합성 공고

- 회사: `Example Games`
- 직무: 신입 웹 백엔드 엔지니어
- 핵심 업무: Java 17·Spring Boot REST API, MySQL, Git 코드 리뷰, 단위 테스트
- 필수: 신입 지원 가능, Java 기초, 객체지향, HTTP, 데이터베이스 기초
- 우대: Spring Data JPA, JUnit, Docker 배포
- 사용자 답변: 프로젝트·업무 경험 없음

실제 사용자 이력서나 비공개 공고 원문은 비교 테이블에 복사하지 않았다.

## 최종 실측

| 항목 | LEGACY | V3 | 비고 |
|---|---:|---:|---|
| 마지막 활성 처리 시간 | 79,618ms | 184,530ms | LEGACY는 이벤트 구간, V3는 progress elapsed 기준 |
| 회사 | Example Games | Example Games | 일치 |
| 직무 | GAME_DEVELOPMENT | BACKEND | 불일치, 합성 원문상 BACKEND가 타당 |
| 최소 경력 | 0개월 | 0개월 | 일치 |
| 판정 | ALTERNATIVE_PATH | UNKNOWN | 불일치 |
| 필수 요건 수 | 3 | 5 | 불일치, 사람 검토 필요 |
| 역량 집합 Jaccard | 0.1667 | 0.1667 | 낮은 중첩 |
| 회사 맞춤 프로젝트 | 있음 | 있음 | 일치 |

자동 비교 결과는 `humanReviewRequired=true`, `criticalMismatchCount=2`였다. 비교기의 판정 명칭은 `ALTERNATIVE_FIRST`와 `ALTERNATIVE_PATH`를 같은 의미로 정규화한다.

## 실제 실행에서 발견하고 수정한 결함

1. 추가 질문 답변 후 공고를 다시 구조화해 요구사항 ID가 바뀌었다.
   - 대기 시 저장한 `structuredPostingCheckpoint`를 재개 요청에서 재사용한다.
   - 다른 verified snapshot의 체크포인트는 계약 검증에서 거부한다.
2. 역량 자기보고 답이 직무 선택용 `clarificationAnswers`에 섞였다.
   - `absence_scope=NONE` 답만 직무·경력 트랙 선택에 전달한다.
   - `absence_scope=REQUIREMENTS` 답은 `requirementSelfReports`로 변환한다.
3. `New graduates may apply`가 검증해야 할 역량으로 생성됐다.
   - 같은 근거로 중복된 EXPERIENCE 원자 요구사항은 전용 `ExperienceRequirement`에만 남긴다.
4. 프로젝트 설계기가 `Responsibility`를 `AtomicRequirement`처럼 읽었다.
   - 업무 ID·본문·필수도를 가진 내부 planning 입력으로 명시 변환한다.
5. 업무만 참조한 유효한 프로젝트 작업을 컴파일러가 거부했다.
   - 승인된 역량 키와 실제 업무 ID를 참조한 작업은 허용한다.
   - 모든 학습 요구사항이 작업 또는 unresolved에 포함돼야 한다는 전체 누락 검사는 유지한다.
6. 내부 코드 예외가 `AI_PROVIDER_UNAVAILABLE`로 위장됐다.
   - 예상하지 못한 예외는 `INTERNAL_ERROR`로 분류하고 서버 traceback을 남긴다.
7. 질문 대기와 재시도를 포함한 전체 생애 시간이 모델 처리 시간으로 표시됐다.
   - `PROGRESS_ELAPSED`, `EVENT_SPAN`, `JOB_WALL_CLOCK` 순으로 측정하고 기준을 metrics에 함께 저장한다.

## 전환 차단 사유

- 실제 비교 표본이 한 건뿐이다.
- V3가 마지막 성공 실행에서도 LEGACY보다 약 2.3배 오래 걸렸다. 측정 기준이 달라 절대 비교로 단정할 수는 없다.
- 직무·판정·필수 요건 수·역량 집합에서 큰 차이가 있다.
- 재개 안정성 결함은 수정됐지만 반복 표본으로 재발률을 관찰하지 못했다.
- active duplicate dispatch는 구현하지 않았고 개인정보·비용 승인도 없다.

따라서 `AI_PROVIDER` 기본값은 변경하지 않는다. 다음 전환 검토는 공개 회귀 공고 여러 건의 사람 판정, 오류율, p50/p95, 비용을 함께 확보한 뒤 진행한다.

## 검증 근거

- V3 최종 실행 상태: `COMPLETED`
- V3 최종 진행 이벤트: 16개, `RESULT_ASSEMBLY COMPLETED`
- passive comparison 자동 생성 및 멱등성 확인
- 일반 사용자 운영 API 403, 운영자 검토 API 확인
- Spring·legacy AI·AI v3·Capability Graph·Vue 전체 회귀는 `scripts/check.ps1`로 검증
