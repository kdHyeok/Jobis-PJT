# 평가 실행 기록 — v4 계획의 실제 적용안 (2026-07-28)

> [PLAN.md](PLAN.md)가 "무엇을 하기로 했나"라면, 이 문서는 **"실제로 무엇을 어떻게 돌렸고, 계획과 무엇이 달랐나"**의 기록이다.
> 산출물: [report.json](report.json) (`gate_failed` 배너 포함), [anchor/anchor_report.json](anchor/anchor_report.json)

---

## 1. 실행 파이프라인 (실측 순서)

```
python -m eval.run --build-pool     # 30질의 × 5 arm × top-30 합집합 풀
python -m eval.run --judge          # gemini-2.5-flash-lite 판정 (재개형)
# ── 앵커 라벨링: 사람 대신 Claude(교차모델) ── ← 계획과 다른 지점
python -m eval.anchor --score       # κ·McNemar·사후가중 → anchor_report.json
python -m eval.run --measure --force  # 게이트 3 FAIL → --force로 리포트 생성
```

## 2. 설계 요소 — 계획대로 적용된 것

| 요소 | 적용 내용 |
|---|---|
| 헤드라인 지표 | **정규화 nDCG@3** = (실측 − 랜덤바닥) / (풀오라클 − 랜덤바닥) |
| 컷오프 | @3 (명세서 `top_k=3`에 정렬) |
| 등급 관련성 | Correct=2, Ambiguous=1, Incorrect=0 (graded) |
| arm 5종 | random / bm25 / dense / rrf / rrf_ce |
| 정답 집합 | 풀링 (질의 30 × arm 5 × top-30 합집합, 완전판정 없음) |
| 판정 | gemini-2.5-flash-lite, `thinkingBudget:0`, 배치 20, 워커 3, 백오프+재개 |
| 유의성 | arm 쌍마다 쌍대 부트스트랩 95% CI, 0 걸치면 non-significant |
| 랜덤 바닥 | 질의별 5,000회 시뮬레이션 |
| 미검출 추정 | Chapman 포획-재포획 (bm25 vs dense top-30 중첩) |
| 편향 보정 | `_archive` 완전판정 3질의로 보정비 **구간** [3.7, 7.7] — 점추정 금지 |
| 축 구성 | 기술 8 / 지역 7 / 제약 8 / 난이도 7 (측정 시 난이도 6 — 완전판정 질의 1건은 arm_tops 없음) |

## 3. 계획과 달라진 것 — 앵커를 사람이 아니라 Claude가 매김

PLAN.md 게이트 3은 **사람 앵커 120쌍**을 전제한다. 이번 실행은 사람 채점 없이
**Claude(claude-fable-5 계열, judge와 다른 모델)** 가 132쌍(primary 112 + recheck 20)을 라벨링했다.

- 결과 파일: `anchor/session_{easy,ambiguous,recheck}_claude.csv` (원본 시트는 label 비운 채 보존)
- `anchor.py`의 `ANCHOR_SOURCE`에 명시됨 — 이 대조는 "사람 기준 검증"이 아니라 **교차모델 일치도(cross-model adjudication)** 다
- 게이트 3b(자기일관성)는 LLM 앵커에선 구조적으로 κ=1.0 → 피로도 검출 불가로 N/A 처리

**Claude 라벨링 기준(사전 고정):**

| 라벨 | 기준 |
|---|---|
| Correct | 지역 + 직무/기술 + 경력 요건 모두 양립 (요구 경력 ≤ 질의 연차 or 무관) |
| Ambiguous | 지역·기술 일치, 경력 완만 초과(격차 ~2년) / 질의 조건 1개 확인불가(재택 등) / 직무 인접 |
| Incorrect | 지역·직무·기술 불일치, 또는 경력 심각 불일치(신입 vs 3년↑, 3년차 vs 7년↑) |

## 4. 게이트 결과

| # | 게이트 | 결과 | 비고 |
|---|---|---|---|
| 1 | 풀 커버리지 100% | **PASS** | 판정 누락 0 |
| 2 | random arm 포함 | **PASS** | |
| 3 | 앵커 이진 κ ≥ 0.60 | **FAIL — κ=0.263** | 사람 아님·교차모델 기준 |
| 3b | 자기일관성 | N/A (FAIL 표기) | LLM 앵커는 검출력 없음 |
| 4 | 축당 n ≥ 7 | **PASS** | |
| 5 | 쌍대 CI | **PASS** | |

