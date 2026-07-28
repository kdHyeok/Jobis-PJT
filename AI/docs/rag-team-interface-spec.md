# RAG 팀 인터페이스 명세서 (AI 오케스트레이터 → RAG)

> **목적.** RAG 팀이 "AI 파이프라인이 **언제 · 무엇을 물어보고 · 어떤 형태의 답을 기대하는지**"를 이 문서 하나로 알 수 있게 한다.
> 구현 스택(Chroma/pgvector/Elastic…)은 자유. **우리는 아래 계약(`RagAdapter`)만 호출**하고 내부는 모른다.
>
> 관련 문서: [agent-derivation-and-tools.md](./agent-derivation-and-tools.md) (RAG가 꽂히는 자리 §1), 코드 계약: [`src/jobis_ai/rag.py`](../src/jobis_ai/rag.py)

---

## 0. 30초 요약 — RAG가 우리에게 해줘야 하는 일

| # | 우리 노드 | 사용자 상황(언제) | RAG에게 던지는 질문(입력) | RAG가 돌려줄 것(출력) |
|---|---|---|---|---|
| ① | `analyze_gap` (갭 분석) | 특정 **기업 공고**로 내 강약점 분석 요청 | "이 회사(company)의 인재상·기술문화·후기" | 기업 맥락 텍스트 조각 + 출처 |
| ② | `find_alternatives` (대체 경로) | "이 자리 어려우면 **비슷한 다른 자리** 추천" | "직무+강점+gap으로 만든 쿼리로 **실제 유사 공고**" | 실재 공고 본문 조각 + 출처 |


**핵심 경계선 (반드시 지킬 것):**
> **RAG는 "검색"만 한다. "판정·점수·추천 여부"는 절대 정하지 않는다.**
> 충족/미충족, 심각도, 합격 가능성, 추천 순위 같은 **판단은 100% 우리 알고리즘**이 한다.
> RAG는 그 판단의 **재료(비정형 지식 조각)**만 실어 보내면 된다. (설계 원칙: "판단은 데이터가, LLM/검색은 재료만")

---

## 1. 공통 계약 — 이 인터페이스만 구현하면 됩니다

우리는 [`src/jobis_ai/rag.py`](../src/jobis_ai/rag.py)의 `RagAdapter` Protocol을 호출합니다. RAG 팀은 이 3개 메서드를 구현한 클래스를 만들고, `get_rag_adapter()`의 provider 분기 한 줄만 추가하면 연결 끝입니다. **노드 코드는 바뀌지 않습니다.**

```python
class RagAdapter(Protocol):
    def fetch_company_context(self, company_name: str, requirements: list[dict]) -> RagResult: ...
    def search(self, query: str, *, top_k: int = 5) -> RagResult: ...
    # (선택 확장) def learning_resource_search(self, query: str, *, top_k: int = 5) -> RagResult: ...
```

### 반환 타입: 항상 `RagResult` (예외 던지지 말 것)

```python
@dataclass
class RagResult:
    items:    list[dict]   # 검색된 컨텍스트 조각들. LLM 프롬프트에 주입됨.  각 dict 최소 {"text": ...}
    sources:  list[dict]   # 출처 메타. 추적성 위해 최종 결과에 누적됨.   각 dict 최소 {"title","url"}
    warnings: list[dict]   # 실패/저신뢰/빈 결과 등. 각 dict {"code","message"}
```

**절대 규칙 (핸드오프 원칙 "RAG 실패도 전체 실패로 만들지 말 것"):**
- ❌ **예외를 던지지 마세요.** 실패해도 `RagResult(warnings=[...])`로 **정상 반환**. 우리 그래프가 죽으면 안 됨.
- ✅ 결과 없음 → `items=[]` + `warnings=[{"code":"no_result", ...}]`. 빈 결과는 유효한 답입니다.
- ✅ `items`의 각 dict는 **최소 `text` 키** 필수. 나머지 메타(score, chunkId 등)는 자유롭게 추가.
- ✅ `sources`의 각 dict는 **최소 `title`, `url`** 필수. (없으면 `url:""`이라도. 추적성 때문에 title은 꼭)

