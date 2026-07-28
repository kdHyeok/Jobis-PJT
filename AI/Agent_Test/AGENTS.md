# 커리어 코치 Agent — 이력서·공고 갭분석 Agent (Prototype 1.0.0)

> 기술 스택: Python 3.11 (`.venv`) / **LangGraph**(+ LangChain primitives) / **Pydantic v2** / python-docx / **GMS**(OpenAI 계열) — 의존성 단일 출처: `requirements.txt`
> 근거 설계: `agent 설계 명세서/agent_prototype_1.0.0.md` (정본) · 개발 규약: `agent_ver_VIBE-CODING-PLAYBOOK.md`
> 최종 갱신일: 2026-07-27 (task 01~06 완료, D11 반영)
>
> ⚠️ **이 파일이 코딩 시 유일 참조.** 설계 문서는 배경 근거(decisions.md D6). `⟨확정 필요 — task NN⟩`은 지어내지 말고 해당 태스크에서 정한다.

---

## 0. 확정 전제·제약 (그린필드)

| 항목 | 확정 사항 |
|---|---|
| 언어/런타임 | **Python 3.11** (venv `.venv`). 의존성 = `requirements.txt`(단일 출처, 버전 핀) |
| 실행 형태 | **서버 없는 파이썬 core.** `python run.py`로 직접 실행·검증 |
| 오케스트레이션 | **LangGraph** `StateGraph`. 노드=모듈, 분기=conditional edge |
| LLM 호출 | LangChain `ChatModel` + `with_structured_output` (노드 내부에서) |
| 프로바이더 | **OpenAI 계열, GMS 프록시 경유** (base_url swap) |
| 인증 | `Authorization: Bearer $GMS_KEY` — **환경변수 주입, 하드코딩 금지** |
| GMS base_url | `https://gms.ssafy.io/gmsapi/api.openai.com/v1` |
| 구조화 추출 | Pydantic 스키마 강제 (`with_structured_output`). free-form "JSON 뽑아줘" 금지 |
| 이력서 파싱 | python-docx (표 없는 텍스트 이력서 가정), agent 밖 전처리 |
| 대화 방식 | **싱글턴** (이력서+공고를 한 번에). 멀티턴 누적 범위 밖 |
| RAG(`search_postings`) | **Mock.** 계약대로 동작 가정, 함수 몸통만 나중 교체 |
| FastAPI 서버화 | **후순위(task 09).** core 완성 후 얇게. Java 백엔드 연결용 |
| 모델 배치 | **정적 티어 매핑**(§5.5). 런타임 동적선택 아님 |
| 절대 안 할 것 | 4번째 툴 신설 / 멀티턴 상태관리 / core 없이 서버부터 / 런타임 모델 자동선택 / 모듈이 모델 직접 지정 / **이력서 빈약 케이스 처리**(profile은 유효 가정) |

---

## 1. 결정 사항 (불변)

| 항목 | 결정 | 상태 |
|---|---|:---:|
| 툴 개수 | 3개 고정 (`analyze_gap`·`search_postings`·`load_posting`) | **불변** |
| Agent 패턴 | ReAct 성격을 LangGraph 그래프로 구현 (관찰→분기) | **불변** |
| max_steps | 10 | **불변** |
| 대화 | **싱글턴** (1.0.0 확정. 멀티턴은 추후 업그레이드 버전에서 적용 가능) | **불변** |
| profile 스키마 | `_UserProfileRead` 10필드 | **불변** |
| 관찰 분기 | level 상→검색X / 중·하→search_postings (§5.3) | **불변** |
| 관측성·툴 재시도 | 백로그 (설계서 §8) | **손대지 말 것** |

---

## 2. 데이터 모델 (JSON 스키마)

> 원칙: 아래 필드명·타입·구조를 **그대로 유지**한다. 임의 추가·개명 금지. 없는 섹션 → `[]`, 값 없는 스칼라 → `null`.

### 2.1 profile JSON — `_UserProfileRead` (10필드, **중심 계약**)
`search_postings`·`analyze_gap`이 공유. **로드베어링(실사용)**: `skills`, `projects.techStack`, `experiences`.