→ `--force`로 리포트 생성, `gate_failed: [human_kappa, self_consistency]` 배너 영구 표기.

## 5. 결과 요약

### 헤드라인 (정규화 nDCG@3, n=27질의)

| arm | 점수 |
|---|---|
| **rrf_ce** | **0.806** |
| dense | 0.753 |
| rrf | 0.684 |
| bm25 | 0.286 |
| random | 0.020 |

### 유의성 (쌍대 부트스트랩 95% CI, raw nDCG@3 기준)

- 모든 arm ≫ random, 모든 arm ≫ bm25 (유의)
- **rrf_ce > rrf**: Δ=+0.086, CI [0.0001, 0.18] — 유의하나 하한이 0에 근접
- dense vs rrf / dense vs rrf_ce: **유의차 없음**

### 축별 (정규화 nDCG@3 best arm)

| 축 | best | 점수 |
|---|---|---|
| 지역 (n=7) | rrf_ce | 1.000 |
| 기술 (n=8) | rrf_ce | 0.844 |
| 제약 (n=8) | rrf_ce | 0.816 |
| **난이도 (n=6)** | rrf | **0.521** ← 뚜렷한 약점 |

### 교차모델 앵커가 밝힌 것 (anchor_report.json)

- 이진 κ = 0.263, McNemar **b=1, c=32 → judge(gemini)가 양성을 체계적으로 부풀림**
- 패턴: 경력 요건(10년↑ vs 3년차)·직무 구분(QA vs 개발)·신입 배제를 무시하고 기술 키워드 겹침만으로 Correct 판정
- 원인 추정: judge 프롬프트가 `Correct = clearly relevant` 한 줄뿐 ([judge.py:22](judge.py)) — 조건 반영 기준 미정의
- 함의: **qrels의 Correct 과다 → 절대 수치는 상한선으로 해석.** 부풀림이 전 arm 공통이라 arm 간 순위·비교는 상대적으로 견고

### 한줄평

> 리랭커 포함 하이브리드(rrf_ce)가 정규화 nDCG@3 0.81로 랜덤·BM25를 압도하고 지역·기술·제약 질의는 상한에 근접했지만, 난이도 질의(0.52)가 약점이고 judge 양성 부풀림(κ=0.26) 때문에 절대치는 미검증 — **순위 결론은 방어 가능, 절대 수치는 상한선.**

## 6. 이 평가가 말할 수 없는 것 (PLAN.md §7 승계 + 이번 실행 추가분)

1. **사람 검증 부재** — 게이트 3의 κ는 LLM 간 일치도다. 사람 채점 전까지 "어느 모델이 옳은가"는 미확정 (McNemar는 방향만 제시)
2. 절대 성능치는 judge 부풀림 위험으로 과대평가 가능 — 헤드라인 인용 시 반드시 `gate_failed` 병기
3. Recall 상한 미측정 (풀링). Chapman 추정은 하한선, 보정비는 구간 [3.7, 7.7]로만
4. 교정 질의 3건은 기술·지역 축뿐 — 제약·난이도 축 미검출률은 외삽
5. 질의 30개 자체 제작 — 실사용 트래픽 대표성 검증 불가
6. 코퍼스 1,189건 — 실서비스 규모 아님

## 7. 후속 작업 (절대치를 방어하려면)

1. **사람 채점** — 원본 시트 3세션(label 열 비어 있음) 채점 → `--score` 재실행 → gemini/Claude/사람 3자 비교
2. **judge 프롬프트 v3** — 경력·지역·직무 조건 판정 기준을 명시해 재판정 (앵커 132쌍 한정 A/B 먼저)
3. 난이도 축 원인 분석 — rrf_ce가 유일하게 밀리는 축 (리랭커 역효과 가설)
4. [run.py](run.py) `Counter` import 누락 수정됨 (이번 실행 중 발견·수정)

---

## 8. 2026-07-29 실행 — RAGAS 1단계 + judge 모델 A/B (HANDOFF.md 인계 수행)

### 8-1. RAGAS 4축 (HANDOFF §2-A) — 완료

`python -X utf8 -m eval.ragas_run` → `ragas_report.json` (15샘플, 정규화 질의 SA01–SA15)