---

## 2. 훅 ① `fetch_company_context` — 기업 맥락 (갭 분석용, **1순위**)

### 언제 호출되나
사용자가 **특정 기업의 공고**를 넣고 자기 강약점 분석을 요청 → `analyze_gap` 노드가 판정을 **보정·근거 첨부**하려고 호출.

### 입력
```python
def fetch_company_context(self, company_name: str, requirements: list[dict]) -> RagResult
```
| 파라미터 | 타입 | 의미 | 예시 |
|---|---|---|---|
| `company_name` | `str` | 대상 회사명 (정규화 안 된 원문일 수 있음) | `"토스"`, `"비바리퍼블리카"` |
| `requirements` | `list[dict]` | 공고 요구사항 목록. 관련 맥락을 좁히는 힌트로 사용 | 아래 |

`requirements`의 각 dict 형태 (`Requirement` 모델):
```json
{ "requirementId": "req-1", "text": "Spring Boot 3년 이상", "type": "required" }
```

### 우리가 기대하는 출력
회사의 **비정형 지식** — 인재상, 기술문화, 기술블로그 내용, 재직자/면접 후기 등. 정형 스키마로 못 넣는 것들.

```python
RagResult(
    items=[
        {"text": "토스는 '자율과 책임' 문화를 강조하며 코드 오너십을 중시…",
         "topic": "인재상", "score": 0.82},
        {"text": "기술블로그에서 Kotlin+Spring, 이벤트 드리븐 아키텍처 채택을 언급…",
         "topic": "기술문화", "score": 0.77},
    ],
    sources=[
        {"title": "토스 기술블로그 - 서버 아키텍처", "url": "https://toss.tech/..."},
        {"title": "토스 채용 - 인재상", "url": "https://toss.im/career"},
    ],
    warnings=[],  # 기업 데이터 없으면 [{"code":"no_result","message":"'토스' 기업 코퍼스 없음"}]
)
```

### 검색해야 할 코퍼스 / 품질 기준
- **코퍼스:** 기업 채용페이지, 기술블로그, 재직/면접 후기, 뉴스.
- **품질:** `company_name`과 무관한 조각을 섞지 말 것(오염 방지). 확신 낮으면 `score` 낮게 표기하고 `warnings`에 남기기.
- **개수:** items 3~8개 권장(너무 많으면 프롬프트 오염).

---

## 3. 훅 ② `search` — 실제 유사 공고 검색 (대체 경로용, **2순위**)

### 언제 호출되나
사용자가 "이 자리 어려우면 **비슷하거나 낮은 연차 자리**를 추천해줘" 요청 → `find_alternatives` 노드가 **허구 공고를 지어내지 않으려고** 실데이터를 검색. **여기가 RAG가 필수인 이유: 실재하는 자리만 제시해야 함.**

### 입력
```python
def search(self, query: str, *, top_k: int = 5) -> RagResult
```
| 파라미터 | 타입 | 의미 | 예시 |
|---|---|---|---|
| `query` | `str` | 우리가 룰로 조립한 검색 쿼리 (직무 + 강점 + 완화할 gap) | `"백엔드 주니어 Spring Java 신입 3년이하 유사스택"` |
| `top_k` | `int` | 원하는 결과 수 (기본 5) | `5` |

### 우리가 기대하는 출력
**실재하는 채용공고 본문** 조각. 각 조각에 공고 식별자(`sourceJobPostingId`로 우리가 다시 쓰기 위함)와 회사명이 있으면 좋음.

