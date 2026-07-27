# RAG 어댑터 핸드오프 (RAG 담당자용)

이 문서는 자비스 AI 에이전트에 **RAG를 어떻게 붙이면 되는지**를 정리한다.
결론부터: 여러분은 **`RagAdapter` 인터페이스를 구현한 클래스(모듈 1개)** 만 만들어 주면 된다.
오케스트레이터·노드·계약 코드는 건드리지 않는다.

---

## 1. 우리 에이전트가 어떻게 설계되어 있나

### 1.1 전체 구조
**LangGraph 오케스트레이터 + 역할별 LangChain 워커 에이전트** 구조다.
오케스트레이터는 "언제 무엇을 할지"(제어·상태·분기·재시도)만 담당하고,
각 워커 노드는 자기 일(공고 파싱, 프로필 구조화, 갭 분석 등)만 한다.

```text
START
→ parse_job_posting      (공고 → 구조화 요구사항)
→ build_user_profile     (이력서 → evidence 중심 프로필)
→ check_sufficiency      (정보 충분성 분기)
    ├─ 부족 → ask_user → assemble_output
    └─ 충분 → analyze_gap        (요구사항 vs 프로필 충족 판정)   ★ RAG hook ①
→ plan_roadmap           (부족 역량 → 기간별 로드맵)
→ (옵션) find_alternatives (대체 취업 경로 제안)                 ★ RAG hook ②
→ verify_result          (스키마·표현·근거·정합성 검증, 재시도 신호)
→ assemble_output → END
```

노드 현황: **모든 워커 노드가 실제 LLM/규칙으로 구현됨**. RAG만 아직 미연결(Null)이다.

### 1.2 설계 원칙 (RAG도 이걸 따른다)
- **부품 교체식 모듈화**: 설정/LLM/추출/RAG는 각각 독립 계층. 개인 키·구현만 갈아끼우면 남의 코드 안 건드리고 동작.
- **예외보다 warning**: 외부 호출(문서추출·LLM·RAG) 실패는 예외로 그래프를 죽이지 않고 warning으로 흡수 → 최소 결과는 항상 나온다.
- **계약 불변**: `AnalyzeRequest`/`AnalyzeResponse`/`GraphState`/노드 입출력 스키마는 함부로 안 바꾼다.

### 1.3 데이터 조회 우선순위 (설계 6장)
모든 에이전트는 동일한 접근 순서를 따른다. **RAG는 이 사다리의 2번**이다.

1. 내부 정형 DB
2. **벡터 DB 또는 RAG  ← 여러분 담당**
3. 자체 웹 검색 툴
4. 외부 LLM 검색 기능

즉 RAG는 "내부 DB로 안 되는 비정형 지식(기업 맥락, 유사 공고, 후기·통계 등)"을 채우는 계층이다.

---

## 2. RAG가 꽂히는 자리 (2개 hook point)

오케스트레이터는 "언제 RAG가 필요한지"만 판단하고, **실제 검색은 여러분 어댑터에 위임**한다.
노드는 `get_rag_adapter()`가 돌려준 어댑터의 메서드만 부른다. 지금은 `NullRagAdapter`(빈 결과)라서 프로필 근거만으로 돌아간다.

| hook | 부르는 노드 | 목적 | 미연결(Null) 시 현재 동작 |
|---|---|---|---|
| `fetch_company_context` | `analyze_gap` (갭 분석) | 기업 인재상·기술문화·기업정보 등 **판정 근거 보강** | 기업 맥락 없이 프로필 근거만으로 판정 + warning |
| `search` | `find_alternatives` (대체 경로) | **유사 직무/저연차/유사 스택 공고 후보** 검색 | 실제 공고 안 지어내고 경로 '유형'만 제안 + warning |

> 연결되는 순간, 같은 노드가 여러분이 준 `items`를 LLM 프롬프트에 주입해 근거를 붙인다. 노드 수정 없음.

---

## 3. 여러분이 구현할 계약 — `RagAdapter`

기준 파일: **`src/jobis_ai/rag.py`** (이게 곧 명세. `NullRagAdapter`가 참고용 레퍼런스 구현).

### 3.1 만들 것
새 모듈(예: `src/jobis_ai/rag_impl/<provider>.py`)에 아래 **메서드 2개**를 구현한 클래스.