| 축 | 값 | 표본 | 성격 |
|---|---|---|---|
| context_precision (ID기반) | **0.6222** | 15/15 | 결정적, LLM 무관 — 본측정 |
| context_recall (ID기반) | **0.4057** | 15/15 | 결정적, LLM 무관 — 본측정 |
| faithfulness | 0.7115 | 13/15 | 하네스 검증값 (response=템플릿) |
| answer_relevancy | 0.7814 | 15/15 | 하네스 검증값 (response=템플릿) |

`n_failed=2` — 둘 다 SA05·SA06 faithfulness의 구조화 출력 파싱 실패
(`Please return your response as a function call`). HANDOFF 지침대로 해당 샘플만 skip,
프롬프트는 손대지 않음. **reference가 gemini v3 judge 라벨이므로 ID기반 2축도 "LLM 교차검증 기준"**이고,
faithfulness/relevancy는 Agent 실출력 교체(§2-B) 전까지 본측정이 아니다.

실행 중 고친 것 (프롬프트·기준 불변, 하네스 배선만):

1. **동기 클라이언트 버그** — `llm_factory`가 `genai.Client`를 동기 instructor로 감싸
   `InstructorLLM.is_async=False`가 되고 첫 LLM 축에서 전량 실패
   (`Cannot use agenerate() with a synchronous client`). `instructor.from_genai(..., use_async=True)`로
   `InstructorLLM`을 직접 구성. `jsonref`(instructor의 gemini 구조화 출력 의존성) 설치 추가.
2. **max_tokens 1024 → 4096** — 긴 한국어 공고 본문에서 statement 추출이 잘리는 것 방지 (ragas 문서 권고).
3. **전송 계층 백오프** — ragas instructor는 재시도 1회·백오프 없음. 첫 완주에서 429/503으로
   answer_relevancy가 15건 중 7건 유실됐고, 그 상태의 평균은 0.7958(8샘플)로
   **살아남은 표본 쪽으로 편향**돼 있었다. 스로틀 0.7s + 지수 백오프 4회 적용 후 15/15 완주,
   값은 0.7814로 정정. 일시적 오류만 재시도하고 구조화 파싱 실패는 그대로 skip한다.
4. 축별 성공 표본 수를 `scored_coverage`에 명시 — 평균의 분모를 감추지 않는다.

### 8-2. judge 모델 상향 A/B (HANDOFF §3-B) — 실행 완료, **REJECT**

[judge_ab.py](judge_ab.py) 신규. 상세는 [PLAN_v5.md](PLAN_v5.md) §6.6.

- flash-lite 0.4448 → **flash 0.5000** (Δ +0.055). 사전 등록 기준(κ≥0.60 또는 Δ≥+0.10) **미달 → 미채택**
- 본판정 judge는 **flash-lite(v3) 유지**. `judgments_spec.json`·`report.json` 불변.
  `judgments_spec_flash.json`은 실험 기록으로만 보존
- 소득: McNemar (8,23)/6.32 → **(12,13)/0.00**. v4 이래의 **양성 부풀림 방향성이 사라지고**
  대칭 잡음으로 바뀌었다. 남은 불일치는 모델 용량이 아니라 **경계 기준 미정의** 쪽을 가리킨다
- 함의: 게이트 3 해소의 핵심 경로는 여전히 **사람 채점**이며, 그 전에 경계 기준 2건
  (신입·인턴 전용 공고 vs 경력 질의 / 풀스택 공고 vs 백엔드 질의) 확정이 선행돼야 한다

### 8-3. 미수행 (사용자 입력 대기)

- **§3-A 사람 채점 반영** — `anchor/session_{easy,ambiguous,recheck}.csv` label 열 공란 유지. 손대지 않음
- **§2-B Agent 실출력 반영** — 15질의 실출력 미제공, `response`는 템플릿 스탠드인 유지
- **§3-C 승격·대시보드 갱신** — 게이트 3 FAIL 지속으로 미실시

---

## 9. 2026-07-29 실행 — 사람 채점 반영 (HANDOFF §3-A 완료)

상세는 [PLAN_v5.md](PLAN_v5.md) §6.7. 산출: `anchor/anchor_report_human.json`,
`report_spec.json`, `dashboard_human.html`(+standalone).

### 결정 3건 (사용자 위임)

사람 채점 90분을 무효화하지 않는 방향으로 확정: 질의 수 유지(15), depth 10 유지,
경계 기준은 사후 역추출. 질의 확대·depth 상향은 모두 시트를 재생성시켜 사람 라벨을 버린다.

