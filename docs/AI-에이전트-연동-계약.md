# 실제 AI 에이전트 연동 계약

이 실험판의 실행 정본은 루트 [README](../README.md)입니다. 이 문서는 코드 경계만
요약합니다.

## 런타임 경계

```text
Vue :5373
  -> Spring Boot :8280
       -> POST /v1/*, X-JOBISS-AI-SECRET
            -> AI/src/jobis_ai/v2bridge :8200
                 -> 실제 planner / agents / graph / session
                 -> (선택) RAG /search :8870
```

Spring은 AI 세션 내부 형식을 알지 않습니다. Java 계약은
`backend/src/main/java/com/jobiss/analysis/AiContracts.java`, Python 계약 정본은
`AI/src/jobis_ai/v2bridge/service_contract.py`입니다.

## 허용된 변환

- camelCase JSON과 Python 모델 사이의 필드명 변환
- 서비스의 선택 공고·커리어 자료를 실제 AI `ChatAttachment`로 변환
- 실제 trace를 채팅 진행 이벤트로 변환
- 실제 AI의 구 `ChangeProposal`을 서비스 `CompetencyProposal` enum으로 기계 변환
- 실제 AI의 `results`를 값 수정 없이 UI 산출물 컨테이너로 포장
- 실제 플래너가 붙여넣은 공고를 분석 대상으로 선택한 경우, 원문을 그대로 담은
  `ANALYZE_POSTING` 동의 제안으로 변환
- 실제 선택형 질문은 `CHOICE`, 선택지가 없는 근거 질문은 `TEXT`로 전달하고 사용자의
  답변 원문을 다음 요청의 커리어 근거에 추가

## 금지된 변환

- 실제 AI가 생성하지 않은 역량, 판정 근거, 프로젝트, 출처 생성
- 로드맵 순서나 분야를 어댑터에서 보정
- 실제 AI 결과가 마음에 들지 않는다는 이유로 프론트 표시 값을 교체
- 기능이 없을 때 가짜 성공 응답 반환
- AI 제안을 사용자 확인 없이 실행하거나 AI 서버에서 서비스 DB를 직접 변경

## 제안과 실행의 경계

AI는 의도 분류와 원문 추출 결과를 `proposedActions`로 제안할 뿐 저장 작업을 실행하지
않습니다. Vue는 확인 버튼을 제공하고, Spring은 AI 답변 작업에 저장된 제안을 `actionId`로
다시 찾은 뒤 계약을 검증합니다. 실제 공고 저장, 사용자별 RLS, 사용량 제한, 공고 중복
재사용, 분석 큐 생성은 모두 Spring의 책임입니다. 따라서 브라우저에서 payload를 바꿔도
임의 공고를 실행할 수 없고, 같은 버튼을 재전송해도 한 번만 처리됩니다.

그래서 실제 AI에 없는 회사 맞춤 프로젝트는 `targetProject: null`, 역량 평가 문제 API는
`AI_CAPABILITY_NOT_AVAILABLE`(501)로 드러납니다.

분석 질문은 한 번에 하나만 전달됩니다. `CHOICE`는 2~4개 선택지를 가지며 `TEXT`는
선택지 없이 최대 2,000자의 사용자 근거를 받습니다. 질문의 `relatedRequirementIds`와
`absenceScope`, 답변의 `answerStatus`를 보존하므로 “경험 없음”을 정보 미입력과 구분합니다.
어댑터는 자유서술 질문의 선택지를 지어내거나 사용자 대신 답하지 않습니다. 질문 상한 뒤에는
실제 파서·프로필·gap matcher의 중간 상태를 사용해 정상 완료하며, 사용자가 확인한 부재만
`not_met`, 그 밖의 미확인 조건은 `uncertain`으로 둡니다.

## 오류 계약

- `AI_PROVIDER_NOT_CONFIGURED`(503): 공급자/키/CLI 설정 없음
- `AI_TIMEOUT`(504): 실제 모델/CLI 호출 제한 시간 초과
- `AI_PROVIDER_UNAVAILABLE`(503): 실제 에이전트 실행이 결과에 이르지 못함
- `ANALYSIS_CONVERGENCE_FAILED`(503): 호출은 성공했지만 분석 상태가 반복되어 완료하지 못함
- `INVALID_AI_RESPONSE`(502): 실제 결과를 서비스 JSON 계약으로 표현할 수 없음
- `AI_CAPABILITY_NOT_AVAILABLE`(501): 실제 에이전트에 해당 기능 계약 자체가 없음

## 검증

```powershell
cd C:\jobiss-service-real-agent-lab\AI
.\.venv\Scripts\python.exe -m pytest -q

cd C:\jobiss-service-real-agent-lab\backend
.\gradlew.bat test

cd C:\jobiss-service-real-agent-lab\frontend
npm run build
```
