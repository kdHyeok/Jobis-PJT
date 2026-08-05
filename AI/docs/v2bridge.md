# v2bridge 계약

계약 정본은 Spring의 `backend/src/main/java/com/jobiss/analysis/AiContracts.java`와
`AiAnalysisClient.java`다. Python 대칭 모델은 `src/jobis_ai/v2bridge/models.py`이며
`extra=forbid`, camelCase 직렬화를 유지한다.

백엔드는 `AI_SERVER_URL`로 v2bridge를 찾고 `X-JOBISS-AI-SECRET`로 인증한다.

| 엔드포인트 | 엔진 매핑 |
|---|---|
| `GET /health` | provider와 `jobis-ai-v2bridge` 식별 |
| `POST /v1/chat[/stream]` | `orchestrator.chat.handle_chat` |
| `POST /v1/analyses[/stream]` | 판정 그래프와 application plan |
| `POST /v1/career-extractions` | 프로필/경력 조각 추출 |
| `POST /v1/evidence-verifications` | 증빙과 노드 범위 검증 |
| `POST /v1/competency-assessments` | 역량 문제 생성·채점 |

오류 코드는 `AI_PROVIDER_NOT_CONFIGURED`(503), `AI_PROVIDER_UNAVAILABLE`(503),
`INVALID_AI_RESPONSE`(502)를 유지한다. 스트림 미지원 시 백엔드가 단건 계약으로 폴백한다.

로컬 실행과 검증은 `AI/README.md`, 컨테이너 운영은 `ops/DEPLOYMENT.md`를 따른다.