```python
from jobis_ai.rag import RagResult

class MyRagAdapter:            # 이름 자유
    def fetch_company_context(self, company_name: str, requirements: list[dict]) -> RagResult:
        """기업 맥락 조회. requirements 각 항목: {requirementId, text, type}."""
        ...

    def search(self, query: str, *, top_k: int = 5) -> RagResult:
        """유사 공고/대체 경로 후보 검색. query 는 직무·기술·gap 로 만든 문자열."""
        ...
```

### 3.2 돌려줄 형식 — `RagResult`
```python
RagResult(
    items:    list[dict]   # 검색된 컨텍스트 조각. 각 dict 최소 "text" 포함 → LLM 프롬프트에 주입
    sources:  list[dict]   # 출처 메타 {title, url, ...} → GraphState.sources 로 누적(추적성)
    warnings: list[dict]   # {code, message} 실패/빈결과/저신뢰
)
```

**hook별 items 권장 필드**
- `fetch_company_context` → `{"text": "...", "title": "...", "url": "..."}` (자유 텍스트 맥락으로 충분)
- `search` → `{"text": "...", "title": "...", "companyName": "...", "jobPostingId": "...", "url": "..."}`
  (LLM이 이 후보를 alternativeJobs로 매핑하므로 공고 식별 정보가 있으면 좋다)

### 3.3 등록 (한 줄)
`src/jobis_ai/rag.py`의 `get_rag_adapter()`에 provider 분기 추가 + `.env`의 `RAG_PROVIDER` 설정.
```python
# get_rag_adapter() 안
if provider == "my_provider":
    from jobis_ai.rag_impl.my_provider import MyRagAdapter
    return MyRagAdapter()
```
```bash
# .env
RAG_PROVIDER=my_provider
```

### 3.4 반드시 지킬 규칙
1. **절대 예외를 던지지 않는다.** 실패·timeout·빈결과 모두 `RagResult(warnings=[{"code","message"}])`로 반환. (그래야 그래프가 안 죽는다)
2. **빈 결과는 정상.** `items=[]` + warning이면 노드가 알아서 폴백한다.
3. **저신뢰 결과는 warning으로 표시**해 후단(verify_result)이 인지하게 한다.
4. 검색 내부(임베딩·청킹·벡터스토어·리랭킹)는 **전적으로 여러분 자유**. 노드/계약/그래프는 손대지 않는다.

---

## 4. RAG는 어떤 식으로 진행하면 좋을까 (권장 방향)

우리 쪽에서 강제하는 건 위 §3 계약뿐이고, 아래는 협업을 매끄럽게 하기 위한 제안이다.

### 4.1 무엇을 인덱싱하면 좋은가
- **기업 맥락**(hook ①용): 기업 소개·인재상·기술 블로그·채용 FAQ·기업 리뷰/통계 등.
  갭 분석이 "이 회사가 원하는 결"을 판단하는 근거로 쓴다.
- **공고 코퍼스**(hook ②용): 유사 직무/저연차/유사 스택 공고 모음.
  대체 경로 추천이 "실제 존재하는 진입 가능한 자리"를 제시하는 근거로 쓴다.

### 4.2 반환할 때의 팁
- `items[].text`는 **LLM이 바로 읽는 근거**다. 너무 길지 않게(조각당 수백자), 관련도 높은 순으로.
- 관련도/유사도 점수가 있으면 `items[].score`로 같이 주면 후단에서 신뢰도 판단에 쓰기 좋다.
- 모든 조각에 대응하는 `sources`(title/url)를 넣어 주면 결과에 출처가 붙어 추적성이 좋아진다.

### 4.3 단계적으로 붙이기 (작은 단위 권장)
1. **hook ①(`fetch_company_context`) 먼저.** 갭 분석 품질에 직접 기여하고, 반환도 자유 텍스트라 난이도가 낮다.
2. 그다음 **hook ②(`search`)** — 공고 코퍼스와 후보 스키마가 갖춰지면.
3. 각 단계는 독립적으로 붙고, 붙기 전엔 Null이 자동 폴백하므로 **부분 연결 상태로도 전체 파이프라인이 돈다.**

### 4.4 우리가 보장하는 것
- 여러분 어댑터가 없거나 일부만 있어도 **파이프라인은 항상 최소 결과를 낸다**(Null 폴백).
- 노드/프롬프트가 `items`를 어떻게 쓰는지는 우리가 유지·조정한다. 여러분은 **좋은 근거 조각을 돌려주는 것에만 집중**하면 된다.

---

## 5. 로컬에서 어댑터 테스트하는 법

계약만 지키면 우리 테스트 하네스에 바로 물린다.

