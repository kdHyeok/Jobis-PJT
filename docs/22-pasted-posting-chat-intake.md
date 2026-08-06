# 자유 채팅 공고 원문 접수 구현 기록

## 해결한 문제

자유 채팅에 붙여넣은 채용 공고가 `last_message`로만 남고 `job_posting` 자산이 되지 않아,
플래너가 공고 분석을 선택해도 실행 검증기가 이를 제거하고 일반 대화로 대체했다.

## 확정 동작

1. 플래너가 현재 발화의 자료 유형을 구조화해서 읽는다.
2. `JOB_POSTING`이면 AI가 만든 요약이 아니라 사용자의 원문을 그대로 저장한다.
3. 새 공고가 등록되면 이전 `analysis`와 `posting_summary`를 무효화한다.
4. 제출된 공고의 리뷰 단계인 `posting_analysis`를 실행 계획에 보장한다.
5. 본문 없는 명시적 요청은 `pendingRequest`로 보존하고 공고 URL·본문을 요청한다.
6. 다음 턴에 공고가 오면 기억한 분석 요청을 이어서 실행한다.
7. 긴 일반 상담은 길이만으로 공고가 되지 않는다.
8. 저확신 일반 대화 폴백일 때만 좁은 공고 요청 판독을 실행한다.

## 검증 결과

- legacy AI 전체: `705 passed`
- 평가 데이터셋: 53케이스 계약 유효
- 실제 Codex 플래너:
  - 공고 본문 + 분석 요청 → `JOB_POSTING`, `posting_analysis`, confidence `0.99`
  - `공고 분석해줘`만 입력 → `QUESTION_ONLY`, `blockedRequests=[posting_analysis]`, confidence `0.98`
- 외부 라이브러리 경고: Starlette TestClient deprecation 1건(기능과 무관한 기존 경고)

## 재시작 범위

변경 대상은 legacy AI 서버이므로 8400번 AI 서버만 재시작하면 된다. 백엔드·프론트엔드·AI v3·
Capability Graph는 이 변경 때문에 재시작할 필요가 없다.
