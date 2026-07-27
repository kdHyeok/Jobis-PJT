# 에이전트별 도출 방법 · 툴 · RAG 배치 정의서

> **0715 개선사항 후속.** 진단은 끝났다("지금은 LLM 파이프라인 + 약한 구조화"). 이 문서는 그 진단을
> 실제 설계로 확정한다: **각 노드에서 답을 무엇으로 도출하고(RAG/DB/룰/임베딩/계산), 무슨 툴이 필요하며,
> LLM은 어디까지만 쓰는지**를 전부 정의한다.
>
> 핵심 원칙 한 줄: **"판단·매칭·계산은 우리 알고리즘(RAG/DB/룰/임베딩)이 하고, LLM은 마지막에 그 답을 사람이 말하듯 바꾸는 일만 한다."**
>
> ---
>
> **구현 상태 (2026-07-20 기준)**: **9개 노드 전부 이 설계대로 전환 완료 + `check_profile_completeness`
> 신규 노드 1개 추가(총 10개, §3.2 후속·비블로킹).** 툴 카탈로그(§4)의 신규 툴 12개를 구현·연결했고,
> 판단 계층 5개 노드는 LLM을 호출하지 않는다(§4.1 검증표). `NormalizedUserProfile`의 자유 dict
> 필드(education/experiences/projects/skills/certifications/languages/bootcamp/awards)를
> 전부 pydantic 하위 모델로 타입 강제했고, `evidenceMap`에는 원문 대조 환각 검증을 추가했다(§5.9).
> 구현하며 내린 추가 결정은 **§5**에 기록했다 — 되돌리기 전에 반드시 읽을 것.
>
> **아직 안 된 것**: `embed` 미연결(→ 서술형 요구사항이 전부 `uncertain`), RAG hook ①② 미연결.
> 상세는 §4.3. 테스트는 §4.2 (133건, LLM 없이 1초 미만).
>
> 이 문서는 설계 의도와 그 배경(왜 그렇게 정했는지)을 담는다. 각 툴의 구체적 동작·임계값은
> 해당 모듈의 docstring이 정본이다(`src/jobis_ai/*.py`).

---

## 0. 3계층 아키텍처 (모든 노드를 이 셋 중 하나로 분류)

LLM을 "쓴다/안 쓴다"가 아니라 **역할을 3개로 쪼갠다.** 이렇게 하면 "파서는 LLM 써도 되는데 왜 갭 분석은 안 되냐"는 혼선이 사라진다.

| 계층 | 하는 일 | 허용 도구 | LLM 허용? |
|---|---|---|---|
| **① 읽기 (Read)** | 비정형 텍스트 → 정형 필드 (추출) | `extract_text`, `run_structured`, taxonomy | ✅ **읽기 용도만.** 원문에 없는 사실 생성 금지 |
| **② 판단 (Decide)** | 정형 데이터로 매칭·계산·검색·검증 (**결정**) | RAG, DB, 룰, 임베딩, 스케줄러 | ❌ **금지.** 여기가 결정론이어야 신뢰성이 나온다 |
| **③ 말하기 (Speak)** | 정형 결정 → 자연어 서술 (**표현**) | `nl_render`(LLM) | ✅ **표현 용도만.** 주어진 결정만 서술, 새 사실 금지 |

- **읽기**의 LLM은 "판단"이 아니다. `req-3 = 'Spring Boot 3년'`처럼 **원문 조각을 뽑는 것**이지, "이 사람이 부족하다"를 정하는 게 아니다.
- **판단**은 전부 알고리즘. "충족/미충족", "심각도", "추천 여부", "합격 여부"는 절대 LLM이 정하지 않는다.
- **말하기**는 마지막에 딱 한 번(assemble). 판정 reason 문장 다듬기 정도만 중간 노드에서 허용.

> 결론적으로 LLM 호출은 **입구(읽기)와 출구(말하기)** 두 곳에만 몰린다. 시스템의 몸통(판단)은 데이터가 돌린다.

---

## 1. 전체 파이프라인에서 RAG가 꽂히는 자리

```text
START
→ parse_job_posting             [읽기]   RAG ❌
→ build_user_profile            [읽기]   RAG ❌
→ check_profile_completeness    [판단]   RAG ❌  (순수 룰, 비블로킹 — §5.9 evidenceMap 환각 검증도 이 앞단인 build_user_profile 내부에서 수행)
→ check_sufficiency     [판단]   RAG ❌  (순수 룰)r
    ├─ 부족 → ask_user   [말하기] RAG ❌
    └─ 충분 → analyze_gap [판단]  ★ RAG hook ① fetch_company_context (기업 비정형 지식)
→ plan_roadmap          [판단]   RAG ❌  (자격증 정형 DB cert_db + skill_to_cert 매핑)
→ (옵션) find_alternatives [판단] ★ RAG hook ② search (채용공고 코퍼스)
→ verify_result         [판단]   RAG ❌  (근거 대조에 기존 sources만 사용)
→ assemble_output       [말하기] RAG ❌  ← LLM '말하기'의 본진
→ END
```

**RAG(벡터 검색)는 딱 2곳뿐.** 둘 다 이미 코드에 hook이 뚫려 있어(`rag.py`의 `RagAdapter` 계약), RAG 팀이 어댑터만 꽂으면 연결 끝. **나머지 노드는 RAG를 쓰지 않는다** — 정형으로 되면 정형 DB, 안 되면 룰/임베딩/계산.

