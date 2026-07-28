# 07. Agent 루프 (LangGraph, B 아키텍처) 🔗 통합

- **선행:** 01~06 (스키마·창구·파서·툴3)
- **참조:** **D11**(아키텍처 B) · D9(동적 라우팅) · AGENTS §5.2·§5.3·§8 · 정본 §4·§5 · design.md §4·§5
- **상태:** ✅ 완료 (2026-07-27)

## 목표
툴 3개를 엮어 **자연어 쿼리 → 툴 동적 호출 → 관찰 분기 → 자연어 응답**하는 Agent를 LangGraph로 만든다. **B 아키텍처**(tool-calling ReAct + analyze_gap 후 결정적 조건엣지). `run_agent()`가 `RunAgentResult` 반환.

## 아키텍처 (D11 = B)
```
START → agent
agent(LLM bind_tools) ─(tool_calls?)─┬─ 있음 → tools
                                     └─ 없음 → END (최종 메시지 = reply)
tools(툴 실행 + State 갱신) ─[조건엣지 route_after_tools]─┬─ 방금 analyze_gap & level∈{중,하} → auto_search
                                                         └─ 그 외 → agent
auto_search(LLM Thought로 대체직군 생성 → search_postings 강제) → agent
※ max_steps(10) 초과 → 강제 END
```

## State
```python
run_id: str                               # 대화 단위 식별(uuid) — 로그 grep 키
messages: Annotated[list, add_messages]   # LLM 대화 + 툴 결과(ToolMessage)
profile: UserProfile | None               # 입력(사전 파싱). 툴에 State로 주입
current_posting: Posting | None           # load_posting 결과 보관(analyze_gap용)
tools_called: list[str]                    # meta 추적
level: str | None                          # analyze_gap 결과(조건엣지·meta용)
step: int                                  # max_steps 가드
```

## 재사용 자산 (신규 작성 금지)
| 용도 | 재사용 대상 |
|---|---|
| 툴 3개 | `tools/{load_posting, search_postings, analyze_gap}` |
| LLM | `llm.get_llm("cheap")`(agent·응답), `get_structured_llm`(필요 시) |
| 반환 | `schemas/RunAgentResult`(meta{scenario, tools_called, level}) |
| 입력 | `schemas/UserProfile`·`Posting` |

## ⟨확인 필요⟩ 통합 결정
1. **profile·posting = State 주입** — 툴에 LLM이 profile을 인자로 안 넘김(큰 객체). LLM은 `url`·`직군명`만 제공, **profile/current_posting은 State에서 tools 노드가 주입**. `analyze_gap`은 State의 profile+current_posting 사용.
2. **scenario 추적** — B엔 명시 라우터 없음 → `meta.scenario`를 **tools_called 패턴으로 추론**(analyze_gap→3 / search+profile→1 / search+직군→4 / load만→2 / 무툴→5·6). best-effort.
3. **Guardrail 5·6** — 별도 노드 없이 **시스템 프롬프트로 유도**(취업 무관→거절, 일상→안내). LLM이 툴 없이 응답.
4. **응답·meta 조립** — agent의 최종 AI 메시지 = `reply`. `meta`는 State(tools_called·level·scenario)로 조립.

## 관측성 — 라이트 로깅 (기능 단위 + 대화 단위)
- **`run_id`**(uuid) 매 `run_agent` 호출마다 생성 → **대화 단위** 묶기 키 (싱글턴이라 1 run = 1 대화).
- **각 노드에서 구조화 로그 1줄** (Python `logging`): `[run_id][step N] node=… tool=… level=… → 다음`.
  - agent: LLM이 고른 tool_calls / tools: 실행 툴·결과 요약·source / route_after_tools: 분기 결정 / auto_search: 대체직군.
- **두 단위 다 지원**: **기능 단위** = 각 로그 라인(노드/툴/분기) · **대화 단위** = `run_id`로 grep.
- 리치 관측성(`sectionStatus`·warnings·트레이스 영속화)은 **백로그**(design §8.2).

## 작업 항목
### `agent/`
- [x] `agent/tools_bind.py` — 3툴을 LLM용 스키마로 래핑(`bind_tools`) + tools 노드가 실제 Pydantic 함수 호출·State 갱신·ToolMessage(문자열) 생성
- [x] `agent/graph.py` — StateGraph: `agent`·`tools`·`auto_search` 노드 + 조건엣지 `route_after_tools` + max_steps 가드
- [x] **라이트 로깅**(`agent/logging.py` 또는 각 노드): `run_id`(State) + 각 노드 구조화 로그 1줄 — 기능·대화 단위 추적
- [x] 시스템 프롬프트 — 6 시나리오 행동 지침(D9: 하드코딩 아님, LLM 유도) + guardrail
- [x] `agent/run.py` (또는 graph 내) — `run_agent(query, profile) -> RunAgentResult`
- [x] `run.py`(루트) — 스모크 진입점
- [x] `agent/__init__.py`