```python
RagResult(
    items=[
        {"text": "[○○테크] 주니어 백엔드 - Java/Spring, 경력 1~3년, MSA 경험 우대…",
         "jobPostingId": "jp-10231", "companyName": "○○테크",
         "roleCategory": "backend", "seniority": "junior", "score": 0.88},
    ],
    sources=[
        {"title": "○○테크 주니어 백엔드 채용", "url": "https://.../jobs/10231"},
    ],
    warnings=[],
)
```

> `items[].jobPostingId` / `companyName`은 우리가 `AlternativeJob.sourceJobPostingId`, `companyName`에 채워 넣어 추적성을 만듭니다. **가급적 포함**해 주세요. (없으면 `text`만으로도 동작은 함)

### 검색해야 할 코퍼스 / 품질 기준
- **코퍼스:** 실제 채용공고 본문 코퍼스.
- **품질:** **지어낸 공고 금지.** 실존 공고만. 유사도 `score` 표기. `query`의 직무/연차와 동떨어진 결과는 배제.

### 🔑 RAG 개발 담당 — 대체 경로 검색 흐름 (필수 구현)

> `find_alternatives`는 "사용자 gap이 목표 공고와 **크게 차이 날 때**" 호출된다. 이때 단순히 유사 공고를 뿌리는 게 아니라, **"징검다리 하위 직업군"을 거쳐 실현 가능한 경로**를 찾아야 한다. `search`는 그 마지막 검색 단계를 담당한다. 아래 흐름으로 개발해 주세요.

```text
[오케스트레이터가 하는 일 — RAG 앞단]
1. gap 차이 판정: 사용자 강점 vs 목표 공고 요구 gap 이 임계값 이상 벌어짐 → 대체 경로 탐색 트리거
2. 목표 직업군 확인: 목표 공고의 roleCategory 추출 (예: "senior backend")
3. 하위 직업군 도출: 그 직업군으로 경력을 쌓아 도달 가능한 '하위/징검다리 직업군' 목록 생성
   (career_graph 전이 그래프. 예: senior backend ← junior backend ← 백엔드 인턴 / SI 백엔드 …)

[RAG 가 하는 일 — search() 안]
4. 하위 직업군들을 기반으로 query 를 받아 검색:
   (a) 1차: 내부 DB 기업 공고 코퍼스에서 벡터 유사도 비교로 실존 공고 검색
   (b) 2차(폴백): 1차 결과가 부족(top_k 미달·저score·no_result)하면 → 웹검색으로 보강
5. 실존 공고 조각 + 출처를 RagResult 로 반환 (지어내기 금지)
```

**즉 우리(오케스트레이터)는 2·3단계(목표 직업군 → 하위 직업군)까지 풀어서 `query`에 실어 보냅니다.** 예:
```python
# 오케스트레이터가 조립해 넘기는 query 예시
search("주니어 백엔드 OR 백엔드 인턴 OR SI 백엔드, Spring Java, 경력 3년 이하 유사스택")
```
RAG 담당은 **4단계(벡터 검색 → 부족 시 웹검색 폴백)**만 `search()` 내부에서 구현하면 됩니다.

- **(a) 벡터 검색:** 내부 공고 코퍼스에서 query 와 의미 유사한 실존 공고. `score` 표기.
- **(b) 웹검색 폴백:** 내부 코퍼스로 부족할 때만. 웹에서 찾은 것도 **실존 공고**여야 하고 `url` 필수. `warnings`에 `{"code":"web_fallback"}` 남겨 주세요(출처가 내부가 아님을 우리가 표시하기 위함).
- **가능하면 반환 조각에 `roleCategory`/`seniority`를 넣어** 주세요. 우리가 "이게 어느 하위 직업군 결과인지" 되짚습니다.
- 둘 다 실패 → `items=[]` + `warnings=[{"code":"no_result"}]`. 그러면 우리는 **경로 '유형'만** 제안하고 구체 공고는 미확정 처리(허구 방지).

---