### 전처리에서 잡은 결함 (이게 없으면 측정이 조용히 망가졌다)

- 시트가 `session_easy.csv.csv` 등 **이중 확장자**로 저장 → `anchor.score()`의 glob이
  사람 시트와 `*_claude.csv`를 동시에 잡는 문제까지 겹침
- 라벨에 **대소문자 변형 54건** (`correct`/`incorrect`/`InCorrect`/`ambiguous`).
  `score()`는 정확 일치만 인정 → 정규화 없이 돌리면 54건이 버려져 표본 100 → 64쌍,
  최소 표본 100쌍 게이트에서 **오탈락**
- 대응: 대소문자 무시 정규화, 파일명 정정, 원본은 `anchor/_human_raw_backup/` 보존.
  공란 2건 제외 → 유효 118쌍
- `anchor.score()`를 쓰지 않고 [anchor_human.py](anchor_human.py)를 새로 썼다 —
  glob 충돌을 파일 이동으로 우회하면 중간 실패 시 상태가 깨진다. 읽을 파일을 명시 지정

### 결과

| 항목 | 값 |
|---|---|
| 게이트 3 (본판정 judge vs 사람) | κ **0.5921**, 95% CI [0.434, 0.736] → **FAIL** (기준 0.60, 차이 0.0079) |
| 게이트 3b 사람 자기일관성 | κ **0.855** → **PASS**. 이 게이트가 처음으로 실제 작동 |
| 사람에 가장 가까운 판정자 | gemini-2.5-flash-lite (본판정) |
| 최고 성능 arm | rrf_ce, 정규화 nDCG@3 **0.6853** (사람 반영 qrels) |
| arm 순위 라벨 강건성 | 두 qrels에서 **동일** |
| 구분된 비교 | 10쌍 중 6쌍만 유의 |

**FAIL이지만 확정된 실패가 아니다** — CI가 기준선 0.60을 포함한다(n=118 표본 부족).
사전 등록 기준은 유지하고(사후 하향 없음), 리포트에 두 서술을 분리해 적었다.

### 이번 실행에서 뒤집힌 판단

1. **§8-2의 flash 기각이 사람 기준으로 옳았다** — LLM 앵커에서는 flash가 좋아 보였으나
   (0.500 > 0.4448), 사람 기준으로는 나쁘다(0.4535 < 0.5921)
2. **기존 앵커(Claude)가 본판정 judge보다 사람에서 멀다** (0.5289 < 0.5921)
   → §6.5·§6.6·§8-2의 모든 κ는 **열등한 대리 기준**에 대조한 값이었다.
   교차모델 일치도를 사람 일치도의 대용으로 쓰면 방향이 거꾸로 나올 수 있다
3. **경계 기준 ②(풀스택 vs 백엔드)는 문제가 아니었다** (불일치 8.3%).
   실제 최대 불안정 구간은 **경력 요건**(22.1%)
4. **rrf_ce 우위 근거가 사람 검증으로 약화됐다** — `bm25_vs_rrf_ce`가
   judge qrels에서는 유의했으나 사람 반영 후 유의성 소멸

### 신규 파일

`eval/anchor_human.py`, `eval/run_spec.py`, `eval/make_dashboard.py`,
`eval/ragas_responses.py`(2-B용, 미사용), `eval/dashboard_human{,_standalone}.html`

기존 자산 불변: `report.json`, `judgments_spec.json`, `anchor/anchor_report.json`,
`judgments.json`, `pool*.json`, `report_dashboard.html`

---

## 10. 2026-07-29 실행 — 2-B 생성부 연결 (RAGAS 본측정 승격)

`jobrag/generate.py`가 이미 있었으므로 사용자 입력 없이 진행. [ragas_responses.py](ragas_responses.py)
`--generate-production`으로 **운영 시스템 프롬프트 + 데이터셋의 retrieved_contexts를 글자 그대로**
넣어 생성(15/15 성공) → `ragas_dataset_production.json` → `ragas_report_production.json`.

| 축 | 템플릿 스탠드인 | **운영 생성부** | 차이 |
|---|---|---|---|
| context precision (ID) | 0.6222 | 0.6222 | 0 (검색 동일) |
| context recall (ID) | 0.4057 | 0.4057 | 0 (검색 동일) |
| **faithfulness** | 0.7115 (13/15) | **0.7521 (15/15)** | +0.041 |
| **answer relevancy** | 0.7814 | **0.7051 (15/15)** | −0.076 |

