# 프로토타입 관찰 UI (prototype) — 에이전트가 하는 일을 전부 눈으로 본다

> 개발 전용 도구. 이력서·공고 원문과 자연어 메시지를 직접 입력하면
> **플래너 선택 → 검증기 dispatch → 에이전트 실행 → 판정 엔진 노드 → LLM 입출력 원문
> → 요구사항별 매칭 판정 → 점수·등급 산출**까지 모든 단계가 타임라인으로 보이고,
> 실행마다 입력·출력·트레이스가 SQLite 에 저장된다.

## 실행

```bash
cd AI
PYTHONUTF8=1 uv run --with fastapi --with uvicorn \
    python -m uvicorn jobis_ai.prototype.app:app --reload
# Windows + 별도 venv 사용 시: UV_PROJECT_ENVIRONMENT=.venv-win 를 앞에 추가
```

브라우저에서 <http://127.0.0.1:8000> 접속.

- **모든 입력은 직접 넣는다** — 메시지(자연어 프롬프트)·이력서 원문·공고 원문 전부
  자유 입력 필드. 하드코딩된 시나리오 없음.
- "이전 세션 이어서 대화"를 체크하면 직전 실행의 세션을 재사용한다 —
  분석 결과 캐시 재사용("자소서 써줘"가 분석 없이 바로 도는 것)을 관찰할 수 있다.
- `.env` 에 LLM 키가 없으면 플래너가 판단할 수 없어 대화형 에이전트(career_chat)가 턴을 받고
  판정은 mock 폴백으로 돌며, 그 경우에도 "누가 호출됐고 왜 폴백됐는지"가 전부 이벤트로 남는다.

## 무엇이 보이나 (이벤트 종류)

| kind | 내용 | 계측 위치 |
|---|---|---|
| `planner` | 플래너 LLM 이 고른 에이전트·confidence·세션 자산 상태 | `orchestrator/chat.py` |
| `fallback` | 플래너 불가(LLM 미설정·실패) → 대화형 에이전트가 턴을 받음 | `orchestrator/chat.py` |
| `dispatch` | 검증기(validate_plan) 통과 후 최종 실행 시퀀스 | `orchestrator/chat.py` |
| `agent_start` / `agent_end` | 에이전트 이름·전제조건·산출물(data)·세션 저장 키·경고 | `orchestrator/chat.py` |
| `node` | 판정 엔진 그래프 노드 1개 완료 — 갱신한 상태 키·값·소요시간 | `service.py` (LangGraph stream) |
| `llm_call` | **모든 LLM 호출의 단일 통로** — 노드명·스키마·시스템 프롬프트·입력 원문·구조화 출력·재시도·소요시간. 공고 파싱/프로필 추출/의미판정/플래너/자소서/nl_render 전부 여기로 잡힘 | `structured.py` |
| `judgment` | 매칭 캐스케이드 판정 — 요구사항별 판정 방법(exact/llm_semantic/keyword/seniority_ladder)·상태(met/partially/not_met/uncertain)·매칭/결측 스킬·근거 ID·판정 사유 | `gap_matcher.py` |
| `score` | 카테고리별 점수·가중치·분모 제외(None) 카테고리·가중 평균·임계값(상0.7/중0.4)·등급 | `gap_matcher.py` |

UI 는 kind 별 전용 뷰(판정 테이블, 점수 산출표, LLM 입출력 접기 등)로 렌더링하고,
모든 이벤트에 "원본 JSON" 펼치기가 붙는다.

## 저장소

- 파일: 레포 루트 `prototype_runs.sqlite3` (gitignore 됨), 테이블 `runs` 하나.
- 한 행 = 대화 한 턴: id·시각·sessionId·메시지·이력서 원문·공고 원문·최종 응답 JSON·트레이스 JSON.
- 왼쪽 "지난 실행" 목록에서 클릭하면 과거 실행의 타임라인을 그대로 다시 본다.
- API: `POST /api/run` · `GET /api/runs` · `GET /api/runs/{id}`.

## 설계 원칙

- **트레이스는 하네스가 아니라 창문** — `jobis_ai/trace.py` 레코더가 비활성이면
  모든 `trace.emit()` 은 no-op 이라 운영 경로의 동작·성능에 영향이 없다
  (contextvar 기반, prototype 의 `/api/run` 만 레코더를 켠다).
- 계측은 판단하지 않고 기록만 한다 — 기존 테스트 228건이 계측 추가 후에도 전부 통과.

## 실측 예시 (2026-07-24, 실 LLM)

이력서·공고 텍스트 입력 + "이 공고 나 되나?" → 21개 이벤트 / 총 ~18초:
플래너 선택(1.7s) → fit_analysis 시작 → 공고 파싱 LLM(2.6s) → 프로필 추출 LLM(4.7s)
→ 의미판정 배치 LLM(1.2s) → 매칭 판정 8건(exact 4·llm_semantic 2·keyword 1·seniority 1)
→ 점수 0.6/등급 중 → 로드맵·대안·검증(각 0~2ms, 결정론) → nl_render LLM(6.4s) → 응답.
