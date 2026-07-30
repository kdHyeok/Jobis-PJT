# 자비스(잡퀘스트) AI 서버

취업 준비 멀티에이전트 AI 서버. **LangGraph 오케스트레이터 + 역할별 워커 노드** 구조.

> 설계 정본: [`docs/agent-structure-current.md`](docs/agent-structure-current.md) —
> 현재 구조(오케스트레이터·전담 에이전트 6종·판정 엔진)와 각 노드가 무엇으로 답을 도출하는지를 담는다.
> 처음 기획부터의 발전 과정·결정 이력은 [`docs/agent-structure-evolution.md`](docs/agent-structure-evolution.md) 참조.
> 최초 계획 문서는 [`에이전트 설계/agent_tool_langchain_langgraph_plan.md`](에이전트%20설계/agent_tool_langchain_langgraph_plan.md)로
> 참고용으로만 남아있고, 실제 구현 기준은 위 정본을 따른다.

## 현재 상태: 10개 노드 전부 구현 완료 (mock 아님)

더 이상 스켈레톤이 아니다. **읽기(Read) / 판단(Decide) / 말하기(Speak) 3계층 아키텍처**로
전환 완료됐고, 판단(충족·심각도·점수·추천) 로직은 거의 전부 결정론(룰/DB/계산)이다 —
유일한 예외는 `analyze_gap`의 서술형 요구사항·도메인 키워드 매칭으로, 실측 결과 임베딩이
신뢰할 수 없어 **LLM 구조화 출력**(`semantic_judge.py`)을 쓴다. 예외의 근거와 범위는
`docs/agent-structure-current.md` §3.5, 원본 실측 데이터는
[`docs/troubleshooting.md`](docs/troubleshooting.md)에 있다.