| hook | 노드 | 무엇을 검색 | 왜 RAG(벡터)여야 하나 | 상태 |
|---|---|---|---|---|
| ① `fetch_company_context` | `analyze_gap` | 기업 인재상·기술문화·기술블로그·후기 | **비정형·회사마다 다름.** 정형 스키마로 못 넣음. 의미 유사 검색 필요 | 코드 hook 존재, 미연결(Null) |
| ② `search` | `find_alternatives` | 실제 유사/저연차/유사스택 **공고 본문** | 허구 공고 방지 → **실재하는 자리**만 제시하려면 실데이터 의미검색 필수 | 코드 hook 존재, 미연결(Null) |

> 둘 다 `rag.py`의 `RagAdapter` 계약(`fetch_company_context`, `search`)에 대응. **노드는 계약만 호출하고 내부(Chroma/pgvector/웹검색 폴백 등)는 모른다.**

**RAG를 쓰지 않기로 결정한 것 (한때 hook ③ 후보였으나 폐기):**

| 무엇 | 왜 RAG가 아닌가 | 대신 무엇으로 |
|---|---|---|
| **학습 로드맵 자료** (`plan_roadmap`) | 강의는 **무한·휘발성(매일 새로 나옴)** → 벡터 DB에 넣으면 곧 낡고 재색인 유지보수 부담. IT 자격증은 반대로 **유한·안정·정형** | **`cert_db`(자격증 정형 DB) + `skill_to_cert` 매핑.** 자격증 없는 경험형 gap은 **프로젝트 과제 템플릿**으로 보완 (§3.6) |
| **희소·신규 기업** (hook ① 커버 밖) | 코퍼스에 없는 회사는 미리 색인 불가 | hook ① **어댑터 내부의 웹검색 폴백**으로 흡수. 노드/계약은 불변(§2 사다리 3단계) |

> 즉 hook ①의 계약(`fetch_company_context`)은 그대로 두되, "코퍼스에 있으면 벡터 검색, 없으면 웹검색"은 **RAG 팀 구현 디테일**로 감춘다. 노드는 여전히 "기업 맥락 조각을 달라"고만 요청한다.

---

## 2. 데이터 조회 우선순위 (설계 6장, 판단 계층 공통 규칙)

판단 노드가 어떤 근거를 쓸지의 **사다리**. RAG는 2번이지 1번이 아니다.

```text
1. 내부 정형 DB       (skill/role taxonomy, cert_db, project_template_db, career_graph)  ← 먼저
2. 벡터 DB / RAG      (기업 지식, 공고 코퍼스, 학습자료)               ← 정형으로 안 되는 것만
3. 자체 웹 검색 툴     (최신·희소 정보)
4. 외부 LLM 검색기능
```

정형으로 표현 가능한 건(회사명, 스킬 카테고리, 직무 전이) **전부 내부 DB**. RAG는 **비정형 지식(인재상·문화·후기·공고 본문·학습자료)** 전담.

---

## 3. 노드별 정의 (전 9노드)

각 노드: **도출 방법(무엇이 답을 정하나) / 필요한 툴 / RAG / LLM 역할**.

### 3.1 `parse_job_posting` — 공고 파서 · [읽기]

| 항목 | 내용 |
|---|---|
| **답 도출** | **하이브리드 추출(룰 우선 → 잔여 비정형만 LLM).** ① `extract_text`로 원문 확보(비LLM) → ② **1차 룰/정규식 추출**(`rule_extractor`): 경력 연차(`3년 이상`/`3년+`/`3~5년`), 이메일·URL, 명시된 스킬 키워드 등 **명확한 패턴을 먼저 확정**(비LLM) → ③ **2차 LLM 추출**(`run_structured`): 룰이 **못 잡은 비정형 문장만** 요구사항으로 추출(읽기, 판단 아님) → ④ 기술스택 `skill_taxonomy.normalize`로 표준화(ReactJS→React, Node.js→Node) → ⑤ `roleCategory`/`seniority`는 `role_taxonomy` **룰 매핑**(LLM 추론 대신 규칙) |
| **필요 툴** | `extract_text`(기존), **`rule_extractor`(신규, 1차 정규식/키워드)**, `run_structured`(기존, **잔여 비정형 전용**으로 제한), **`skill_taxonomy`(신규)**, **`role_taxonomy`(신규)** |
| **RAG** | ❌ 공고 원문 자체가 소스 |
| **LLM 역할** | 룰이 못 잡은 **비정형 문장의 필드 추출(읽기)만.** 직무 카테고리·연차 "판단"은 taxonomy로 이관 |

> **왜 임베딩이 아니라 LLM인가.** 파서의 일은 "비정형 원문 → 정형 필드 **추출**"이다(예: `"Spring Boot 3년 이상 우대"` → `{req:"Spring Boot", years:3, level:"우대"}`). 이건 **생성/추출** 작업이라 임베딩 모델로는 불가능하다 — 임베딩은 문장을 벡터로 바꿀 뿐 필드를 뽑아내지 못한다. 임베딩이 쓰이는 곳은 파서가 아니라 **판단 계층**(`gap_matcher`의 유사도 매칭, §3.5)이다.
>
> **왜 하이브리드인가.** 순수 룰은 결정론·무비용·무환각이 강점이지만 비정형 문장(자유서술 공고)에서 재현율이 낮다. 순수 LLM은 비정형을 잘 잡지만 비용·환각 표면이 있다. → **정규식이 먼저 명확한 패턴을 확정하고, 못 잡은 나머지만 LLM으로 넘겨** 두 방식의 장점을 취한다(§2 데이터 조회 사다리 "정형은 룰, 안 되는 것만 상위 도구"와 일관). 이로써 LLM 호출량·환각 표면이 줄고 재현율은 유지된다.
>
> **변화점(✅ 적용 완료)**: 카테고리/연차까지 LLM이 "판단"하던 것을 taxonomy 룰로 옮겨 결정론화했다. 추출도 룰 우선으로 바꾸고, LLM은 잔여 비정형 추출까지로만 역할을 좁혔다.
>
> **구현 노트**: LLM의 읽기 스키마(`_JobPostingRead`)에서 `roleCategory`/`seniority` 필드를 **아예 제거**했다. 프롬프트로 "판단하지 마라"라고 적는 것보다, 줄 수 없는 답을 만들 수 없게 스키마에서 빼는 게 확실하다. 이 전략은 프로필 빌더(§3.2)와 `nl_render`(§3.9)에도 동일하게 적용했다.