| 필드 | 구조 |
|---|---|
| `skills` | `[{ name, level }]` |
| `experiences` | `[{ id, company, role, employmentType, period, summary }]` |
| `projects` | `[{ id, title, projectType, period, teamSize, role, summary, techStack[], achievements[] }]` |
| `education` | `[{ id, school, major, degree, status, period }]` |
| `certifications` | `[{ id, name, status, acquiredDate }]` |
| `languages` | `[{ id, name, testName, score, testDate, proficiency }]` |
| `bootcamp` | `[{ id, name, organization, track, period, summary }]` |
| `awards` | `[{ id, title, organization, date, description }]` |
| `evidenceMap` | `[{ evidenceId, source, text }]` (메타) |
| `uncertainties` | `[string]` (메타) |

### 2.2 공고 JSON — load_posting/DB 원본 (약 15필드) *(design.md §7.2 이식)*
`source · posting_id · company · title · url · employment_type · experience · education · location · posted_date · deadline · detail_text · image_urls[] · need_ocr · collected_at`
- **`need_ocr:"X"`(본문 채워진 것)만 사용.** `detail_text`에 필수/우대 요건이 자유 텍스트로 존재(→ `analyze_gap`이 추출).
- 데이터 위치: `sample_data/db내 공고파일/*.json` (jobkorea·wanted 합본).

### 2.3 search_postings 출력
```jsonc
{ "postings": [ { /* 원본 공고 JSON */ , "score": 0.71,
                  "match_reason": { "matched_skills": [...], "matched_keywords": [...], "matched_fields": [...] } } ] }  // 계약: RAG 명세서(3필드)
```
- 정렬: `score` 내림차순 / 기본 `TOP_K=3` / 결과 0건 → `{ "postings": [] }`
- 상세 계약: `rag_입출력 관련 명세서/RAG_입출력_명세서.md`

### 2.4 run_agent 반환 계약 (core 출력)
```jsonc
{ "reply": "<자연어 응답>",
  "meta": { "tools_called": ["load_posting","analyze_gap", ...], "level": "상|중|하|null", "run_id": "<uuid>" } }
```
- `meta.tools_called`·`level`로 성공 판정(§8) 검증. `run_id`로 로그 연결. FastAPI(task 09)는 봉투로 감쌈.
- ~~scenario~~ 제거(D11 후속): agent는 자기 시나리오를 자칭 안 함. scenario 판정은 test 쪽(task 08).

---

## 3. 목표 디렉토리 구조 (모듈 = 장애 격리선, 과분할 금지)

```
Agent_Test/
├─ agent/         LangGraph StateGraph · 라우팅 · run_agent() 진입점
├─ tools/         analyze_gap.py · search_postings.py(mock) · load_posting.py   ← 파일 1개 = 툴 1개
├─ preprocess/    resume_parser (docx→text→profile)
├─ llm/           GMS 클라이언트 · 모델 티어 매핑 (모델 선택·호출 단일 창구)
├─ schemas/       Pydantic 모델 (profile · 공고 · 툴 I·O · run_agent 반환)
├─ api/           FastAPI 라우터 (얇게) — 후순위(task 09)
├─ sample_data/   (기존) 공고 JSON · 이력서 docx  ← 재사용, 이동 금지
└─ run.py         스모크 실행 진입점
```

---

## 4. 계약 규격 (2층)

### 4.1 내부 툴 I/O 계약 — **주 계약**
- 툴은 예외를 throw하지 않고 **결과 객체**로 실패 반환: `{ "error": "<CODE>", "source": "<모듈명>", "detail": "..." }` (§7).
- 파괴적 동작 없음(조회·분석만) → confirm 파라미터 불필요.