LLM(챗)·임베딩 호출은 **SSAFY GMS(API 게이트웨이) 경유**로 연결돼 있다(`LLM_PROVIDER=openai`,
`EMBED_PROVIDER=openai`). `.env`에 `GMS_KEY`만 채우면 동작한다 — 아래 [실행](#실행) 참고.

## 구조

```
src/jobis_ai/
├── contracts/               # 계약 스키마 (Pydantic)
│   ├── api.py                #   백엔드 ↔ AI 요청/응답
│   └── domain.py             #   에이전트별 출력 스키마
├── graph/                   # LangGraph 오케스트레이터
│   ├── state.py               #   GraphState + 진행 상태 코드
│   ├── nodes.py                #   10개 노드 함수 (실 구현)
│   └── builder.py              #   노드·엣지 조립 (StateGraph)
├── embed_impl/               # 임베딩 provider 구현체 (GMS 경유 OpenAI 등)
│
│  # --- 읽기 계층 ---
├── extract.py, rule_extractor.py, structured.py
│  # --- 판단 계층 (핵심 툴) ---
├── gap_matcher.py             # 요구사항×프로필 매칭 엔진 (핵심)
├── skill_taxonomy.py, role_taxonomy.py, career_graph.py
├── experience_estimator.py    # 사용자 경력 개월수 추정 (연차 비교용)
├── semantic_judge.py          # LLM 구조화 출력 의미 판정 (§0 원칙의 의도적 예외)
├── sufficiency_rules.py, profile_completeness.py, verify_rules.py
├── cert_db.py, skill_to_cert.py, project_template_db.py, roadmap_scheduler.py
│  # --- 말하기 계층 ---
├── nl_render.py
│  # --- 어댑터/설정 ---
├── llm.py, embed.py, rag.py, config.py
├── service.py                # 요청→그래프→응답 진입점
└── run_demo.py                # 데모 실행기
tests/                        # 253건, LLM/임베딩 실호출 없이 1초대(conftest.py가 강제)
```

## 실행

```bash
# 1) 가상환경 + 설치
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash / source .venv/bin/activate (WSL·Linux)
pip install -e ".[dev]"

# 2) 환경변수 설정
cp .env.example .env
# .env 를 열어 GMS_KEY 를 채운다 (LLM·임베딩 공용 인증키). 나머지 기본값은 그대로 써도 된다.

# 3) 데모 실행 (요청 → 응답 JSON 출력)
python -m jobis_ai.run_demo

# 4) 테스트 (LLM/임베딩 실호출 없음, ~1초)
pytest
```

### 웹 서비스와 함께 띄우기 — 웹 브릿지 서버 (:8000)

웹 백엔드(Spring Boot)가 붙는 서버다. `fake-ai`(node) 자리에 그대로 들어가므로
**웹 쪽 코드·설정·DB를 건드리지 않고** 이 서버만 켜면 진짜 에이전트로 바뀐다.

```bash
# uv 사용 (권장 — 의존성 자동 설치, venv 불필요)
uv run --extra prototype uvicorn jobis_ai.webbridge.app:app --host 127.0.0.1 --port 8000

# venv 를 이미 만들어 뒀다면
pip install -e ".[prototype]"
uvicorn jobis_ai.webbridge.app:app --host 127.0.0.1 --port 8000
```

- 준비 완료 신호: `Uvicorn running on http://127.0.0.1:8000`
- 확인: `curl http://localhost:8000/health` → `{"status":"ok","engine":"jobis-ai"}`
- Windows 에서 한글이 깨지면 `PYTHONUTF8=1` 을 함께 준다
- 8000 이 이미 쓰이면 다른 포트로 띄우고, 백엔드에 `AGENT_WS_URL`·`AGENT_HTTP_URL` 만 준다
  (`application.yml` 이 이미 그 변수를 읽는다 — 파일 수정 불필요)

제공 계약 두 갈래 — 상세는 [`docs/webbridge.md`](docs/webbridge.md):

| | 경로 | 쓰임 |
|---|---|---|
| WebSocket | `/` | 공고 분석 대화 (START/USER_MESSAGE ↔ PROGRESS/QUESTION/DONE) |
| HTTP | `/chat`, `/chat/stream` | 대화 페이지 한 턴 (`/chat/stream` 은 진행·토큰 SSE) |
| HTTP | `/extract`, `/extract-file` | 저장소 자료 파편화 |
| HTTP | `/roadmap`, `/reassess`, `/roadmap-ask`, `/submission-review` | 로드맵·산출물 |

전체 스택(MySQL → AI → 백엔드) 기동 순서는 루트 [README](../README.md#실행-방법) 참고.

### LLM 프로바이더 선택 (`.env` 의 `LLM_PROVIDER`)

둘 중 아무거나 골라 쓴다 — 기능 차이는 없고 속도·비용만 다르다.

| | `claude_code` | `openai` (GMS) |
|---|---|---|
| 필요한 것 | 그 머신에 `claude` CLI 로그인(팀 플랜) | `GMS_KEY` |
| 비용 | 무과금 (구독 시트) | GMS 토큰 과금 |
| 속도 | 느림 — 호출마다 CLI 기동(수 초) | 빠름 (턴당 4~10초) |
| 토큰 스트리밍 | X (완성본 한 덩어리) | **O** |

```bash
# (A) Claude Code CLI — GMS_KEY 불필요
LLM_PROVIDER=claude_code
EMBED_PROVIDER=null              # GMS_KEY 가 없으면 임베딩은 어차피 건너뛴다
# CLAUDE_CLI=claude              # 기본값. Windows 에서 띄우고 claude 가 WSL 에 있으면 "wsl claude"
# CLAUDE_CODE_MODEL=sonnet       # 기본값 (고급 티어: 추출·생성)
# CLAUDE_CODE_MODEL_LIGHT=haiku  # 기본값 (경량 티어: 분류·이진판정)

# (B) GMS — 토큰 스트리밍까지 확인할 때
LLM_PROVIDER=openai
GMS_KEY=본인_GMS_키
```

바꾼 뒤에는 브릿지를 **재시작**해야 적용된다.
`GMS_KEY` 가 없어도 임베딩 계층은 예외를 던지지 않고 경고만 남기고 건너뛴다
(`embed_impl/gms_openai.py` — "예외를 던지지 않는다" 규칙). 즉 키 없이 `claude_code` 만으로 정상 동작한다.

### 공고 데이터 (실공고 추천·URL 조회)

`postings_db` 가 읽는 크롤링 공고 JSON 위치는 기본 `sample_data/db내 공고파일/` 이고,
환경변수 `POSTINGS_DB_DIR` 로 바꿀 수 있다. 데이터팀 파일이 오면 그 디렉토리에 JSON 을
넣고 재시작만 하면 된다(파일 형식은 `src/jobis_ai/postings_db.py` 상단 주석 참고).
이 데이터가 없으면 공고 추천이 빈 결과가 되고, 공고 URL 첨부는 웹 수집으로 폴백한다.

## 그래프 흐름

```
START
→ parse_job_posting → build_user_profile → check_profile_completeness → check_sufficiency
    ├─ insufficient → ask_user → assemble_output
    └─ sufficient   → analyze_gap → plan_roadmap
→ (optional) find_alternatives → verify_result
    ├─ retry → analyze_gap | plan_roadmap
    └─ pass  → assemble_output → END
```

## 참고 문서

- [`docs/agent-structure-current.md`](docs/agent-structure-current.md) — 설계 정본(현재 구조 스냅샷).
  노드별 도출 방법·툴·RAG 배치·신뢰성 장치 전부 여기 있다.
- [`docs/agent-structure-evolution.md`](docs/agent-structure-evolution.md) — 처음 기획부터의 발전
  과정과 구현하며 내린 결정 이력. **설계를 되돌리기 전에 먼저 읽을 것.**
- [`docs/troubleshooting.md`](docs/troubleshooting.md) — 실측으로 드러난 문제와 그 해결 기록.
- `작업로그/` — 날짜별 작업 로그(무엇을 왜 했는지, 다음에 할 일).
- [`docs/rag-team-interface-spec.md`](docs/rag-team-interface-spec.md),
  [`docs/rag-adapter-contract.md`](docs/rag-adapter-contract.md) — RAG 팀 연동 계약(hook② `search`
  아직 미연결, RAG 팀 작업 대기 중).

## 남은 작업

상세 목록은 `docs/agent-structure-current.md` **§8**. 요약:

1. `skill_taxonomy`/`semantic_judge`의 실 GMS 데이터 기준 정확도 검증(지금은 임시 스모크 테스트만)
2. RAG hook② `search`(`find_alternatives`) 연결 — RAG 팀 작업
3. 기업 맥락(`fetch_company_context`) 크롤링 + 정형 DB 구현 — 크롤링/데이터 담당 작업
4. 시드 데이터 확장(`skill_taxonomy`/`cert_db`/`project_template_db`/`career_graph`)
5. `experience_estimator`/`semantic_judge` 자동 테스트 추가