### 3.2 `build_user_profile` — 프로필 빌더 · [읽기]

| 항목 | 내용 |
|---|---|
| **답 도출** | ① `extract_text`(이력서/포트폴리오) → ② `run_structured`(LLM)로 경력·프로젝트 **항목 추출**(읽기) → ③ 스킬 추출·정규화 `skill_taxonomy`(키워드+동의어, 비LLM) → ④ `evidenceMap`은 **각 스킬이 나온 문장 span을 룰로 매핑**(추적성) + 원문 대조로 환각 문장 제거(§5.9) |
| **필요 툴** | `extract_text`, `run_structured`(읽기 전용), `skill_taxonomy` |
| **RAG** | ❌ 개인 데이터 — 내부 DB/입력이 소스 |
| **LLM 역할** | 읽기(항목 추출)만. "이 경험이 이 스킬을 증명한다"는 매핑은 룰/임베딩 |

> **폐기(❌ 안 함)**: "⑤ `embed`로 유사 스킬 병합"은 계획으로만 있었고 구현하지 않기로 했다.
> `embed`(§4 참고)는 지금 `gap_matcher`의 2차 유사도 매칭(§3.5) 한 곳에서만 쓰인다.

### 3.3 `check_sufficiency` — 정보 충분성 분기 · [판단]

| 항목 | 내용 |
|---|---|
| **답 도출** | **순수 룰.** 필수 필드 존재 여부 + 요구사항 대비 프로필 커버리지 임계값(예: 스킬 evidence < N개, 핵심 required의 X% 이상이 근거 없음 → 부족) |
| **필요 툴** | 내부 룰 함수(`sufficiency_rules`) |
| **RAG** | ❌ |
| **LLM 역할** | **없음** |

### 3.4 `ask_user` — 추가 질문 · [말하기]

| 항목 | 내용 |
|---|---|
| **답 도출** | **어떤 필드가 비었는지 = 룰이 결정.** 질문 목록은 결측 필드 → **질문 템플릿** 매핑 |
| **필요 툴** | 결측필드 룰, 질문 템플릿, `nl_render`(선택) |
| **RAG** | ❌ |
| **LLM 역할** | **없음(구현 결과).** 템플릿 문구를 그대로 쓴다 — 다듬기는 `nl_render`로 붙일 수 있는 선택지로 남겨 뒀다. 무엇을 물을지는 룰이 결정 |

### 3.5 `analyze_gap` — 갭 분석 · [판단] ★ 핵심 · RAG hook ①

가장 중요한 개선 지점. **"LLM이 다 판단"을 걷어내고 매칭 엔진으로 대체.**

| 항목 | 내용 |
|---|---|
| **답 도출** | requirement × user skill 매칭을 **`gap_matcher`(신규)**가 결정: <br>· 1차 **정확/동의어 매칭**(taxonomy) <br>· 2차 **임베딩 cosine 유사도**(requirement 임베딩 vs skill/evidence 임베딩) → 임계값으로 `met`/`partially_met`/`not_met` 결정 <br>· `matchedEvidenceIds` = 매칭된 evidence span, `confidence` = 유사도 점수 <br>· `severity` = **룰**(required+not_met→high 등) <br>· `scoreBasis` = 카테고리별 가중 **집계 계산** <br>· **RAG hook ①** `fetch_company_context`로 기업 인재상/기술문화 근거 조각 → 판정 보정·근거 첨부 |
| **필요 툴** | **`gap_matcher`(신규, 핵심)**, `embed`, `skill_taxonomy`, **RAG `fetch_company_context`**, `nl_render` |
| **RAG** | ✅ **hook ①** — 기업 비정형 지식 보강. **판정 전 재료 공급**일 뿐, 판정 결정권은 노드가 가짐. 코퍼스에 없는 희소 회사는 어댑터 내부 웹검색 폴백으로 흡수(계약 불변) |
| **LLM 역할** | **없음(구현 결과).** 충족/미충족 판정은 물론 `reason` 문장까지 `gap_matcher`가 사실 서술로 생성한다. 더 다듬고 싶으면 `nl_render`를 붙일 수 있으나 그때도 판정은 불변 |