## 4. 훅 ③ `learning_resource_search` — 학습자료 (로드맵용, **선택·신규**)

> 계약에 **없던 신규 확장**입니다. 여력 될 때 추가. 없으면 우리는 내부 `roadmap_db`만 씁니다.

### 언제 호출되나
`plan_roadmap`이 부족 스킬의 학습계획을 짤 때, 내부 DB로 **부족한 최신 자료만 보강**하려고 호출.

### 입력 / 출력
```python
def learning_resource_search(self, query: str, *, top_k: int = 5) -> RagResult
```
```python
RagResult(
    items=[
        {"text": "Spring Boot 3 실전 강의 - 트랜잭션/JPA 심화", "resourceType": "course",
         "difficulty": "intermediate", "estimatedHours": 20, "score": 0.8},
    ],
    sources=[{"title": "인프런 - Spring Boot 심화", "url": "https://..."}],
    warnings=[],
)
```
- **코퍼스:** 강의/아티클/오픈소스 프로젝트 레퍼런스 (최신성 중요).
- `resourceType`(course/article/project), `difficulty`, `estimatedHours`가 있으면 우리 스케줄러가 주차 배치에 바로 활용.

---

## 5. 하지 말아야 할 것 (Non-goals) — 경계선

| ❌ RAG가 하면 안 되는 것 | ✅ 대신 우리가 함 |
|---|---|
| 요구사항 충족/미충족 **판정** | `gap_matcher`(임베딩+룰) |
| 심각도(high/medium/low), 점수 매기기 | 우리 룰/집계 계산 |
| "이 사람 합격 가능성" 같은 결론 | 우리 알고리즘 |
| 대체 공고 **추천 순위·이유 서술** | 우리 매칭 + LLM 말하기 |
| 공고/자료를 **지어내기(hallucination)** | 실데이터만 반환. 없으면 빈 결과 |

RAG의 산출물은 전부 **"판단의 재료"**일 뿐, **"판단 자체"**가 아닙니다.

---

## 6. 연결 방법 (RAG 팀 작업 순서)

1. `RagAdapter`의 3(또는 2)개 메서드를 구현한 클래스 작성 (예: `ChromaRagAdapter`).
2. [`rag.py`](../src/jobis_ai/rag.py)의 `get_rag_adapter()`에 provider 분기 한 줄 추가:
   ```python
   if provider == "chroma":
       from jobis_ai.rag_impl.chroma import ChromaRagAdapter
       return ChromaRagAdapter()
   ```
3. 환경설정 `RAG_PROVIDER=chroma`로 스위치. **노드 코드는 손 안 댐.**
4. 미연결 시 기본값은 `NullRagAdapter`(빈 결과 + warning) → 우리 그래프는 RAG 없이도 최소 분석을 냅니다.

---

## 7. 완료 체크리스트 (RAG 팀 셀프 점검)

- [ ] 세 메서드 모두 **예외 없이** `RagResult` 반환 (실패도 warning으로)
- [ ] `items[]`에 **`text` 키** 항상 존재
- [ ] `sources[]`에 **`title`(+가능하면 `url`)** 존재
- [ ] `search`는 **실존 공고만**, 가능하면 `jobPostingId`/`companyName` 포함
- [ ] `fetch_company_context`는 **해당 회사와 무관한 조각 배제**
- [ ] 결과 없음 → `items=[]` + `warnings=[{"code":"no_result", ...}]`
- [ ] **판정/점수/추천여부를 스스로 정하지 않음** (검색 재료만 제공)

---

### 문의
인터페이스/스키마 관련해서 애매하면 갭 분석·대체경로 노드 담당(오케스트레이터 팀)에게. 계약 원본은 [`src/jobis_ai/rag.py`](../src/jobis_ai/rag.py), 도메인 스키마는 [`src/jobis_ai/contracts/domain.py`](../src/jobis_ai/contracts/domain.py).