- 단위 확인: 어댑터를 직접 만들어 `fetch_company_context(...)`/`search(...)`가 `RagResult`를 반환하고 **예외를 안 던지는지** 확인.
- 통합 확인: `.env`에 `RAG_PROVIDER=<your>` 설정 후 `python tests/run_user1.py` 실행 → `analyze_gap`/`find_alternatives` 출력의 `companyContext`/`alternativeJobs`·`sources`에 여러분 결과가 실리는지 본다.
- 참고: 자동 테스트(`pytest`)는 LLM을 mock으로 강제해 결정적으로 돈다. RAG 어댑터 유닛 테스트도 같은 방식(네트워크 없이 결정적)으로 작성하길 권장.

---

## 6. RAG가 필요로 하는 데이터

더미 몇 개로는 **"배관이 연결되는지"만** 검증된다. RAG의 실제 가치(관련도 높은 근거 검색)는
**규모 있고 실제성 있는 코퍼스 + 임베딩 + 벡터스토어**가 있어야 나온다.
(우리가 만든 이력서 더미 1개와는 성격이 다르다.)

### 6.1 hook별 필요 코퍼스
| hook | 필요한 코퍼스 | 예시 소스 |
|---|---|---|
| `fetch_company_context` | **기업 지식**: 기업 소개·인재상·기술문화, 기술 블로그, 채용 FAQ, 기업 리뷰/통계 | 기업 홈페이지·채용페이지, 기술블로그, 리뷰 사이트, 기업정보 API |
| `search` | **채용공고 코퍼스**: 유사 직무·저연차·유사 스택 공고 다수 | 잡코리아·사람인·원티드 등 공개 공고 |

설계 6장 우선순위(내부 DB → 벡터/RAG → 웹)에 따라 역할이 갈린다:
정형 정보(회사명·업종·규모)는 내부 DB, **비정형 지식(인재상·문화·후기·유사 공고 본문)이 RAG 담당분**이다.

### 6.2 왜 더미로 부족한가
- `search` 가 "실제 진입 가능한 대체 자리"를 제시하려면 공고가 **최소 수백~수천 건** 규모여야 유사도 검색이 의미 있다. 소수 더미는 늘 같은 걸 반환한다.
- `fetch_company_context` 는 **지원 대상 기업들의 실제 정보**가 있어야 판정 근거로 쓸 수 있다. 가짜 기업 소개는 판정을 왜곡한다.

### 6.3 2단계 접근 (권장)
1. **Seed/더미 단계 (배관 검증)**: 공고 5~10건 + 기업 소개 2~3건을 손으로 만들어 적재. 어댑터가 `RagResult` 를 반환하고 노드가 `items` 를 실제로 쓰는지 통합 확인. — 여기까진 더미로 충분.
2. **실제 코퍼스 단계 (가치 창출)**: 공개 채용사이트 공고 수집 → 청킹 → 임베딩 → 벡터스토어(`{text,title,companyName,jobPostingId,url}`), 대상 기업 지식 수집. 규모는 공고 최소 수백 건 이상.

### 6.4 우리 파이프라인과의 연결
현재 테스트의 **잡코리아 백엔드 공고**가 곧 `search` 코퍼스의 한 조각이고, 그 **대상 기업**이 `fetch_company_context` 가 채울 기업 지식이다. RAG 팀의 "공고 수집 + 기업정보 수집" 결과가 두 hook 으로 그대로 흘러든다.

### 6.5 주의점
- **수집 합법성**: 사이트 robots/ToS, 리뷰 사이트 크롤링 제약 확인.
- **신선도**: 공고는 만료됨 → 수집 시점/만료 메타 필요.
- **중복 제거·정규화**: 같은 공고가 여러 사이트에 게재됨.

---

## 7. 요약

| 구분 | 내용 |
|---|---|
| 우리가 주는 것 | `src/jobis_ai/rag.py` (인터페이스 계약 = `RagAdapter` + `RagResult` + `NullRagAdapter` 레퍼런스) |
| 여러분이 주는 것 | `RagAdapter` 구현 클래스 모듈 1개 + `get_rag_adapter()` provider 분기 한 줄 |
| 구현할 메서드 | `fetch_company_context(company_name, requirements)`, `search(query, *, top_k=5)` |
| 반환 | `RagResult(items, sources, warnings)` — 예외 금지, 빈 결과 OK |
| 건드리지 않을 것 | 노드/그래프/계약(`AnalyzeRequest`·`AnalyzeResponse`·`GraphState`) |