> **변화점(✅ 적용 완료)**: `run_structured` 하나로 해석+비교+판정을 전부 LLM에 위임하던 것을 걷어냈다. **`analyze_gap`은 이제 LLM을 호출하지 않는다.** 매칭·판정은 `gap_matcher`, reason은 매처가 사실 서술로 생성한다.
>
> **구현 노트 — '없다'와 '모른다'의 구분(가장 중요)**: 기술명도 못 뽑고 임베딩도 없으면 `not_met`이 아니라 **`uncertain`**이다. `not_met`은 "이 사람에게 없다"는 주장이고 `uncertain`은 "우리가 판정 못 한다"는 고백이다. 그리고 **`uncertain`은 `gaps`에 넣지 않는다** — gap은 '확인된 부족'이다. 모르는 걸 부족으로 세면 근거 없이 사람의 결함을 단정하게 되고, `plan_roadmap`이 그 위에 "경력 3년을 쌓으세요" 같은 무의미한 학습 계획을 세운다. `uncertain`은 `check_sufficiency`가 추가 질문으로 돌려 사용자에게 직접 묻는다.
>
> **구현 노트 — 근거 있는 보유 vs 주장만 있는 보유**: 이력서 기술스택 나열은 주장일 뿐 증명이 아니므로 `met`을 주지 않는다. 그리고 이 차이를 `reason` 문장에 **반드시 그대로 적는다**("Spring Boot는 프로젝트 근거로 확인됨 / Java는 이력서에 기재됐으나 뒷받침 경험 근거가 없음"). 둘을 뭉쳐 "확인됨"이라 쓰면 판정과 설명이 모순돼(다 확인됐다는데 왜 부분 충족인가?) 신뢰를 잃는다.

### 3.6 `plan_roadmap` — 로드맵 플래너 · [판단] · **RAG ❌ (자격증 정형 DB)**

| 항목 | 내용 |
|---|---|
| **답 도출** | ① 입력 = `analyze_gap`의 미충족 gap 목록 → ② 각 gap 스킬을 **`skill_to_cert`(신규 매핑)**로 관련 IT 자격증 조회 → ③ **`cert_db`(신규 정형 DB)**에서 자격증 메타(시험과목·난이도·`prepHours`·시험일정) 조회 → ④ 자격증이 **없는 경험형 gap**은 **`project_template_db`(프로젝트 과제 템플릿)**로 대체 → ⑤ **`roadmap_scheduler`(기존 `_refit_roadmap_to_budget` 정식화)**가 severity·`prepHours`·가용시간·기간예산·**시험일정 역산**으로 **주차 배치를 결정론적 계산** |
| **필요 툴** | **`cert_db`(신규 정형 DB)**, **`skill_to_cert`(신규 매핑)**, **`project_template_db`(신규)**, **`roadmap_scheduler`(정식화)**, `nl_render` |
| **RAG** | ❌ **RAG 안 씀.** 학습자료는 강의(무한·휘발성)가 아니라 **IT 자격증(유한·안정·정형)**을 소스로 삼아 정형 DB로 해결 |
| **LLM 역할** | **없음(구현 결과).** `goal`/`tasks`/`doneCriteria` 문구까지 정형 DB의 값을 그대로 쓴다 — 자격증 시험과목이 곧 `tasks`, "최종 합격"이 곧 `doneCriteria`라 지어낼 게 없다. **항목·기간·순서·시간은 알고리즘이 결정** |

> **변화점 1(✅ 적용 완료)**: 로드맵 100% LLM 생성("invented roadmap")을 제거했다. **`plan_roadmap`은 이제 LLM을 호출하지 않는다.** 항목은 `cert_db`/`project_template_db`에서 꺼내고, 순서·기간·시간은 `roadmap_scheduler`가 계산한다. 문구도 정형 DB의 값을 그대로 쓴다(자격증 시험과목이 곧 `tasks`, "최종 합격"이 곧 `doneCriteria`).
>
> **구현 노트 — `examDates`는 비워 뒀다**: 시험 일정은 해마다 바뀌어서 코드에 박으면 반드시 낡는다. 비어 있으면 스케줄러가 일정 역산을 건너뛰고 `prepHours` 기반 순차 배치로 폴백한다(없는 날짜를 지어내지 않는다). 대신 `examWindowsPerYear`/`alwaysAvailable`로 시험 압박 정도만 표현한다.
>
> **구현 노트 — `prepHours`는 표준 추정치다**: 개인 배경에 따라 크게 다르므로 정밀한 값이 아니라 '규모 감각'이다. 스케줄러도 상대적 비교에만 쓴다.
>
> **변화점 2 (hook ③ 폐기 이유)**: 원래 학습자료를 RAG(`learning_resource_search`)로 보강하려 했으나, 강의·아티클은 **최신성이 핵심 가치라 벡터 DB 스냅샷과 상충**하고 재색인 유지보수 부담이 크다. IT 자격증은 정반대로 **개수 유한·시험범위 안정·완전 정형·스킬 매핑 명확**이라 RAG/웹검색 없이 **정형 DB 조회 한 방**으로 끝난다. 덤으로 `doneCriteria`가 "자격증 취득"으로 **진짜 측정 가능**해지고, `prepHours`가 실측이라 예산 재적합이 정확하며, 시험일정으로 **역산 배치**까지 가능하다. IT 솔루션 도메인으로 스코프를 좁혔기에 성립하는 설계다.
>
> **커버리지 한계**: 자격증이 없는 gap("이벤트 드리븐 아키텍처 설계 경험", "MSA 운영")은 `project_template_db`의 프로젝트 과제로 보완한다 — 자격증은 만능이 아니다.

### 3.7 `find_alternatives` — 대체 경로 · [판단] ★ RAG hook ②

