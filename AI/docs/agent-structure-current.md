# 에이전트 현재 구조 분석 (agent-structure-current)

> **지금 코드(`src/jobis_ai`) 기준의 구조 스냅샷 정본.** 여기까지 어떻게 왔는지의 역사는
> [`agent-structure-evolution.md`](./agent-structure-evolution.md), 실측 문제·해결 기록은
> [`troubleshooting.md`](./troubleshooting.md) 참조.
>
> 이 문서는 다음 옛 문서들의 "현재 상태" 내용을 통합했다(원본 삭제됨). 코드 docstring 이
> 옛 문서명을 참조하면 이 표로 찾아온다:
>
> | 옛 문서 | 내용이 간 곳 |
> |---|---|
> | `agent-derivation-and-tools.md` | 이 문서 §3~§5 (판정 엔진·툴·신뢰성 장치) |
> | `agent_develop.md` | 이 문서 §1 (3계층) + evolution ④ |
> | `agent_orchestration_improvement.md` | 이 문서 §2 (오케스트레이터·로스터) + evolution ⑤ |
> | `agent_latency_analysis.md` | 이 문서 §6 (성능) |
> | `0720에이전트구조정리.md` | 이 문서 §3.2 (프로필 빌더) |

---

## 1. 전체 3계층 구조

하나의 거대한 AI가 아니라, **신뢰성 계약이 다른 세 계층의 분업**이다.

```text
사용자 ↔ 자연어 대화 (POST /api/v1/chat)
              │
┌─────────────▼──────────────────────────────────────────┐
│  ① 대화 오케스트레이터  (orchestrator/)                     │
│     agent_planner[LLM 자율 판단] → validate_plan[결정론 검증] │
│     (LLM 불가 시 대화형 에이전트가 턴을 받는다 — 대응표 없음)     │
│     스스로 판단하지 않는다 — 선택·검증·조합·호출만 한다            │
└──┬──────┬──────┬──────┬──────┬──────┬───────────────────┘
   ▼      ▼      ▼      ▼      ▼      ▼      (agents/ 6종)
 적합도   공고    이력서   자소서   로드맵   면접
 분석     추천    진단     초안     관리     준비
   │
   ▼
│  ② 판정 엔진  (graph/ 10노드, 결정론)                        │
│  parse → profile → completeness → sufficiency → gap        │
│  → roadmap → (alternatives) → verify → assemble            │
   │
   ▼
│  ③ 행동/생성 산출물 + 인간 게이트                             │
│  초안까지만 — 최종 확정(제출)은 사용자. 제출 툴 자체가 없다      │
```

| 계층 | 신뢰성을 무엇으로 버나 | LLM |
|---|---|---|
| ① 오케스트레이터 | 추론은 자율, **행동 집합과 상태 전이는 하네스가 좁힌다**(등록된 에이전트만·전제 확인·가시화) | 에이전트 선택만(판단 필드 없음) |
| ② 판정 엔진 | 틀리지 않음(결정론·회귀 테스트) | 입구(읽기)·출구(말하기)만 |
| ③ 행동/생성 | 제출 전 사람이 본다 | 근거제한 생성만 |

**한 줄**: **추론은 자율에 맡기고, 행동과 상태 전이는 하네스로 좁힌다.**
① 그라운딩 — 판단의 입력을 강제한다(세션 자산·최근 대화·실행 가능 여부·검색/툴 결과·인용).
② 액션 스페이스 제한 — 추론은 자유롭게, 실행 가능한 행동 집합은 좁게(레지스트리 등록 에이전트만).
③ 검증 — 자율 판단의 출력을 사후에 확인한다(스키마·전제 검사·금지표현·근거 대조).

---

## 2. 대화 오케스트레이터 (`orchestrator/`)

| 부품 | 파일 | 성격 | 하는 일 |
|---|---|---|---|
| 플래너 | `planner.py` | LLM | 발화 + 자산 상태 + 에이전트 목록(레지스트리에서 동적 생성) → 호출할 에이전트를 직접 선택. 선택지는 스키마(Literal)로 제한 — 미등록 에이전트 호출(환각)이 구조적으로 불가능. 판단 필드 없음 |
| 검증기 | `router.py::validate_plan` | 결정론 | 선택 시퀀스의 전제조건 검사 + 전제 에이전트 자동 삽입(`produces` 기반) + 실행 불가 제거. **무엇으로 대신할지는 정하지 않는다** — 남는 것이 없으면 대화형 에이전트가 턴을 받는다. 순수 함수라 전수 테스트 가능 |
| 실행 가능 판정 | `router.py::agent_feasibility` | 결정론 | 지금 상태에서 각 에이전트가 실행 가능한지(불가면 결측 자산). **플래너 프롬프트의 그라운딩 입력** — 플래너가 상태를 알고 고르므로 "이 상황이면 저 에이전트" 대체 규칙이 코드에 없다 |
| 세션 저장소 | `session.py` | 결정론 | 이력서·공고·분석 결과를 세션별 누적(키 격리). 검증기의 전제조건 조회처 |
| 대화 진입 | `chat.py` | — | `/api/v1/chat` 흐름 조립 — 플래너 우선, 실패 시 폴백 |