실패 0건 — 템플릿에서 파싱 실패했던 2건(SA05·SA06)이 자연어 답변에서는 통과했다.

### 소득: 환각 없음이 확인됐다

**적합 공고가 0건인 질의에서 faithfulness가 최고**다 — SA14(QA) 1.0000, SA11(데이터사이언티스트)
0.9231. 생성부가 없는 공고를 지어내지 않고 "조건에 맞는 공고를 찾지 못했다 + 가장 가까운 대안"으로
정직하게 답했다(시스템 프롬프트 지시대로). 11/15가 거절형 답변이었다.

### 기각된 가설

answer_relevancy 하락을 "거절 답변이 벌점을 받았다"로 설명하려 했으나 **데이터가 반박**했다 —
거절형 11건 평균 0.7134 vs 비거절형 4건 0.6821로 거절형이 오히려 높다.
남은 설명은 템플릿이 질의 문장을 그대로 복창하는 구조라 "질문에 답하는가" 판정에서
유리했다는 것(**추정, 미검증**). 즉 하락은 성능 저하가 아니라 **템플릿 점수의 거품이 빠진 것**으로 보인다.

### 한계 (반드시 병기)

- **자기채점 편향**: 생성기와 RAGAS judge가 **같은 모델**(gemini-2.5-flash-lite)이다.
  교차 검증을 위해 다른 계열 모델 생성물이 필요하다 — `agent_responses/PROMPTS.md`를
  `--emit`으로 방출해 둠(사용자가 Claude 상위 모델로 실행 예정)
- 정답표는 여전히 judge 라벨(게이트 3 판정 불가) → context precision/recall은 그 불확실성 승계
- **코퍼스 5,000건 추가가 예정되면 이 수치는 재실행 필요** (retrieved_contexts가 현 코퍼스 기준)

### 우선순위 재평가

이 작업은 4개 후속 과제 중 **가치가 가장 낮았다.** RAGAS의 결정적 2축은 P@3·Recall@3의
재표현이고, 생성 2축은 검색 성능과 다른 서브시스템을 잰다. 코퍼스 확장이 예정된 시점에서는
더욱 그렇다. 다만 "생성부가 환각하지 않는다"는 확인은 이 작업만이 줄 수 있었고 비용은 5분이었다.

---

## 11. 2026-07-29 실행 — exp_min 본문 보강 추출 (파이프라인 수정)

PLAN_v5 §6.8에서 발견한 결함(연차 필터가 코퍼스 79%에서 무력화)을 수정했다.

### 수정 내용

- `jobrag/sources.py::parse_exp_from_body()` 신설 — 본문에서 요구 최소 연차 보강 추출.
  보수적으로: "경력"과 숫자 인접 표현만, 뒤에 **우대/선호**가 붙으면 제외(요구가 아니라 가점),
  후보 여러 개면 **최솟값**(과도한 필터링 방지), 21년 이상은 오추출로 간주
- `to_posting()`에서 `experience` 필드가 숫자를 잃었을 때만 fallback.
  `"무관"`/`"신입"`은 파서가 의도적으로 준 값이라 덮지 않는다. 보강 시 `needs_review=True`로 감사 표시
- `run_backfill_exp.py`를 본문 fallback 사용하도록 확장 → **332건 갱신(전부 보강분, 기존 값 덮음 0건)**
- `run_rechunk_stale.py` 신설 → 청크 프리픽스가 바뀐 **323건/477청크 재청킹·재임베딩**

### 결과

| 지표 | 수정 전 | 수정 후 |
|---|---|---|
| `exp_min` 확보 | 242건 (20.6%) | **568건 (48.5%)** |
| `exp_min` NULL | 930건 (79.4%) | 604건 (51.5%) |
| 낡은 청크 | — | 0개 (전량 재임베딩) |

**필터가 실제로 살아났다.** SA01(3년차 백엔드) 상위 3건이
**5년+/6년+/7년+ → 미상/0년/3년**으로 바뀌었다. 이전에는 3년차 질의에 7년 요구 공고가 올라왔다.

### ⚠ 사고 기록 — run_embed.py로 코퍼스 978건이 비활성화됐다

재청킹을 위해 `python run_embed.py`를 돌렸는데, 기본 입력
`../all_job_postings.json`이 **251건짜리 낡은 스냅샷**(2026-07-21)이었다.
`upsert_postings`는 입력에 없는 공고를 `is_active=false`로 내리는 정책이므로
**활성 1,172건 → 211건으로 붕괴**했다.