| 툴 | 입력 | 출력(성공) | 실패 | 사용 조건 |
|---|---|---|---|---|
| `load_posting` | 공고 URL(str) | 공고 JSON 1건(원본) | `NOT_FOUND` | 사용자가 공고 URL 제시 (시나리오 2·3) |
| `analyze_gap` | profile(JSON) + 공고(JSON, `detail_text`) | `{ score, level, matched_required[], missing_required[], matched_preferred[], uncertain[], rationale }` | `INSUFFICIENT_INPUT` | 이력서·공고 둘 다 (시나리오 3) |
| `search_postings` | 직업명(str) **또는** profile(JSON) | `{ postings: [...] }` (§2.3) | 0건→`{postings:[]}` / 오류→`SEARCH_FAILED` | 추천(1)·직군검색(4)·대체직군(3 중·하) |

### 4.2 외부 API 계약 (FastAPI ↔ Java) — **후순위(task 09)**
- `run_agent()` 반환(§2.4)을 `{ "success": bool, "data": {...}, "error": null }` 봉투로 감쌈.
- 엔드포인트 표면(단일 POST vs 시나리오별)은 ⟨확정 필요 — task 09⟩. 지금 확정 안 함.

---

## 5. 핵심 비즈니스 로직

### 5.1 analyze_gap 채점
```
1) [LLM/mid] detail_text → 필수/우대 항목 리스트 추출
2) **룰 스킬 매칭(met)** + 나머지 [LLM/strong] 폴백 (met / not_met / uncertain)  ← 결정론 우선(task 06)
3) [알고리즘] 가중치 합산(**uncertain 제외**) → score → level(상/중/하)
```
- **확정(task 06):** score≥0.70 상 / 0.40~0.70 중 / <0.40 하. required=1.0·preferred=0.5, met=1.0·not_met=0.0. `uncertain`은 not_met과 구분(분모 제외).

### 5.2 라우팅 = LLM 동적 계획 (고정 시나리오 아님) — *설계서 §4 ReAct·§6.1*
사용자 **자연어 쿼리**를 LLM이 읽고, `profile` 존재 여부 등 컨텍스트와 함께 **어떤 툴을 호출할지 동적으로 계획**한다(ReAct 루프). 규칙 기반 시나리오 분류가 **아니다**.
- 아래 6개는 **하드코딩 분기가 아니라** LLM을 유도하는 **행동 지침 + 성공판정 테스트 케이스**다.

| # | 입력(예) | 의도된 행동 (LLM 지침) |
|---|---|---|
| 1 | 이력서 O / 공고 X | 파싱 → `search_postings` → (공고 선택) → 갭분석 유도 |
| 2 | 이력서 X / 공고 O | `load_posting` → LLM 공고 정리 → 이력서 입력 유도 |
| 3 | 이력서 O / 공고 O | `analyze_gap` → **[관찰 level]** → 분기(§5.3) — **핵심** |
| 4 | 직군명 | `search_postings` |
| 5 | 일상 대화 | 툴 없음 → 시나리오 1·2·3 안내·유도 (Guardrail) |
| 6 | 취업 무관 | 툴 없음 → "취업 관련 외 질의는 받지 않습니다" 거절 |

> **확정(D11 = B 아키텍처):** tool-calling ReAct(LLM 동적 라우팅) + `analyze_gap` 후 **결정적 조건엣지**(level 중/하 → auto_search). 성공기준 1·4(호출 여부)는 LLM 의존(동적).

### 5.3 관찰 기반 분기 (Agent 핵심 — LangGraph conditional edge)
```
analyze_gap.level == "상"        → rationale만 출력, search_postings 호출 안 함
analyze_gap.level in ("중","하")  → rationale + Thought(대체직군) + 로드맵 + search_postings(대체직군)
```
> 이 분기는 **LLM 재량 아님, 규칙**. `route_after_gap(state)` conditional edge로 결정적 구현.

### 5.4 Thought (툴 아님)
- **대체직군 생성**(중/하) · **공고 정리**(load_posting 결과 요약). LLM 내부 추론이므로 툴로 만들지 않는다.