| 항목 | 내용 |
|---|---|
| **답 도출** | **징검다리 하위 직업군을 거치는 경로 탐색.** ① gap 차이 판정: 사용자 강점 vs 목표 공고 gap 이 임계값 이상 벌어지면 대체 경로 트리거(기존 `route_after_roadmap` 조건) → ② 목표 직업군 확인(`roleCategory`) → ③ **`career_graph`(신규 DB)**로 그 직업군에 도달 가능한 **하위/징검다리 직업군** 도출(예: senior backend ← junior backend ← 백엔드 인턴/SI) → ④ 하위 직업군들로 쿼리 조립(`_build_alternative_query` 확장) → ⑤ **RAG hook ②** `search`로 **실존 공고 검색(내부 코퍼스 벡터 비교 → 부족 시 웹검색 폴백)** → ⑥ 각 후보 공고 요구사항 vs 사용자 강점을 **`gap_matcher` 재사용**해 `reducedGaps`/`matchedStrengths` **계산**, `confidence`=유사도 |
| **필요 툴** | **RAG `search`(벡터+웹검색 폴백)**, **`career_graph`(신규)**, `gap_matcher`(재사용), `embed`, `nl_render` |
| **RAG** | ✅ **hook ②** — 공고 코퍼스(필수, 내부 벡터→웹검색 폴백). 목표→하위 직업군 도출(`career_graph`)은 내부 DB로 RAG 앞단에서 수행 |
| **LLM 역할** | **없음(구현 결과).** `reason`도 계산 결과("보유 역량 N개를 살릴 수 있고 부족했던 M개를 요구하지 않음")를 서술한다. **공고는 지어내지 않고 RAG 결과만 사용** |

> **변화점(✅ 적용 완료)**: "LLM이 추측으로 대체경로 생성"을 제거했다. **`find_alternatives`는 이제 LLM을 호출하지 않는다.** 경로 설계는 `career_graph`, 실공고는 RAG(`search`), 매칭은 `gap_matcher` 재사용.
>
> **구현 노트 — RAG 미연결 시 폴백**: 실공고 후보가 없으면 `career_graph`의 경로 '유형'만 낸다. 회사명은 빈 문자열, `sourceJobPostingId`는 null, **`reducedGaps`도 비운다** — 실제 공고 없이는 "이 자리에선 뭐가 덜 필요한지"를 알 수 없고, 추측해서 채우면 그게 바로 이 노드가 피하려던 허구다. `confidence`도 0으로 둔다(실공고 근거가 없으므로 신뢰도를 주장하지 않는다).
>
> **구현 노트 — 연차 미상이면 하위 연차 경로를 내지 않는다**: `career_graph`가 연차를 'mid'로 가정하던 폴백을 제거했다. 근거 없이 "인턴/주니어 자리를 노려라"는 경로를 지어내게 되기 때문이다. 연차가 없으면 징검다리 직군(연차 무관)만 낸다.
>
> **역할 분담(중요)**: 오케스트레이터가 ①~④(gap 판정 → 목표 직업군 → 하위 직업군 → 쿼리)까지 풀어 `query`에 담아 넘긴다. RAG 담당은 ⑤(벡터 검색 → 부족 시 웹검색 폴백)만 `search()` 내부에서 구현. 상세 흐름은 [rag-team-interface-spec.md §3](./rag-team-interface-spec.md) "대체 경로 검색 흐름" 참조.

### 3.8 `verify_result` — 검증기 · [판단]

"LLM이 LLM 결과를 검증"하는 신뢰도 문제를 **룰 검증으로 전환.**

| 항목 | 내용 |
|---|---|
| **답 도출** | ① 스키마 = **pydantic 검증**(룰) → ② 금지표현 = **사전/정규식 매칭**(룰) → ③ 근거성(`no_evidence`) = 각 판정이 실재 `evidenceId`/`source`를 참조하는지 **대조**(참조 무결성) → ④ 정합성(`inconsistent`) = gap과 roadmap의 `requirementId` **교차 검증** → ⑤ `retrySignal` = 룰 결과 집계 |
| **필요 툴** | `schema_validator`, `forbidden_lexicon`, `evidence_grounding_check`, `consistency_check` (전부 룰) |
| **RAG** | ❌ (단, ③에서 기존 `sources` 대조에 사용) |
| **LLM 역할** | **없음 권장.** 애매한 표현 판정 보조만 예외적으로. 사용자 대면 문장 없음 |

### 3.9 `assemble_output` — 조립 · [말하기]

| 항목 | 내용 |
|---|---|
| **답 도출** | 구조 조립은 **룰**(AnalyzeResponse 형태). 여기서 **최종 `nl_render`(LLM)**가 전체 결과를 사람이 말하듯 요약·서술 |
| **필요 툴** | `nl_render`(LLM) |
| **RAG** | ❌ |
| **LLM 역할** | **여기가 LLM '말하기'의 본진.** 앞 노드가 확정한 사실만 자연어로 표현, 새 사실·수치 생성 금지 |

---

## 4. 툴 카탈로그 (구현 대상 총정리)

| 툴 | 계층 | 유형 | 상태 | 파일 | 쓰는 노드 |
|---|---|---|---|---|---|
| `extract_text` | 읽기 | 비LLM | ✅ | `extract.py` | parse, profile |
| `rule_extractor` | 읽기 | 비LLM(정규식/키워드) | ✅ | `rule_extractor.py` | parse |
| `run_structured` | 읽기 | LLM(읽기전용, 잔여 비정형만) | ✅ 용도 제한 완료 | `structured.py` | parse, profile |
| `skill_taxonomy` | 읽기/판단 | 내부 DB+동의어+함의 | ✅ | `skill_taxonomy.py` | parse, profile, gap, roadmap |
| `role_taxonomy` | 읽기 | 내부 DB+룰 | ✅ | `role_taxonomy.py` | parse, career_graph |
| `embed` | 판단 | 임베딩 어댑터 | 🔌 계약만, **미연결** | `embed.py` | gap |
| `gap_matcher` | 판단 | 룰+임베딩 엔진 | ✅ **(핵심)** | `gap_matcher.py` | gap, sufficiency, alternatives |
| `sufficiency_rules` | 판단 | 룰 | ✅ | `sufficiency_rules.py` | check_sufficiency, ask_user |
| `cert_db` | 판단 | 내부 정형 DB | ✅ | `cert_db.py` | roadmap |
| `skill_to_cert` | 판단 | 내부 매핑 | ✅ | `skill_to_cert.py` | roadmap |
| `project_template_db` | 판단 | 내부 DB | ✅ | `project_template_db.py` | roadmap |
| `roadmap_scheduler` | 판단 | 결정론 계산 | ✅ 정식화 완료 | `roadmap_scheduler.py` | roadmap |
| `career_graph` | 판단 | 내부 그래프 DB | ✅ | `career_graph.py` | alternatives |
| `verify_rules`(4종) | 판단 | 룰 | ✅ | `verify_rules.py` | verify |
| RAG `fetch_company_context` | 판단 | RAG(+웹검색 폴백) | 🔌 hook 있음, **미연결** | `rag.py` | gap |
| RAG `search` | 판단 | RAG | 🔌 hook 있음, **미연결** | `rag.py` | alternatives |
| `nl_render` | 말하기 | LLM(표현전용) | ✅ | `nl_render.py` | assemble |