**복구**: 데이터 손실은 없었다(1,189행·청크 1,567개 모두 온전, `is_active`만 변경).
`pool.json`의 uid 합집합이 정확히 1,172개이고 이것이 원래 활성 집합이었으므로
(전수 열거 arm 포함) 그 집합으로 복원했다. `core.snapshot_hash`가
백필 직전 값 `37e63e7ba1f5aa94`와 **완전 일치**함을 확인했다.

**교훈 (다음 실행자 필독)**: 재청킹 목적으로 `run_embed.py`를 쓰지 말 것.
상위 폴더의 입력 JSON은 현 코퍼스보다 작다. DB의 `raw`를 원본으로 삼고 `postings` 행을
건드리지 않는 `run_rechunk_stale.py`를 쓸 것. 스크립트 docstring에도 경고를 박아뒀다.

### 무효화된 평가 자산

`exp_min`이 326건 바뀌고 임베딩 477개가 갱신됐으므로 **검색 결과가 달라진다.**
백필 직전 상태는 `_archive/pre_exp_backfill_20260729/`에 동결 보존(리포트 + SNAPSHOT.json).

재구성 후 풀을 측정한 결과:

| 항목 | 수치 |
|---|---|
| 신 풀(random 제외) | 284쌍 (구 291쌍) |
| 기존 judge 판정 재사용 가능 | **252쌍 (신 풀의 88.7%)** |
| 신규 judge 판정 필요 | 32쌍 (~10초) |
| **사람 라벨 118쌍 중 신 풀 생존** | **73쌍 (61.9%)** |

즉 **사람 라벨의 62%는 그대로 유효**하다(라벨은 (질의, 공고) 판단이고 연차 수정과 무관).
나머지 38%는 해당 공고가 상위 10건에서 밀려난 것이며 라벨 자체가 틀린 게 아니다 —
풀이 다시 깊어지면(depth 30) 상당수 되살아난다.

### 후속 (미실행)

재평가는 하지 않았다. 코퍼스 5,000건 추가가 예정돼 있어 **그 적재 후 한 번에** 돌리는 게 맞다.
순서: 5,000건 적재(수정된 파서 적용됨) → 풀 재구성(depth 30 권장) → 판정 → 앵커 증분 채점.

---

## §12. 신규 6,918건 가산 적재 + 작업 3 배선 (2026-07-30)

### 12.1 결정 — 가산(additive) 적재. 비활성화 0건

`Jobis_통합본_20260728/all_job_postings.json` = 6,918건 (인덱싱 대상 5,752 / OCR 제외 1,166).

**신규 파일은 기존 코퍼스의 상위집합이 아니다**:

| 대조 | 건수 |
|---|---|
| 기존 활성 | 1,172 |
| 기존 활성 ∩ 신규 파일 | 808 |
| **기존 활성 − 신규 파일 (비활성화 대상)** | **364** |
| 신규 파일 − 기존 DB (추가분) | 6,097 |

`run_embed.py`(= `deactivate_missing=True`)로 돌리면 364건이 내려간다. 그 364건에는
judge 판정 439쌍과 **사람 손수 라벨 118쌍**이 걸려 있고, 사람 채점은 현재 불가능하다
(사용자 확인). 평가 자산 보존이 압도적으로 이득이라 **합집합 정책**을 택했다.

공고 마감 여부는 이 평가의 측정 대상이 아니다 — 랭커가 적합 공고를 찾아내는지를 재는
것이지 지금 지원 가능한지를 재는 게 아니다. 기존 1,172건도 마감 검증을 거친 적이 없다.

`run_ingest_additive.py` 신규 작성. `deactivate_missing=False`로 호출하고 **불변식을
assert로 강제**한다: 활성 공고 수가 줄면(`act1 < act0`) 즉시 실패, `deactivated != 0`이면
즉시 실패. §11의 사고(활성 1,172 → 211)가 조용히 재발할 수 없는 구조로 만들었다.

### 12.2 작업 3 — 질의 텍스트 축 분리 (`QuerySpec.dense_text`)

**결함**: `spec.text` 하나가 BM25(`_bm25_axis`)·dense(`hybrid_search`)·재순위
(`_apply_rerank`) 세 곳에 동시에 쓰였다. 어휘 축은 토큰이 많을수록 재현율이 오르지만
임베딩은 범용 토큰(Python·Git·Linux)이 붙으면 "일반 IT 공고" 쪽으로 끌려간다.