## 완료 기준 (DoD) — 성공 판정 5기준 (design.md §8 / AGENTS §8)
- [x] **기준1**: 이력서+공고 요청(시나리오3) → `meta.tools_called`에 `analyze_gap` 포함
- [x] **기준2 ★핵심**: level 중/하 → `analyze_gap → search_postings` 순서(조건엣지 auto_search 작동)
- [x] **기준3**: level 상 → search_postings **미포함**(auto_search 안 탐)
- [x] **기준4**: 없는 URL → `load_posting` NOT_FOUND → 크래시 없이 "공고 못 찾음" 안내
- [x] **기준5**: 모든 요청 `max_steps`(10) 이내 종료
- [x] `run_agent()` → `RunAgentResult{reply(자연어), meta{scenario, tools_called, level}}`
- [x] **로그 확인**: 한 요청 실행 시 `run_id`로 스텝별 로그(agent→tools→분기→…)가 남는다

## 주의
- **성공 판정 = 구조(meta)로**, 문자열 assert 금지(LLM 비결정성). 기준 1·4는 LLM이 툴 부르는지에 의존(동적).
- **max_steps 가드 필수** — 무한 툴 루프 방지.
- 툴 결과 직렬화: LLM에겐 문자열 요약, 구조화 결과는 State에(조건엣지·meta).
- **범위: agent 조립만.** FastAPI 노출은 task 09.

---
↓ 구현 후 채움 ↓
## 검증 메모 (2026-07-27)
- ✅ **성공판정 5기준**:
  - 1) analyze_gap 호출(시나리오3): 런타임 확인
  - 2★) 중/하 → search(auto_search): 런타임 확인 (불변식 `search 발동 ⟺ level 중/하` 성립)
  - 3) 상 → search 없음: **조건엣지 단위 확인**(상→agent, 중/하→auto_search). ※ 런타임 상 케이스는 비결정성으로 미발생(프론트 공고도 중 나옴)
  - 4) 없는 URL → `load_posting` NOT_FOUND → "공고를 찾을 수 없습니다"(크래시 없음)
  - 5) max_steps: 2~3스텝 종료, recursion 크래시 없음
- ✅ **로깅**: run_id + 노드별 1줄(agent/tools/route/auto_search) — 기능·대화 단위 추적
- 📦 산출: `agent/{graph,__init__}.py`, `run.py`, `schemas/agent_io.py`(Meta: scenario→run_id)
- 💳 케이스당 LLM 여러 회(agent·gap·auto_search).

## 구현 메모 — 채택 방식 결정
- **B(D11) 구현**: `agent`(bind_tools) ⇄ `tools`(State 주입·직렬화·tools_called/level 추적) + `route_after_tools` 조건엣지 + `auto_search`(대체직군 LLM Thought → search 강제).
- **관찰**: LLM이 `load_posting`+`analyze_gap`을 **한 턴에 병렬** 호출하기도 함. tools 노드가 순서대로 처리(load 먼저 → current_posting 세팅 후 gap)라 동작. ⚠️ 만약 gap이 리스트 앞이면 posting=None 위험 → 향후 tool_calls 정렬(load 우선) 고려(백로그).
- **상 비결정성**: 같은 프론트 공고가 task 06(0.727 상) vs 지금(중) — analyze_gap LLM 폴백 변동. 기준3은 결정적 조건엣지로 보장, 런타임 상은 미시연.
- scenario 제거(D11 후속) — meta는 {tools_called, level, run_id}.
- **직접 테스트 후속 수정 (2026-07-27)**: chat.py로 직접 돌려 발견한 디버깅성 개선 —
  ① 실패 원인 명확화(공고 없음 vs 이미지 공고 본문 없음 vs 이력서 없음 구분, `analyze_gap` ToolError `detail`을 reply까지 전달) → reply가 "이력서 탓" 오도 안 함.
  ② 검색 로그·요약에 `score`·`match_reason` 포함 → 왜 추천됐나 가시화.
  ③ S2 공고정리: `load_posting` 요약에 본문 발췌(500자)+핵심필드 → LLM이 실제 내용 요약(제목만 X). `d17f50f`
  ④ 공고 제시 시 **URL 포함**(추천·검색·대체직군) + 프롬프트 지침. `1e2883f`
  ※ 대화 맥락 기억(멀티턴)은 별개 결정으로 보류(설계 §9 싱글턴, D12).