> `nl_render` 는 현재 `assemble_output` 에서만 쓴다. 중간 노드(gap/roadmap/alt)의 문장은
> 각 툴이 사실 서술로 이미 만들고 있어(예: gap_matcher 의 `reason`) 다듬기 단계를 아직
> 붙이지 않았다. 필요해지면 같은 렌더러를 호출하면 된다 — 계약은 열려 있다.

### 4.1 노드별 LLM 호출 현황 (§0 3계층 준수 검증)

| 노드 | 계층 | LLM 호출 |
|---|---|---|
| `parse_job_posting` | 읽기 | ✅ (잔여 비정형 추출) |
| `build_user_profile` | 읽기 | ✅ (항목 추출) |
| `check_sufficiency` | 판단 | ❌ |
| `ask_user` | 말하기 | ❌ (질문 템플릿) |
| `analyze_gap` | 판단 | ❌ |
| `plan_roadmap` | 판단 | ❌ |
| `find_alternatives` | 판단 | ❌ |
| `verify_result` | 판단 | ❌ |
| `assemble_output` | 말하기 | ✅ (`nl_render`) |

**LLM 호출이 입구(읽기) 2개와 출구(말하기) 1개에만 남았다. 판단 5개 노드는 전부 데이터가 돌린다.**
이 표는 회귀 감시용이다 — 판단 노드에 `run_structured` 가 새로 생기면 설계 위반이다.

### 4.2 테스트

`tests/` 133건. **LLM 을 호출하지 않는다** — `conftest.py` 가 `get_llm` 을 미설정으로 강제하므로
결정적·고속(1초 미만)이고 CI 에서 그대로 돌릴 수 있다. 판단 계층이 전부 룰이라 가능한 구조다.

    python -m pytest tests -q

| 파일 | 무엇을 지키나 |
|---|---|
| `test_gap_matcher.py` | 판정 엔진 계약 — met/partially_met/not_met/uncertain 구분, severity 룰, scoreBasis |
| `test_taxonomy.py` | 표준화·검색 경계·`implies` 함의 관계, career_graph 어휘 정합성 |
| `test_rule_extractor.py` | **실제 페르소나 공고**(`tests/docs/user1·user2`)로 섹션 분리·기술스택·연차 추출 |
| `test_sufficiency_rules.py` | "정보가 충분한가" vs "사람이 충분한가" 경계선 |
| `test_roadmap_tools.py` | cert_db·skill_to_cert·project_template_db 선택 규칙 |
| `test_nl_render.py` | 말하기 계층의 정책 게이트·폴백 |
| `test_verify_result.py` | 검증 룰 4종 |
| `test_career_graph.py`, `test_extract.py`, `test_graph_smoke.py`, `test_retry_loop.py`, `test_eval_metrics.py` | 기존 |

**§5 의 결정들은 전부 테스트로 못 박혀 있다.** 되돌리면 테스트가 깨진다 —
예컨대 `uncertain` 을 `not_met` 으로 바꾸면 5건이, `Spring Boot → Java` 함의를 넣으면 1건이 실패한다
(변이 주입으로 확인함). 임계값(`_MET_EVIDENCE_RATIO`, `_MIN_EVIDENCE_COUNT`)을 조정할 때는
테스트가 왜 깨지는지 먼저 읽을 것.

> **손으로 만든 샘플만 쓰지 말 것.** `■ 자격 요건 (필수)` 같은 실제 공고의 헤더 장식은
> 페르소나 파일로 돌려 보고서야 드러났다. 새 추출 규칙을 넣으면 `tests/docs` 로 검증한다.

### 4.3 남은 작업

1. **`embed` 연결 (최우선)** — 가장 큰 기능적 공백. 미연결이라 2차 매칭이 안 돌아서 서술형 요구사항
   ("경력 3년 이상", "이벤트 드리븐 설계 경험")이 전부 `uncertain` 으로 남는다.
   `EMBED_PROVIDER` 환경변수 + `get_embedder()` 분기 한 줄이면 붙는다.
2. **RAG hook ① `fetch_company_context`** — RAG 팀. 계약 준비 완료.
3. **RAG hook ② `search`** — RAG 팀. 붙으면 `find_alternatives` 가 경로 '유형' 대신
   실존 공고를 낸다(코드 경로는 이미 구현돼 있고 후보가 없어서 폴백 중일 뿐).
4. **시드 데이터 확장** — `skill_taxonomy`·`cert_db`·`project_template_db`·`career_graph` 는
   대표 항목만 담은 스캐폴딩이다. 커버리지가 곧 품질이다.