**신뢰성 3규칙**: ① LLM은 선택만 한다(판단 필드 없는 스키마) ② 실행 가능 여부·순서 보정은
결정론 검증기가 확정 ③ 선택을 가시화하고(플래너의 ack — 금지표현 검증 통과분만), 확신이 낮거나
실행할 것이 없으면 **고정 문구로 끝내지 않고** 대화형 에이전트가 사용자의 말에 답하며 필요한
자료를 요청한다.

**대응표를 두지 않는 이유**: (발화 × 자산) 표는 문장 하나만 달라져도 무너지고, 에이전트가
늘어날 때마다 표가 곱으로 커진다. 무엇을 할지는 발화·상태·대화 이력을 함께 본 플래너가 매 턴
새로 정하고, 코드는 그 선택이 **지금 실행 가능한지만** 확인한다. LLM 이 없으면 흐름을 대신
정하는 대신 대화형 에이전트가 턴을 받는다(2026-07-27 `intent.py`·`route()` 제거).

**측정(2026-07-29 재측정, `evals/planner_dataset.json` 46케이스 × 3회)**: 시퀀스 정확도 **0.93**,
되묻기 **1.00**, **안정성 0.98**. 07-24 의 "41/41 100%" 는 1회 측정이고 그 뒤 프롬프트가 바뀌어
**폐기**한다. 최초 재측정은 0.67 이었고, 원인을 프롬프트 과잉 적용(5건)·데이터셋 낡음(6건)·
flaky(3건)로 갈라 앞의 둘을 고쳐 0.93 이 됐다. 남은 stable-wrong 2건은 의도적으로 열어 둔 것.
상세: `docs/eval-records/2026-07-29_planner-reproducibility.md`.
(폴백 대응표 측정치 78.0%/82.9% 는 2026-07-27 대응표 제거와 함께 폐기 — 흐름을 표로 정하지
않기로 했으므로 비교 대상이 아니다.)

**모든 호출은 오케스트레이터가 한다** — 에이전트끼리는 서로 모르고, 호출 경로는 항상 추적 가능하다.

### 전담 에이전트 6종 (`agents/`)

| 에이전트 | 파일 | 입력 → 산출 | 본체(재사용 자산) | 성격 |
|---|---|---|---|---|
| 적합도 분석 | `fit_analysis.py` | 이력서+공고 → 등급(상/중/하)+근거 | 기존 판정 그래프 전체 | 결정론 |
| 공고 추천 | `job_recommend.py` | 이력서 → 맞춤 공고 목록 | `find_alternatives` 독립화+RAG | 결정론+검색 |
| 이력서 진단 | `resume_diagnosis.py` | 이력서 → 강점·보완점 리포트 | 프로필 빌더+completeness | 결정론+생성 |
| 자소서 초안 | `coverletter_draft.py` | 이력서+공고+분석결과 → 초안 | evidenceMap 근거제한+verify | 생성(게이트 필수) |
| 로드맵 관리 | `roadmap_manager.py` | 분석결과(로드맵) → 일정·진척 | `plan_roadmap`+scheduler | 결정론+지속성 |
| 면접 준비 | `interview_prep.py` | 분석결과(갭·강점) → 예상 질문·답변 포인트 | 신규 생성+verify | 생성 |

로스터 원칙: **판정 결과가 상류, 생성이 하류.** 자소서·로드맵·면접은 전부 적합도 분석 산출물의
소비자이며 판정을 다시 하지 않는다.

---

## 3. 판정 엔진 (`graph/` 10노드)

모든 노드는 읽기/판단/말하기 중 하나다. **판단 노드는 LLM을 쓰지 않는다**
(유일한 의도적 예외: `semantic_judge` — 아래 §3.5).