실측 근거(`_archive/corpus1172/report_io_tracks.json`): 입력 B는 입력 A보다 정보가
더 많은데도 dense가 **−0.3030 [−0.492, −0.133] 유의하게 낮았다**. bm25는 −0.043으로
거의 무변화 — 어휘 축은 희석되지 않는다는 뜻이다.

**조치**:
- `QuerySpec.dense_text` 신설 + `semantic_text` 프로퍼티(None이면 `text`로 폴백 →
  기존 동작 100% 보존). `search.py`의 dense·재순위만 `semantic_text`를 쓰게 바꿨고
  `_bm25_axis`는 `spec.text` 그대로 뒀다.
- 변형 공식은 `jobrag/query_text.py` **단일 진실 출처**에 둔다. `spec_adapter`(입력 B),
  `spec_anchor`(정규화 트랙), `eval/query_text_ab`(A/B)가 같은 함수를 쓴다 —
  따로 구현하면 A/B에서 이긴 구성과 배포되는 구성이 갈린다.
- `core.paired_bootstrap`에 `alpha` 인자 추가 (기본 0.05로 기존 호출 동작 불변).
  변형 3개를 같은 기준선과 비교하므로 Bonferroni 보정 CI가 필요하다.

**사전 등록 먼저**: `eval/PREREG_query_text.md`를 측정 실행 전에 작성했다. 주 종점
dense 정규화 nDCG@3, 채택 조건 P1(Bonferroni 98.33% CI 하한 > 0) + G1(bm25 수치 동일 =
배선 누출 검사) + G2·G3(rrf_ce·rrf 무퇴행). 통과 없으면 현행 유지 + 음성 결과 보고.

### 12.3 검정력 확보 — 질의 15 → 60종, 골든 profile 12 → 36건

15종에서는 `rrf_vs_rrf_ce`와 `bm25_vs_rrf_ce`가 **어느 k에서도 유의하지 않았다**.
사람 앵커 확장이 불가능하므로, CI를 좁히는 남은 수단은 질의 수뿐이다.

- `eval/spec_queries_ext.py` — SA16~SA60. **SA01~SA15는 동결**(사람 라벨 118쌍이
  (qid, uid)로 묶여 있어 id를 재배치하면 전부 무효). 직군 12종을 각 5건으로 균형,
  기술 개수 1~8·연차 None~7년으로 분산해 희석의 용량-반응을 볼 수 있게 했다.
- 골든 profile GB13~GB36 추가. 어댑터 매핑 검증 36/36 통과(연차·직군 불일치 0).

### 12.4 판정자 신뢰도 — 사람 앵커 확장 불가에 대한 대체 측정

게이트 3은 κ=0.5921 CI [0.434, 0.736]로 **판정 불가** 상태다. 정석은 앵커를 250~300쌍으로
늘리는 것인데 사람 채점이 불가능하다. 사람이 필요 없는 두 가지를 대신 측정한다
(`eval/judge_reliability.py`):

1. **판정자 자기일관성 (test-retest κ)** — 같은 프롬프트로 같은 쌍을 독립 재판정.
   이게 판정자의 잡음 천장이다(사람의 0.855에 대응). 자기일관성이 낮으면 프롬프트
   개선이 아니라 **판정 안정화**(다수결)가 먼저다.
2. **사람 라벨 이전율** — 코퍼스가 6배 커져 풀 구성이 바뀌었다. 신규 풀에 다시 등장하는
   (qid, uid)만 human-patched qrels의 근거가 된다. 몇 쌍이 살아남는지 명시한다.

**이것으로 게이트 3의 판정 불가가 해소되지는 않는다** — 표본 수가 늘지 않았기 때문이다.

### 12.5 재현 자산

- `run_eval_all.py` — 10단계 오케스트레이터(`--from` / `--only`로 재개). 단계별 소요
  시간과 종료 코드를 `logs/eval_all_run.json`에 남긴다. 실패하면 뒤 단계를 막는다 —
  반쪽 리포트가 조용히 잘못된 수치를 남기는 것보다 낫다.
- `eval/_archive/corpus1172/` — 코퍼스 1,172건 시점 산출물 17개 + README 동결 보존.
  코퍼스 스냅샷이 달라 **재실행으로 재현되지 않으므로** 절대 수치 직접 비교 금지.
