# 자비스(잡퀘스트) AI 서버

취업 준비 멀티에이전트 AI 서버. **LangGraph 오케스트레이터 + 역할별 워커 노드** 구조.

> 설계 정본: [`docs/agent-derivation-and-tools.md`](docs/agent-derivation-and-tools.md) —
> 각 노드가 무엇으로 답을 도출하는지(룰/DB/임베딩/LLM), 왜 그렇게 정했는지의 근거까지 담는다.
> 최초 계획 문서는 [`에이전트 설계/agent_tool_langchain_langgraph_plan.md`](에이전트%20설계/agent_tool_langchain_langgraph_plan.md)로
> 참고용으로만 남아있고, 실제 구현 기준은 위 정본을 따른다.

## 현재 상태: 10개 노드 전부 구현 완료 (mock 아님)

더 이상 스켈레톤이 아니다. **읽기(Read) / 판단(Decide) / 말하기(Speak) 3계층 아키텍처**로
전환 완료됐고, 판단(충족·심각도·점수·추천) 로직은 거의 전부 결정론(룰/DB/계산)이다 —
유일한 예외는 `analyze_gap`의 서술형 요구사항·도메인 키워드 매칭으로, 실측 결과 임베딩이
신뢰할 수 없어 **LLM 구조화 출력**(`semantic_judge.py`)을 쓴다. 예외의 근거와 범위는
`docs/agent-derivation-and-tools.md` §5.14, 원본 실측 데이터는
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
tests/                        # 133건, LLM/임베딩 실호출 없이 1초대(conftest.py가 강제)
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

- [`docs/agent-derivation-and-tools.md`](docs/agent-derivation-and-tools.md) — 설계 정본. 노드별
  도출 방법·툴·RAG 배치와 "구현하며 내린 결정"(§5) 전부 여기 있다. **되돌리기 전에 §5 먼저 읽을 것.**
- [`docs/troubleshooting.md`](docs/troubleshooting.md) — 실측으로 드러난 문제와 그 해결 기록.
- `작업로그/` — 날짜별 작업 로그(무엇을 왜 했는지, 다음에 할 일).
- [`docs/rag-team-interface-spec.md`](docs/rag-team-interface-spec.md),
  [`docs/rag-adapter-contract.md`](docs/rag-adapter-contract.md) — RAG 팀 연동 계약(hook② `search`
  아직 미연결, RAG 팀 작업 대기 중).

## 남은 작업

상세 목록은 `docs/agent-derivation-and-tools.md` **§4.3**. 요약:

1. `skill_taxonomy`/`semantic_judge`의 실 GMS 데이터 기준 정확도 검증(지금은 임시 스모크 테스트만)
2. RAG hook② `search`(`find_alternatives`) 연결 — RAG 팀 작업
3. 기업 맥락(`fetch_company_context`) 크롤링 + 정형 DB 구현 — 크롤링/데이터 담당 작업
4. 시드 데이터 확장(`skill_taxonomy`/`cert_db`/`project_template_db`/`career_graph`)
5. `experience_estimator`/`semantic_judge` 자동 테스트 추가