| 노드 | 계층 | 답을 정하는 것 | LLM |
|---|---|---|---|
| `parse_job_posting` | 읽기 | 정규식(`rule_extractor`) 1차 → 잔여 비정형만 LLM → `skill/role_taxonomy` 표준화 | ✅ 잔여 추출만 |
| `build_user_profile` | 읽기 | LLM 항목 추출 → 환각 원문 대조 → id 재부여 → skillEvidence 룰 구축 | ✅ 추출만 |
| `check_profile_completeness` | 판단 | 순수 룰(결측 enum → 비블로킹 객관식 질문) | ❌ |
| `check_sufficiency` | 판단 | 순수 룰(분석 가능 여부 게이트, blocking 결핍만 차단) | ❌ |
| `ask_user` | 말하기 | 질문 템플릿(무엇을 물을지는 룰) | ❌ |
| `analyze_gap` | 판단 | **`gap_matcher`** (§3.5) | ❌* |
| `plan_roadmap` | 판단 | `cert_db`+`skill_to_cert`+`project_template_db`+`roadmap_scheduler` 계산 | ❌ |
| `find_alternatives` | 판단 | `career_graph` 징검다리 → RAG `search` 실존 공고 → `gap_matcher` 재사용 | ❌ |
| `verify_result` | 판단 | 룰 4종(스키마·금지표현·근거 무결성·정합성) → 실패 시 재분석 신호 | ❌ |
| `assemble_output` | 말하기 | 구조 조립은 룰, 최종 요약만 `nl_render`(LLM). 요약도 verify 통과 필수, 실패 시 결정론 요약 폴백 | ✅ 표현만 |

\* `gap_matcher` 내부의 LLM 의미판정(이진)은 의도적 예외 — §3.5.

### 3.5 스코어링 알고리즘 (핵심, `gap_matcher.py`)

**매칭 — 4단 캐스케이드** (정량은 룰, 정성만 LLM):

1. **정확/동의어 매칭(룰)** — `skill_taxonomy`로 표기 정규화(ReactJS/리액트→React) 후
   skillEvidence 대조. 함의 관계 `implies`(MySQL→RDBMS·SQL) 반영. 요구 기술의 80% 이상
   충족이면 met(4개 중 3개 증명을 미충족으로 찍는 건 과하다).
2. **LLM 의미판정(의도적 예외)** — 기술명이 안 뽑히는 서술형 요구만. **이력서 근거 문장
   안에서만, 관련 있냐 없냐 이진 판정만**(점수·등급 불가). N건을 1콜로 배치 + 캐시.
   (원래 임베딩 유사도였으나 실측 신뢰 불가로 교체 — troubleshooting 07-20.)
3. **도메인 키워드(룰→LLM 폴백)** — 포함 매칭 먼저, 실패 시 2번과 같은 의미판정.
4. **연차 사다리(룰)** — 관련 직군 경력만 개월 합산(`experience_estimator`) →
   intern~lead 사다리 위치 비교. 한 칸 아래면 partially_met.

**점수화 — 가중 평균 → 임계값 등급**:

- 상태 점수: met 1.0 / partially_met 0.5 / not_met 0.0. **uncertain 은 분모 제외.**
- 요구 종류 가중: required 1.0 / preferred 0.5.
- 카테고리 가중: techSkill 0.35 · projectExperience 0.25 · roleRelevance 0.15 ·
  domainFit 0.15 · certLanguage 0.10 — **계산된 카테고리만** 가중 평균(억지 숫자 금지,
  하나도 없으면 "판정불가").
- 등급 경계: **상 ≥ 0.7 / 중 ≥ 0.4 / 하 < 0.4.**

**가장 중요한 규칙 — 모른다 ≠ 아니다**: 판정 불가는 `uncertain`이며 gap 에 넣지 않고
`check_sufficiency`가 되묻기로 돌린다. 모든 판정에는 method(어떻게 판정했나)와 reason
(근거 문장, "근거로 확인됨/기재만 됨" 구분)이 남아 **점수 뒤 근거가 전부 추적된다.**

---

## 4. 툴 카탈로그 (요약)

| 툴 | 유형 | 상태 | 쓰는 곳 |
|---|---|---|---|
| `extract_text` / `rule_extractor` / `run_structured` | 비LLM / 정규식 / LLM(읽기 전용) | ✅ | parse, profile |
| `skill_taxonomy` / `role_taxonomy` | 내부 DB+룰 | ✅ (시드, 확장 필요) | parse, profile, gap |
| `gap_matcher` + `semantic_judge` | 룰+LLM 이진판정 | ✅ 핵심 | gap, sufficiency, alternatives |
| `sufficiency_rules` / `verify_rules`(4종) | 룰 | ✅ | sufficiency, verify |
| `cert_db` / `skill_to_cert` / `project_template_db` / `roadmap_scheduler` | 정형 DB+계산 | ✅ (시드) | roadmap |
| `career_graph` | 내부 그래프 DB | ✅ | alternatives |
| `experience_estimator` | 룰 | ✅ | gap(연차) |
| `nl_render` | LLM(표현 전용) | ✅ | assemble |
| RAG `fetch_company_context` / `search` | RAG 어댑터 | 🔌 **hook만, 미연결** (RAG 팀) | gap, alternatives |