5. **중간 노드 `nl_render` 적용** — gap/roadmap/alt 의 사실 서술 문장을 더 다듬고 싶을 때.
   지금도 읽을 만해서 급하지 않다.

---

## 5. 구현하며 내린 결정 (설계서에 없던 것)

구현 중 실제 데이터로 돌려 보고 나서야 드러난 문제들과, 그에 대한 결정. **되돌리기 전에 여기를 읽을 것** — 대부분 "그냥 이렇게 하면 편한데?" 하고 되돌리기 쉬운 것들인데, 되돌리면 원래 문제가 그대로 돌아온다.

### 5.1 `skill_taxonomy.implies` — 함의 관계 (신규 개념)

`aliases`(같은 것의 다른 이름)만으로는 부족했다. "MySQL 등 RDBMS 설계 및 SQL 활용 능력" 요구사항에서 `RDBMS`·`SQL`이 MySQL과 **별개 스킬로 잡혀**, MySQL 경험자가 각각을 따로 증명하지 못해 미충족으로 찍혔다. 그리고 `plan_roadmap`이 "SQL 자격증"을 따로 찾았다.

→ `implies`를 추가했다: `MySQL → (RDBMS, SQL)`. 근거 문장 "MySQL 인덱스 튜닝"이 RDBMS·SQL의 근거로도 인정된다.

**주의**: `aliases`와 혼동하면 안 된다. 그리고 **엄격히 수반되는 것만** 넣어야 한다. 예를 들어 `Spring Boot → Java`는 **넣지 않았다** — Spring Boot는 Kotlin으로도 쓴다. 애매하면 안 넣는 쪽이 안전하다.

### 5.2 `embed.similarity()` 는 `None`을 돌려준다 (`0.0`이 아니라)

미연결 상태에서 `0.0`을 돌려주면 "안 닮았다"는 **적극적 판정**이 되어 `gap_matcher`가 미충족으로 오판한다. `None`은 "모른다"라서 매처가 2차 매칭을 건너뛰고 1차 룰 결과만 쓴다. 이 구분 덕에 임베딩 없이도 매처가 **틀린 판정을 내지 않는다**(재현율만 낮아진다).

### 5.3 `sufficiency_rules`: 차단하는 결핍 vs 있으면 좋은 질문

이 노드가 묻는 건 **"분석할 정보가 충분한가"**이지 **"이 사람이 충분한가"**가 아니다. 섞으면 역량이 부족한 사용자에게 질문을 퍼붓는 무례한 제품이 된다.

처음엔 "근거 없는 스킬 주장"도 부족 판정에 넣었더니, **근거 3건이 탄탄한 이력서가 Java 하나 때문에 분석을 못 받고 되물림당했다.** → `MissingInfo.blocking`으로 나눴다. 분석 자체가 불가능한 결핍(근거 없음·판정 불가)만 차단하고, 나머지는 어차피 멈춰서 물을 때만 곁들인다. 근거 없는 스킬은 갭 분석의 `reason`이 이미 알려주므로 되묻는 건 중복이다.

수반 스킬도 묻지 않는다 — "MySQL 경험 알려주세요"와 "SQL 경험 알려주세요"를 따로 물으면 같은 걸 두 번 묻는 꼴이다.

### 5.4 LLM 자리표시자 정리

LLM이 "값 없음"을 빈 문자열이 아니라 `<UNKNOWN>`, `N/A`, `미상` 같은 **자리표시자 문자열로 채운다.** 실제로 회사명 미상 공고에서 `companyName: "<UNKNOWN>"`이 나왔고, 그대로 두면 `fetch_company_context("<UNKNOWN>")`으로 RAG를 호출한다. → `_clean_field`로 빈 문자열화하고, 회사명이 없으면 **RAG를 아예 호출하지 않는다**(무의미한 쿼리 + 오염 방지).

### 5.5 `project_template_db`: 관련성이 비용보다 우선

과제를 소요 시간으로만 고르면, "MSA 부족"에 5시간 짧다는 이유로 MSA 전용 과제 대신 '이벤트 드리븐 전환' 과제가 뽑힌다. 더 싸지만 겨냥이 빗나간 처방이다. → 정렬 기준을 (주 대상 여부 → 과제의 좁힘 정도 → 난이도 → 시간) 순으로 잡았다.

### 5.6 `nl_render` 출력도 검증을 통과해야 한다

말하기 계층이라고 면제가 아니다. LLM 요약을 `verify_rules`의 금지 표현 검사에 통과시키고, 걸리면 **계산된 사실로 만든 결정론 요약으로 대체**한다. 요약은 결과의 얼굴이라 비어 있으면 제품이 고장 난 것처럼 보이므로, LLM이 없거나 실패해도 빈 문자열은 내지 않는다.

### 5.7 계약 변경

- `NormalizedUserProfile.skillEvidence` (내부): 표준 스킬명 → evidenceId 목록. **룰로 만든다.** LLM에게 "이 근거가 이 스킬을 증명한다"고 주장하게 두면 환각 근거가 섞이는데, 룰로 만들면 **존재하지 않는 근거 인용이 구조적으로 불가능**해진다.
- `Gap.missingSkills` (내부): `gap_matcher`가 계산. `plan_roadmap`의 `skill_to_cert` 입력.
- `GraphState.sufficiency` (내부): `check_sufficiency` 판정 → `route_sufficiency`가 읽는다.
- **`AnalyzeResponse.summary` (백엔드 계약)**: `nl_render` 산출 요약. 기본값 `""`인 **추가** 필드라 기존 소비자는 무시해도 된다.

### 5.8 `role_taxonomy`가 직무 어휘의 단일 소유자

