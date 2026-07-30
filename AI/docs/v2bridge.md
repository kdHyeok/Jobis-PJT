# v2bridge — 서비스 v2 백엔드 연결 가이드

서비스 v2(`feat/be/jobiss-service-v2`, worktree `C:\Users\SSAFY\Desktop\S15P11C202-rag`)의
백엔드는 AI 서버를 `AI_SERVER_URL` 환경변수 하나로 고른다. 팀이 만들어 둔 `ai-server/` 는
계약 검증용 임시 어댑터이고, **v2bridge 가 같은 계약을 구현하므로 URL 만 바꾸면 진짜
에이전트로 교체된다** (팀 README §ai-server 안내가 약속한 교체 방식).

## 계약 (정본: 팀 저장소 `ai-server/app/models.py` · `_docs/service-v2/`)

| 엔드포인트 | 하는 일 | 엔진 매핑 |
|---|---|---|
| `GET /health` | 상태·provider 보고 | — |
| `POST /v1/chat` | 대화 한 턴 (이력·커리어 요약 동봉) | 오케스트레이터 `handle_chat` |
| `POST /v1/analyses` | 공고 분석 → `COMPLETED` 또는 `NEEDS_INPUT`(질문 1개) | 판정 그래프 + `application_plan` |
| `POST /v1/career-extractions` | 원문 → 커리어 조각 제안 | `build_user_profile` → 조각 변환 |
| `POST /v1/evidence-verifications` | 증빙 ↔ 노드 범위 대조 | `run_structured` (semantic_judge 계열 예외) |

- 인증: `X-JOBISS-AI-SECRET` 헤더 (env `JOBISS_AI_SHARED_SECRET`, 기본 `local-ai-secret`).
- 무상태 계약: 매 요청에 전체 문맥이 온다. 분석은 `analysis_job_id` 단위로 세션을 새로 세운다.
- 오류 코드(백엔드 워커의 재시도 기준): `AI_PROVIDER_NOT_CONFIGURED`(503) ·
  `AI_PROVIDER_UNAVAILABLE`(503, 재시도 가능) · `INVALID_AI_RESPONSE`(502).
- 판정 보류(UNDETERMINED)는 verdict 로 내보내지 않고 503 으로 실패시킨다 (D63).

## 실행 — push 자동 반영 포함 (권장)

```bash
# WSL 에서 (백그라운드 권장). 기본 포트 8000.
AI/scripts/run_v2bridge.sh [포트]
```

- uvicorn `--reload` + 원격 워처: 현재 브랜치에 push 가 오면 60초 안에 fast-forward 로
  코드가 갱신되고 서버가 자동 재기동된다 (**push = 배포**, 병렬 개발용).
- 워처는 ff 불가(작업 트리 충돌·분기)면 갱신을 보류하고 로그만 남긴다 — 작업 중 코드를
  덮어쓰지 않는다.
- 확인: `powershell.exe -NoProfile -Command "(Invoke-WebRequest -UseBasicParsing http://localhost:8000/health).Content"`
  → `{"status":"ok","service":"jobis-ai-v2bridge",...}`

자동 갱신 없이 띄우려면:

```bash
cmd.exe /c "cd /d C:\Users\SSAFY\Desktop\S15P11C202-ai\AI&& set PYTHONUTF8=1&& C:\Users\SSAFY\.local\bin\uv.exe run --with fastapi,uvicorn uvicorn jobis_ai.v2bridge.app:app --host 127.0.0.1 --port 8000"
```

## v2 백엔드에 연결

v2 백엔드(`S15P11C202-rag/backend`)를 띄울 때 환경변수만 지정한다 — 팀 폴더의 코드·설정은
건드리지 않는다:

```powershell
$env:AI_SERVER_URL='http://localhost:8000'      # v2bridge 포트
$env:AI_SHARED_SECRET='local-ai-secret'          # JOBISS_AI_SHARED_SECRET 과 같은 값
```

포트 충돌 주의: 구 백엔드용 webbridge 도 기본 8000 이다. 두 스택을 동시에 띄우면
v2bridge 를 다른 포트(예: 8001)로 올리고 `AI_SERVER_URL` 만 맞춘다.

## 되묻기 처리 규약 (service.py)

| 엔진 질문 | 어댑터 응답 | 근거 |
|---|---|---|
| 동의 게이트(`confirm_*`) | "네, 진행해 주세요" | 백엔드의 분석 작업 실행이 곧 사용자의 실행 지시 |
| 자산 요청(`resume`·`job_posting`) | "요청에 담긴 자료가 전부" | v2 요청에 확정 자료가 전부 동봉됨 |
| 선택지 있는 질문 | `NEEDS_INPUT` 으로 승격 (질문 예산 3회) | 사용자가 답해야 결과가 갈린다 |
| 선택지 없는 질문 | "정보 없음"으로 진행 | 선택지를 지어내지 않는다 — uncertain 처리(§2-1)에 맡김 |

## 파일

- `src/jobis_ai/v2bridge/models.py` — 계약 스키마 사본 (정본이 바뀌면 다시 맞춘다)
- `src/jobis_ai/v2bridge/mapping.py` — 판정 산출물 → 계약 변환 (결정론, 판단 없음)
- `src/jobis_ai/v2bridge/service.py` — 엔진 호출 어댑터
- `src/jobis_ai/v2bridge/app.py` — FastAPI 앱
- `tests/test_v2bridge_contract.py` · `tests/test_v2bridge_mapping.py` — LLM 없이 도는 검증
- `scripts/run_v2bridge.sh` — push 자동 반영 실행기