---

## 5. 신뢰성 장치 (계층 공통)

| 위험 | 방어 |
|---|---|
| LLM 즉석 판단 | 의도분류 스키마에 판단 필드 없음 / 읽기 스키마에서 판단 필드 제거 — **금지는 프롬프트가 아니라 구조로** |
| 근거 환각 | `evidenceMap` 원문 대조 제거 → id 룰 재부여 → skillEvidence 룰 구축 → verify 참조 무결성 — 문장이 판정까지 가는 동안 지어낼 기회 차단 |
| 자소서 환각 | evidenceMap 밖 서술 금지 + 원문 대조 + P4 verify + 초안 게이트(사용자 검토 없이 완성본 없음) |
| 문항 답 창작 | 프로필 결측 문항은 생성 대신 되묻기 |
| 허구 공고 | 대안은 RAG 실존 공고만. 미연결 시 경로 '유형'만 내고 confidence 0 |
| 오라우팅 | 라우팅 가시화 + 저신뢰 되묻기 + 결정론 검증기(validate_plan) + 플래너 평가셋(46케이스, 정확도 0.93·안정성 0.98) |
| 플래너 환각 선택 | 선택지를 스키마 Literal 로 제한 — 미등록 에이전트는 검증 단계에서 거부 |
| 에이전트 폭주 | **제출·결제·전송 툴 미보유** — 최종 행동은 사람만 가능 |

---

## 6. 성능 (2026-07-23 실측, user2 실문서)

| 구간 | 소요 | 비고 |
|---|---|---|
| 첫 분석 턴(파이프라인 전체) | **~81초** (`gpt-5.4` 기준. `gpt-5-nano`면 ~240초) | 77%가 이력서 추출 — 모델 생성 속도 문제 |
| 판정 계층(sufficiency·gap·roadmap·alt·verify) | **~0초** | 결정론 + 의미판정 배치 1콜 + 캐시 |
| 이후 턴(추천·진단·면접·자소서) | 수 초~수십 초 | 프로필·분석 결과 세션 캐시 |
| 의도분류(모든 턴) | ~6초 | LLM 1콜 |

판정 결과는 모델 교체와 무관하게 동일(fitGrade "중") — 판정 계층이 결정론이라는 설계 의도의 실증.
남은 개선 여지: parse ∥ profile 병렬화(첫 턴 ~50초선), 이력서 추출의 백엔드 사전 계산화,
nl_render 실측.

---

## 7. 테스트 전략 (계층별 분리)

계층별 신뢰성 계약이 다르므로 **하나의 스위트로 뭉치지 않는다.**

| 계층 | 검증 | 상태 |
|---|---|---|
| 판정 엔진 + 오케스트레이터 | 결정론 회귀 테스트 — LLM 없이 1초대, API 비용 0원 | ✅ 223건 (07-24 기준) |
| 플래너 | 발화→기대 실행 시퀀스 평가셋 46케이스 × N회 (`eval/planner_harness.py`, 실 LLM) | ✅ 정확도 0.93 · 안정성 0.98 (07-29) |
| 검증기(validate_plan) | (선택 시퀀스 × 자산) 조합 전수 테스트 — 순수 함수라 가능 | ✅ 19조합 + 방어 케이스 |
| 생성 에이전트 | 근거성 검사 통과율 — 근거 없는 문장 0건 | verify_rules 재사용 |
| 중단·재개 | interrupt→resume 왕복 통합테스트 | Phase 4 |

핵심 결정들은 테스트로 못 박혀 있다 — uncertain→not_met 으로 되돌리면 테스트가 깨진다.

---

## 8. 남은 작업

1. **RAG hook ①②연결** (RAG 팀) — 계약(`rag.py` RagAdapter) 준비 완료. 붙으면
   find_alternatives 가 경로 유형 대신 실존 공고를 낸다.
2. **checkpointer 도입(Phase 4)** — `ask_user`를 interrupt 기반 일시정지로 전환, P5 게이트의
   표준 패턴 확보. opt-in 이라 기존 테스트 무변경.
3. **공고 추천 검색 루프 승격(Phase 5)** — 1회 retrieval → 검색→평가→재검색 루프,
   대체추천→재판정→자소서 순환 완성.
4. **시드 데이터 확장** — skill_taxonomy·cert_db·project_template_db·career_graph 는
   대표 항목만 담은 스캐폴딩. 커버리지가 곧 품질.
5. **(수요 확인 후) tool-calling 플래너(Phase 6)** — 자유 조합 요구가 실제로 쌓이면.