`career_graph`가 role 별칭·연차 사다리를 자체 보유하고 있어 사전이 두 벌이었다. 갈라지면 "backend"와 "web-backend"가 서로 다른 직군이 되는 사고가 난다. → 어휘는 `role_taxonomy`가 소유하고, `career_graph`는 그 위에 **전이 관계(feeders)만** 얹는다.

### 5.9 `evidenceMap` — "주장"과 "증명"을 분리하는 근거 체인 (+ 환각 원문 대조)

`evidenceMap`은 독립된 툴이 아니라 `NormalizedUserProfile`의 필드다. 다만 이 프로젝트에서
가장 많은 노드가 순서대로 거쳐 가는 데이터라 별도로 정리해 둔다.

**무엇인가**: `{evidenceId, source, text}` 리스트. `text`는 이력서 원문에 실제로 있는
성과/경험 문장을 LLM 이 그대로 옮겨 담은 것이다 — 요약·윤색 금지가 원칙이다(§3.2).

**왜 필요한가**: 이력서의 "기술스택 나열"은 주장일 뿐 증명이 아니다(§3.5 구현 노트).
`evidenceMap` 은 그 증명을 담는 자리이고, 이게 있어야 `gap_matcher` 가 "근거 있는 보유"와
"주장만 있는 보유"를 구분할 수 있다.

**전체 수명주기** (`build_user_profile` 내부, `graph/nodes.py`):

1. **생성 (LLM)** — `_PROFILE_BUILDER_SYSTEM` 프롬프트가 채운다. 이 시점 데이터는 신뢰하지
   않는다(id 중복 가능, 원문 대조 안 됨).
2. **환각 원문 대조 (룰, 신규 — `_filter_grounded_evidence`)** — `evidence.text` 를 공백
   정규화한 뒤 원문(`resume_text`)에 실제로 있는 부분 문자열인지 대조한다. 없으면 제거하고
   `hallucinated_evidence` warning 을 남긴다. **완전 문자열 대조이지 퍼지 매칭이 아니다** —
   프롬프트가 "그대로 인용하라"고 명시했으므로 사소한 표기 차이까지 봐줄 이유가 없다.
   이 단계가 없으면 LLM 이 그럴듯하지만 원문에 없는 문장을 지어내도 걸러낼 방법이 없었다.
   `verify_result.check_evidence_grounding` 이 `matchedEvidenceIds` 의 **참조 무결성**(그
   id 가 evidenceMap 에 실재하는가)을 검증하는 것과 같은 이유로, 이 단계는 그보다 한 걸음
   앞선 지점 — **문장 자체가 원문에 실재하는가** — 를 막는다.
3. **id 재부여 (룰)** — 남은 문장들의 `evidenceId` 를 `ev-1, ev-2...` 순서로 재할당한다.
   LLM 이 낸 id 는 신뢰하지 않는다(§5 도입부 원칙과 동일).
4. **skillEvidence 구축 (룰)** — 각 문장을 `skill_taxonomy.find_in_text` + `with_implied`
   로 스캔해 "스킬명 → evidenceId 목록" 표를 만든다. LLM 에게 "이 근거가 이 스킬을
   증명한다"고 주장하게 두지 않는다(§3.2-④).
5. **소비 A — `gap_matcher`**: 요구 기술이 `skillEvidence` 에 있으면 `met`/`partially_met`
   판정 + `matchedEvidenceIds` 에 인용(§3.5).
6. **소비 B — `check_sufficiency`**: `len(evidenceMap)` 을 근거 개수 지표로 써서 "정보
   충분성"을 판단한다(§3.3).
7. **소비 C — `verify_result`**: `matchedEvidenceIds` 가 실제 `evidenceMap` 에 있는 id 를
   가리키는지 최종 재확인한다(§3.8). 여기서 걸리는 게 거의 없는 이유는 2번 단계가 이미
   앞에서 막아 두기 때문이다.

**예시**: "MySQL 인덱스 튜닝과 Redis 캐싱으로 응답시간을 780ms→210ms 로 줄였다"라는 문장
하나가 → `skillEvidence` 에 `{"MySQL": [ev-2], "RDBMS": [ev-2], "SQL": [ev-2], "Redis": [ev-2]}`
로 확장되고(MySQL→RDBMS/SQL 함의, §5.1), 공고 요구사항 "MySQL 등 RDBMS 설계 및 SQL 활용"이
이력서에 "RDBMS"라는 단어가 한 번도 없어도 `met` 으로 판정된다.

**핵심 원칙**: LLM 이 손대는 건 1번(문장 생성)뿐이다. 2~7번은 전부 룰/결정론이라, 문장
하나가 최종 판정까지 가는 동안 "지어낼 기회"가 구조적으로 차단돼 있다.

---

## 6. 한 줄 요약

- **RAG(벡터 검색)는 2곳뿐**: 갭 분석(기업 지식, +희소회사 웹검색 폴백)·대체 경로(공고 코퍼스). 로드맵은 **RAG 아님 → 자격증 정형 DB(`cert_db`)**. 나머지는 내부 DB/룰/임베딩/계산.
- **RAG를 안 쓰는 판단 기준**: 대상이 *비정형·의미유사검색 필요·자체 데이터 축적*이면 RAG(공고). *유한·안정·정형*이면 정형 DB(자격증). *최신·희소*면 웹검색(희소 기업).
- **판단은 전부 알고리즘**: `gap_matcher`·`taxonomy`·`roadmap_scheduler`·`career_graph`·`verify_rules`.
- **LLM은 입구(읽기)와 출구(말하기)에만.** 몸통(충족·심각도·추천·검증 판정)은 데이터가 돌린다.
- **판단은 데이터가 하고, LLM은 말만 한다.**