### 5.5 모델 티어 매핑 (정적 — `llm/` 창구에서만 관리) *(D7)*
| 티어 | 단계(모듈) | 모델(시작안) | 크레딧 |
|:---:|---|---|:---:|
| cheap | 라우팅 · 공고정리 · 최종 응답 | `gpt-4o-mini` | 2 |
| mid | docx→profile 추출 · 요건 추출 | `gpt-4.1-mini` | 4 |
| strong | 항목 매칭 · 대체직군 Thought | `gpt-4.1` 또는 `gpt-5` | 16~20 |
> 정확한 model 문자열·크레딧 상한 → ⟨확정 필요 — task 02⟩. cheap이라도 structured output 지원 모델이어야 함.

---

## 6. 코딩 컨벤션 (금지형)

| 항목 | 규칙 |
|---|---|
| 구조화 출력 | free-form 프롬프트 JSON 파싱 **금지**. `with_structured_output`(Pydantic)만 |
| 스키마 | `schemas/` 밖에서 dict 임의 조립 **금지** |
| 모델 선택 | 모듈이 모델·base_url 직접 지정 **금지**. `llm/` 창구 경유 (티어는 §5.5) |
| 시크릿 | `GMS_KEY` 소스 하드코딩 **금지**. 환경변수 주입 |
| 모듈 경계 | 층 건너뛴 직접 import **금지** (예: `api`가 `tools` 직접 X → `agent` 경유) |
| 노드 경계 | 그래프 노드 1개 = 단일 책임. 노드 간 공유는 State로만 |
| 툴 실패 | `raise`로 흐름 중단 **금지**. `{error, source, detail}` 반환 |
| 툴 신설 | 3툴 외 새 툴 **금지** |
| 멀티턴 | 대화 상태 누적 **금지** (싱글턴) |
| 서버 선행 | core 전에 FastAPI부터 **금지** |

---

## 7. 에러코드 / 공통 상수 *(design.md §6 이식)*

| 이름 | source | 의미 / 메시지 |
|---|---|---|
| `NOT_FOUND` | load_posting | 해당 URL 공고가 DB에 없음 |
| `INSUFFICIENT_INPUT` | analyze_gap | 이력서/공고 정보 부족 |
| `SEARCH_FAILED` | search_postings | 검색 오류 (0건은 에러 아님 → `{postings:[]}`) |
| 상수 `MAX_STEPS` | agent | 10 |
| 상수 `TOP_K` | search_postings | 3 |
| 상수 `LEVEL 임계치` | analyze_gap | **확정(task 06):** score≥0.70 상 / 0.40~0.70 중 / <0.40 하 |
| 상수 `MODEL_TIER[티어]` | llm | §5.5 → 실제 model 문자열 (task 02 확정) |

### 예외 흐름 *(design.md §5 이식)*
1. **URL 공고 DB에 없음** → `load_posting`이 `NOT_FOUND` 반환, agent는 크래시 없이 "공고를 찾지 못함" 안내. (성공기준 4)
2. ~~이력서 빈약 시 추가 질의~~ → **프로토타입 1.0.0 범위 밖.** 이력서 빈약 케이스는 상정하지 않는다(파싱된 profile은 유효하다고 가정).

---

## 8. 실행

- 사전조건: Python 3.11 → `python -m venv .venv` → `.venv/Scripts/python.exe -m pip install -r requirements.txt`. 환경변수 `GMS_KEY`·`OPENAI_API_BASE`는 `.env`로 주입(task 02~).
- 실행: `python run.py` — 서버 없이 core 직접 실행. **스모크 실행 + 성공 판정 케이스(§ 아래)가 게이트.**
- (task 09 후) `uvicorn api.main:app` 기동 + 엔드포인트 호출을 DoD에 추가.

### 성공 판정 기준 (구조적 동작만, 품질 아님) — *설계서 §8*
| # | 기준 | 판정(meta) |
|---|---|---|
| 1 | 시나리오 3에서 `analyze_gap` 호출 | `meta.tools_called` 포함 |
| 2 | level 중/하 → `search_postings` 호출 **★핵심** | `analyze_gap → search_postings` 순서 |
| 3 | level 상 → 추가 검색 없음 | search_postings **미포함** |
| 4 | 없는 URL → `NOT_FOUND`, 크래시 없이 안내 | error.source 확인 |
| 5 | 모든 요청 `MAX_STEPS`(10) 이내 종료 | step ≤ 10 |
