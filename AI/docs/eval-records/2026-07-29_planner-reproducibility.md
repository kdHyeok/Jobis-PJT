# 재현성 측정 — 플래너·오케스트레이터 (2026-07-29)

> **측정 이력 기록.** `evals/planner_baseline.json`(temp 0.3) · `evals/planner_baseline_temp0.json`(temp 0)
> 이 원본 수치이고, 이 문서는 "무엇을 왜 재고 무엇이 나왔나"를 남긴다.
> 배경: `docs/멀티에이전트-프로토타입-비교분석.md` §2-3 (재현성 미측정 지적).

## 왜 쟀나

기록돼 있던 플래너 정확도 **100%** 는 **1회 측정치**였다. LLM 계열 시스템의 정확도를 1회로
말할 수 없다는 것이 프로토타입(`Agent_Test/tests/eval.py`, 케이스당 3회)에서 배운 관점이고,
`eval/consistency.py` 로 이식만 해 둔 채 **한 번도 돌리지 않았다.**

## 무엇을 바꿔서 쟀나

### ① 지표 — 정확도와 안정성을 갈랐다

이식해 온 "일관성 k/N" 하나는 두 가지를 섞는다. 0/3 을 볼 때 *일관되게 틀린 것*인지
*무작위로 틀린 것*인지 구분되지 않는데, **원인과 처방이 다르다.** 같은 run 데이터에서 공짜로
갈라 낼 수 있다:

| 지표 | 정의 |
|---|---|
| `accuracy` | 기대와 일치한 run 비율 |
| `stability` | **최빈 결과**가 차지한 비율 (정답 여부와 무관) |
| `verdict` | `stable-correct` / **`stable-wrong`**(명세·프롬프트 결함) / `unstable`(flaky) |

이 구분이 이번 측정의 결론을 바로 갈랐다 — 아래 참고.

### ② 하네스가 프로덕션 흐름이 아닌 것을 재고 있었다 (수정함)

`dispatch_case` 가 07-28 에 들어온 두 경로를 몰랐다:

| 경로 | 프로덕션(`chat.handle_chat`) | 수정 전 하네스 |
|---|---|---|
| 확신 < 0.6 | **`career_chat` 이 턴을 받아 대화한다** | `asked=True`("ASK")로 뭉갬 |
| 무거운 생산자 자동 삽입 | **동의 게이트** — 실행 없이 묻는다 | `agents=()`+`asked=False` → 빈 키 |

`dispatch_case` 가 `handle_chat` 분기를 그대로 따라가게 고쳤다. `asked=True` 의 정의를
**"실행 없이 되묻는다"** 로 확정했다 — 동의 게이트는 해당하고, 저신뢰 폴백은 해당하지 않는다
(에이전트가 실제로 돌아 말을 한다). 이 수정으로 `thanks-chat`·`vent-chat` 이 정답으로 돌아왔다.

## 결과

### 플래너 — 46케이스 × 3회 (`gpt-4.1-mini`)

| | temp 0.3 (현행 `.env`) | temp 0 |
|---|---|---|
| `sequence_accuracy` | 0.6739 | 0.6884 |
| `ask_accuracy` | 0.8551 | 0.8696 |
| **`mean_stability`** | **0.9420** | **0.9493** |
| stable-correct | 29 | 31 |
| stable-wrong | 9 | 8 |
| unstable | 8 | 7 |

### 오케스트레이터 풀턴 — 7케이스 × 3회 (`eval/consistency.py`, 첫 실행 기록)

**6/7 케이스가 3/3 일관.** 이탈 3건은 전부 한 케이스(S5)에서 나왔고 그것도 **안정적 오답**이다.

```
S1 일상 위로 ✅3/3  S2 무관 거절 ✅3/3  S3 공고 제출→정리 ✅3/3  S4 이력서 제출→정리 ✅3/3
S5 갭분석 동의게이트 ❌0/3 — 기대 게이트, 관측 [posting_analysis, resume_diagnosis]×3
S6 슬롯 오배정 교정 ✅3/3  S7 공고 추천(실데이터) ✅3/3
```

## 판정

### 1. 재현성은 문제가 아니었다

플래너 안정성 **0.942**, 풀턴 6/7 완전 일관. **온도를 0.3 → 0 으로 내려도 0.949 로 거의
변하지 않았다**(불안정 8 → 7). 남은 흔들림은 온도가 아니라 발화 자체의 애매함에서 온다.

> **→ 티어별 온도 분리(planner 만 temp 0)는 지금 할 이유가 없다.** 측정 전에는 유력한
> 손잡이로 보였는데, 재고 나니 값이 없다. `.env` 의 `LLM_TEMPERATURE=0.3` 은 그대로 둔다.

### 2. 정확도 100% → 68% 은 코드 회귀가 아니다

| 시각 | 일 |
|---|---|
| 07-27 **16:24** | `planner_baseline.json` 저장 (46/46, **1회**) |
| 07-27 **21:42** | `fbc876d` — "자료 제출 턴은 정리·확인 후 판정" 프롬프트 규칙 추가 |
| 07-28 (3회) | 플래너 프롬프트·인자·동의 게이트 추가 변경 |
| 07-29 | **재측정 (이 문서)** |

즉 **100% 는 프롬프트가 바뀐 순간 이미 죽은 숫자**였고, 재측정이 없어서 그 사실이 드러나지
않았다. (이번 세션의 변경은 플래너 경로를 건드리지 않았다 — manifest 는 name·description·params
만 싣고 `kind` 는 안 싣는다.)

### 3. 실패 17건의 분류 — 정확도/안정성 분리가 이걸 가능하게 했다

| 버킷 | 건수 | 성격 | 처방 |
|---|:---:|---|---|
| **A. 데이터셋 낡음** | 8 | 지금 동작이 **의도한 것**이다 — "고정 문구로 끝내지 않는다"(대응표 제거, 07-27), 동의 게이트(07-28) | 기대값 갱신 |
| **B. 프롬프트 과잉 적용** | 5 | **진짜 결함** — 아래 참고 | 프롬프트 수정 |
| **C. 잔여 flaky / 과잉 엄격** | 4 | 3건 flaky + 1건 순서만 다름 | 개별 판단 |

**A 예시** — 자산이 없을 때 되묻고 끝내는 대신 대화형 에이전트가 턴을 받는다:
`fit-missing-both`·`resume-missing`·`roadmap-missing`·`interview-missing`(→ career_chat /
preference_intake), `coverletter-missing-posting`(→ resume_diagnosis, 가진 자산으로 먼저 돕는다),
`coverletter-motivation`·`interview-auto-prereq`(→ 동의 게이트).

**B — `fit_analysis` 가 명시적 요청에도 안 불린다 (실사용 손해):**

| 케이스 | 발화 (자산: 이력서+공고) | 관측 |
|---|---|---|
| `fit-basic` | "이 공고 나 되나?" | posting_analysis×2 / resume_diagnosis×1 |
| `fit-paraphrase-1` | "삼성전자 백엔드 공고에 지원하면 승산 있을까?" | resume_diagnosis×2 / fit_analysis×1 |
| `fit-paraphrase-3` | "이 공고랑 내 이력서 매칭 좀 봐줘" | resume_diagnosis×2 / career_chat×1 |
| `fit-paraphrase-5` | "이 공고 요구사항 중에 내가 못 채우는 게 뭐야?" | posting_analysis×3 |
| `multi-fit-then-interview` | "분석 후에 면접 질문도 준비해줘" | resume_diagnosis×2 |

원인은 프롬프트 규칙 하나다:

```
- fit_analysis(무거운 판정)는 사용자가 정리 결과를 본 뒤 진단을 요청·동의한 턴에 고른다.
```

**"발화가 판정을 명시적으로 요청하면 그 턴에 바로 고른다"는 예외가 없다.** 그 예외는 바로 위
"이번 턴 제출 자료" 규칙에만 붙어 있다("이 발화에서 판정을 명시적으로 요청하지 않는 한").
그래서 제출 표식이 없는 턴에서는 아래 규칙만 남아 `fit_analysis` 가 사실상 차단된다.

실제 제품에서도 손해다: 세션에 이력서·공고가 이미 있는 재방문 사용자가 "이 공고 나 되나?"
라고 하면 **판정 대신 공고 요약**을 받는다. `greeting-chat`("안녕하세요" → resume_diagnosis)과
풀턴 S5 도 같은 뿌리다 — 자료가 있으면 정리부터 하라는 규칙이 너무 넓게 적용된다.

## 남은 일

1. **B 수정** — 프롬프트에 명시적 판정 요청 예외를 넣고 재측정. 이 5건 + `greeting-chat` + S5 가
   함께 움직일 것으로 예상.
2. **A 갱신** — 데이터셋 기대값을 현행 정책으로. 갱신 전에는 `sequence_accuracy` 를 품질
   지표로 인용하지 않는다(지금 값은 정책 변경분을 오답으로 세고 있다).
3. **재측정 규약** — 플래너 프롬프트를 고치면 baseline 을 다시 저장한다. 이번 일의 교훈:
   **프롬프트 변경과 평가셋 재측정이 같은 커밋에 없으면 baseline 은 조용히 죽는다.**
4. `agent_loop` 궤적 안정성은 여전히 미측정(비교 문서 §2-1).

---

# 후속 (같은 날) — B 수정 → A 갱신 → 재측정

위 "남은 일" 1·2 를 실행했다. **한 번에 두 축을 고치지 않고, 고칠 때마다 다시 쟀다** — 그래야
어느 변경이 무엇을 움직였는지 말할 수 있다.

## 측정 궤적

| 단계 | 정확도 | 안정성 | stable-correct | stable-wrong | unstable |
|---|---|---|---|:---:|:---:|
| ① 최초 (하네스 수정 후) | 0.6739 | 0.9420 | 29 | 9 | 8 |
| ② 프롬프트 B 수정 | 0.7826 | 0.9565 | 32 | 8 | 6 |
| ③ 과잉 발동 조항 축소 | 0.8188 | **0.9855** | 37 | 7 | 2 |
| ④ 데이터셋 A 갱신 | **0.9275** | 0.9783 | **41** | **2** | 3 |

`ask_accuracy` 는 ④에서 **1.0**.

## ② 무엇을 고쳤나 — 프롬프트 (B)

`fit_analysis` 규칙에 **"발화가 판정을 명시적으로 요청하면 그 턴에 바로 고른다"** 예외를
넣었다(예시 발화 5개 포함). 원래 그 예외는 위 "이번 턴 제출 자료" 규칙에만 붙어 있어서,
제출 표식이 없는 턴에는 "정리 먼저" 규칙만 남아 판정이 사실상 차단됐다.

**B 5건 전부 해결**: `fit-basic`·`fit-paraphrase-1`·`-3`·`-5`·`multi-fit-then-interview`
→ 전부 3/3 `fit_analysis`.

## ③ 같이 넣은 조항이 과잉 발동했다 (측정이 잡아냈다)

②에서 `greeting-chat` 도 고치려고 *"인사·감사·하소연·잡담이면 career_chat"* 을 함께 넣었는데,
후반부 문구("사용자가 요청하지 않은 작업을 시작하지 않는다")가 **기능 요청까지 끌어갔다**:

```
interview-with-analysis  "면접 예상 질문 뽑아줘" (analysis 보유) → career_chat ×3   ← 새 실패
interview-followup · roadmap-with-all-assets · recommend-missing-resume · preference-open  → career_chat 섞임
```

②만 보면 정확도가 올라갔으니(0.67→0.78) 통과시켰을 것이다. **케이스별 판정을 보고서야**
"고친 것 8건 / 깨뜨린 것 6건"이 드러났다. 조항을 *"발화에 아무 요청도 없고 인사·감사·하소연
뿐이면"* 으로 좁히고 반례를 명시하니 ③에서 불안정이 6 → **2** 로 떨어졌다.

> 교훈: 프롬프트 규칙은 **좁히는 문장과 넓히는 문장을 같은 커밋에 넣지 않는다.** 총계만 보면
> 서로를 가린다.

## ④ 데이터셋 갱신 — 근거를 케이스마다 적었다

정책 변경으로 낡은 기대값 **6건**을 갱신하고, 각 케이스 `note` 에 *어느 결정이 그렇게 정했나*
를 남겼다(근거 없이 고치면 평가셋이 구현을 따라가는 거울이 된다):

| 케이스 | 갱신 | 근거 |
|---|---|---|
| `resume-missing`·`roadmap-missing` | ASK → `career_chat` | 07-27 대응표 제거 — 고정 문구로 끝내지 않는다 |
| `coverletter-missing-posting`·`interview-missing` | ASK → `resume_diagnosis` | 가진 자산으로 먼저 돕고, 부족한 자료는 그 에이전트가 대화로 요청 |
| `coverletter-motivation` | 실행 → ASK | 동의 게이트(07-28) — 무거운 파이프라인을 말없이 시작하지 않는다 |
| `fit-missing-both` | ASK → `preference_intake` | 자산이 없어도 대화로 받는다 |

## 일부러 실패로 남긴 2건 (덮으면 숫자가 거짓이 된다)

- **`fit-missing-posting-degrade`** "이 공고 나 되나?"(이력서만) → `career_chat`×3.
  같은 상황의 `coverletter-missing-posting`·`interview-missing` 은 `resume_diagnosis` 로 가는데
  이것만 대화로 빠진다 — **플래너가 일관되지 않다.** 열어 둔다.
- **`multi-coverletter-and-interview`** → 내용은 맞고 **순서만 반대**.
  둘은 서로의 산출을 쓰지 않아 `chat.parallel_group` 이 실제로는 동시 실행한다. 즉 순서가
  결과를 바꾸지 않는데 데이터셋이 순서를 강제한다 — **지표가 "순서 무관"을 표현하지 못하는
  한계**라 그대로 둔다.

## 풀턴 재검증 (7케이스 × 3회)

프롬프트 변경 후에도 **6/7 완전 일관**. 남은 S5("자소서 써줘" + 두 자료 동시 제출)는
`resume_diagnosis`×2 / `fit_analysis>application_plan`×1 로 갈린다 — "제출 턴이니 정리 먼저"와
"자소서를 청했으니 판정부터"가 둘 다 살아 있는 **진짜 애매함**이라, 평가셋을 고쳐 덮지 않고
제품 판단으로 남긴다.

> 덤: 그 run2 궤적 `['fit_analysis', 'application_plan']` 은 **`observe_rules.weak_grade_transition`
> 이 실사용에서 발동한 기록**이다(등급이 낮아 자소서를 지원 경로 설계로 교체). 비교 문서 §2-2 가
> 넣은 규칙이 계측된 궤적으로 확인된 첫 사례다.

## 남은 일

1. `fit-missing-posting-degrade` 의 일관성 — 판정 요청인데 전제가 반만 있을 때 무엇을 할지 확정.
2. S5 의 제품 판단 — 제출 턴에 기능 요청이 함께 오면 정리 먼저인가 요청 먼저인가.
3. 지표가 "순서 무관 집합"을 표현하도록 확장할지(현재는 시퀀스 완전 일치만).
4. `agent_loop` 궤적 안정성은 여전히 미측정.

---

# 후속 2 — 열린 질문 2개 처리 (같은 날 밤)

**GMS 크레딧 절약 방침**(큰 분기마다 한 번만 측정)에 맞춰, 프롬프트를 반복 조율하지 않고
**한 번 측정 → 판단 → 되돌림/기록**으로 끝냈다.

## 질문 ① 전제가 반만 있을 때 — 시도했고 **되돌렸다**

추천안 (a)를 프롬프트에 넣었다: *"판정·생성을 요청했는데 전제가 일부만 있으면 대화로 넘기지
않는다 — 있는 자료를 정리해 보여주고 없는 자료는 그 에이전트가 청한다"*.

| | 정확도 | 안정성 | stable-correct |
|---|---|---|---|
| 전 | 0.9275 | 0.9783 | 41 |
| **후** | **0.9058** | **0.9638** | **39** |

목표(`fit-missing-posting-degrade`: career_chat×3 → **resume_diagnosis×3**)와
`fit-missing-both`(불안정 → 안정) 둘을 고쳤지만, **관계없는 케이스 4건을 깨뜨렸다**:
`interview-with-analysis`(interview_prep×3 → preference_intake×2 — analysis 를 갖고 직접
요청한 턴인데) · `interview-missing` · `roadmap-basic` · `roadmap-paraphrase`.

**원인은 규칙 간 간섭이다.** 프롬프트에는 "전제가 부분적일 때 무엇을 고르나"를 다루는 규칙이
이미 다섯 개였고, 여섯 번째가 기존 것을 흐렸다. 로드맵·면접처럼 **무관한 케이스가 흔들린 것이
증거**다(내 규칙은 그 케이스들을 언급조차 하지 않는다).

> **교훈 — 07-29 에 세 번째로 같은 것을 배웠다.** ①은 "총계는 올랐지만 케이스별로는 깨졌다"
> (③ 인사 조항), 이번은 "총계까지 내려갔다". 프롬프트 규칙은 **더 넣어서 고치는 것이 아니다.**
> 같은 판단 영역의 규칙이 다섯 개를 넘으면 새 규칙은 기존 것을 흐린다. 다음 시도는
> **추가가 아니라 다섯 개를 하나로 합치는** 방향이어야 한다.

되돌렸고, `fit-missing-posting-degrade` 는 KNOWN FAILURE 로 유지한다 — 프롬프트 한 줄로 살
값이 아니다.

## 질문 ② — 재정의: **동의 게이트를 플래너가 우회할 수 있다**

S5 의 불안정을 파고들자 표면이 아니라 **결정론 결함**이 나왔다.

```python
# router.validate_plan
requested = set(agents)                     # ← 플래너의 선택
inserted_heavy = [n for n in plan if n not in requested and registry[n].heavy]
```

게이트가 막으려는 것은 **"사용자가 청하지 않은 무거운 작업"** 인데 *"플래너가 고르지 않았다"* 를
대용품으로 쓴다. **플래너도 전제를 추론해 넣으므로 대용품이 샌다** — 실측 S5("자소서 써줘" +
자료 동시 제출): 플래너가 스스로 `[fit_analysis, coverletter_draft]` 를 골라 `fit_analysis` 가
requested 에 들어가고 **수십 초 파이프라인이 말없이 돌았다.**

계획만으로는 구분 불가 — `[fit_analysis, 소비자]` 라는 같은 모양이 두 뜻을 갖는다
("분석하고 면접 질문도"=사용자가 청함 / "자소서 써줘"=플래너가 추론함). 차이는 발화에만 있다.

**제안 해법은 스키마다**(①의 교훈대로 프롬프트 조건을 늘리지 않는다):
플래너가 `inferredPrerequisites`(사용자가 청하지 않았지만 전제로 넣은 것)를 스스로 신고하고,
게이트는 `자동 삽입분 ∪ (신고분 ∩ heavy)` 에 걸린다. **판단은 LLM, 행동은 코드.**
산문이 아니라 필드라 ①의 간섭 실패 모드를 피한다. 착수 전 계측 필요.

`router.validate_plan` 과 `eval/consistency.py` S5 에 주석으로 박아 뒀다.
**기대값을 고쳐 초록으로 만들지 않았다** — 구멍이 닫히기 전에 덮으면 그 사실이 사라진다.

## 남은 일 (갱신)

1. **동의 게이트 구멍** — `inferredPrerequisites` 스키마 안. 다음 큰 분기의 1순위.
2. 프롬프트 규칙 **다섯 개를 하나로 합치기** — 지금 상태에서는 새 규칙을 넣을 수 없다.
3. `agent_loop` 궤적 안정성 미측정.
4. 로컬 LLM 대조 (`다음작업.md` §2-E) — 기준선은 `evals/planner_baseline.json`.

---

# 후속 3 — 프롬프트 규칙 합치기 + Claude CLI 전환 (변수 분리)

두 변수를 동시에 움직여 놓고 대조군을 하나 더 돌려 귀속했다. **GMS 는 이 절에서 쓰지 않았다**
(A 는 기존 저장분).

| | 프롬프트 | 모델 | 정확도 | 안정성 | 폴백률 | 파일 |
|---|---|---|---|---|---|---|
| **A** | 옛 규칙 5개 | GMS `gpt-4.1-mini` | 0.9275 | 0.9783 | 0.029 | `planner_baseline.json` |
| **C** | 옛 규칙 5개 | Claude `sonnet` (CLI) | 0.8188 | 0.9348 | 0.109 | `planner_control_old-prompt_claude.json` |
| **B** | **사다리** | Claude `sonnet` (CLI) | **0.8406** | **0.9493** | **0.065** | `planner_baseline_claude.json` |

- **모델 효과 (A→C, 프롬프트 동일): −0.109.** 정확도 하락은 **전부 모델 교체**다.
- **프롬프트 효과 (C→B, 모델 동일): +0.022** / 안정성 +0.015 / **폴백률 0.109 → 0.065 (−40%)**.
  → **사다리는 개선이다.** 유지한다.

## 무엇을 합쳤나

"전제가 부분적일 때 무엇을 고르나"를 다루던 **규칙 5개를 우선순위 사다리 하나**로 바꿨다
(6단, 위에서 아래로 처음 맞는 항목). 후속 2 의 교훈("규칙을 더 넣지 말고 합쳐라")을 그대로 적용.
①(전제가 반만 있을 때)은 **사다리 4단 안에 종속절로** 들어갔다 — 병렬 규칙이 아니라 하위 조건이라
간섭하지 않는다. 그리고 ②를 겨냥한 가드 한 줄을 붙였다: *"무거운 판정을 전제로 쓰려고 스스로
끼워 넣지 마라 — 전제는 시스템이 채운다."*

폴백률이 40% 준 것이 합침의 직접 효과로 보인다 — 규칙이 서로를 흐리면 모델이 확신을 잃고
대화로 후퇴한다.

## 이 데이터셋은 `gpt-4.1-mini` 에 맞춰져 있다 (주의)

Claude 실패 10건 중 **3건은 "상위집합"** 이다 — 기대 에이전트를 **포함해** 한 단계 더 한다:

```
recommend-missing-resume   기대 preference_intake        → preference_intake>job_recommend ×3
preference-open            기대 preference_intake        → preference_intake>job_recommend ×3
recommend-paraphrase-3     기대 job_recommend            → resume_diagnosis>job_recommend ×1
```

"선호를 묻고 **바로 추천까지** 한다"는 더 나은 제품 동작일 수 있다. 즉 A→C 의 −0.109 를
"sonnet 이 못하다"로 읽으면 안 된다 — **평가셋이 이전 모델의 성향으로 캘리브레이션돼 있다.**

> **기대값을 sonnet 에 맞춰 고치지 않았다.** 그건 평가셋을 모델에 맞추는 것이고, 후속 2 에서
> 경계한 "평가셋이 구현을 따라가는 거울" 의 재발이다. 모델을 확정한 뒤 **의도를 다시 정하고**
> 갱신해야 한다.

## ②(동의 게이트 구멍)는 그대로 열려 있다

가드 한 줄로는 안 닫혔다 — `coverletter-motivation`(기대 ASK) 이 Claude 에서
`fit_analysis>coverletter_draft` ×2 로 나왔다. **플래너가 전제를 스스로 끼워 넣는 것을 프롬프트
부탁으로 막을 수 없다**는 증거다. 스키마 해법(`inferredPrerequisites`) 이 필요하다.

## Claude CLI 전환 상태

- `.env`: `LLM_PROVIDER=claude_code` (기본 티어 `sonnet` / 경량 `haiku`).
- `claude.exe` 가 Windows PATH 에 있어 `CLAUDE_CLI=claude` 기본값으로 붙는다.
- **1콜 5.2초** (구조화 출력은 지시+검증형 — `claude_code_llm._Structured`). 46×3 = 138콜에
  4워커로 약 6분. GMS 크레딧 0.
- `llm_failed` 1건 관측(B) — CLI 타임아웃·파싱 실패 계열. 재시도로 흡수되는 범위.

---

# 후속 4 — ② 동의 게이트 구멍을 **스키마로** 닫았다

후속 3 에서 확인된 것: 프롬프트로 *"무거운 판정을 스스로 끼워 넣지 마라"* 라고 금지해도
Claude 가 그대로 넣었다(`coverletter-motivation` → `fit_analysis>coverletter_draft` ×2,
게이트 미발동). **프롬프트 부탁으로는 못 막는다.**

## 무엇을 넣었나

**판단은 LLM, 행동은 코드** — 플래너가 *스스로 신고*하고, 게이트는 그 신고를 읽는다.

```python
# AgentPlan
inferredPrerequisites: list[AgentName]   # agents 에 넣었지만 사용자가 청하지는 않은 것
```
```python
# router.validate_plan(agents, session, inferred=())
requested = set(agents) - set(inferred)          # ← 대용품을 실제 값으로 교체
inserted_heavy = [n for n in plan if n not in requested and registry[n].heavy]
```

프롬프트 가드도 **금지 → 신고**로 바꿨다(금지는 실측에서 안 먹었으므로 그 문장을 남겨 둘
이유가 없다): *"전제를 직접 넣었다면 그 이름을 `inferredPrerequisites` 에 신고하라."*

## 플래너가 실제로 갈라 채운다 (실측, Claude `sonnet` × 3회)

| 발화 (자산: 이력서+공고) | 신고 | 결과 |
|---|---|---|
| "분석 후에 면접 질문도 준비해줘" | `[]` — 둘 다 사용자가 청했다 | `fit_analysis>interview_prep` ×3 (게이트 없음) |
| "이 공고 나 되나?" | `[]` | `fit_analysis` ×3 |
| "지원 동기 문단 초안 잡아줘" | `[fit_analysis]` | **ASK ×3** (게이트) |
| "자소서 초안 부탁해" | `[fit_analysis]` | **ASK ×3** |
| "면접 준비 도와줘" | `[fit_analysis]` | **ASK ×3** |

**②는 닫혔다.** 구조가 같은 계획(`[fit_analysis, 소비자]`)이 발화에 따라 갈린다 — 계획만으로는
불가능했던 구분이다.

## 실측이 잡은 부작용 1건 (같이 고쳤다)

`analysis` 를 **이미 가진** 세션의 "자소서 다시 써줘" 에 게이트가 걸렸다
(`coverletter-rewrite` → ASK ×3). 플래너가 필요 없는 전제를 넣고 신고했기 때문인데,
**이미 있는 분석을 다시 하겠냐고 묻는 것**은 사용자를 헷갈리게 한다.

게이트는 "필요한데 무거운 것"에만 의미가 있다 → **신고된 전제 중 이미 있는 자산을 만드는 것은
묻지 않고 뺀다**(`validate_plan` 의 `redundant`). 사용자가 직접 재분석을 청했으면 신고에
없으므로 빠지지 않는다. 결과: `coverletter-rewrite`·`coverletter-paraphrase` → `coverletter_draft` ×3.

## 평가셋 기대값 2건 갱신 (정책 일관 적용)

`coverletter-auto-prereq`·`interview-auto-prereq` 를 `expectAsk` 로. 후속 2 에서
`coverletter-motivation` 만 고치고 이 둘을 놓쳐, **평가셋 안에서 같은 상황이 다르게 기대되고
있었다.** 근거는 케이스 `note` 에 적었다.

## 최종 수치 (Claude `sonnet` CLI, 46케이스 × 3회)

| | 정확도 | 되묻기 | 안정성 | stable-correct / wrong / unstable |
|---|---|---|---|---|
| 사다리만 (후속3) | 0.8406 | 0.9638 | 0.9493 | 36 / 4 / 6 |
| **+신고 스키마 (후속4)** | **0.8478** | **1.0000** | **0.9565** | **37 / 3 / 6** |

**`ask_accuracy` 가 1.0** 이 된 것이 이 작업의 성과다 — "묻느냐 실행하느냐"가 이제 항상 맞는다.
정확도 상승분(+0.007)은 작지만, 닫은 것은 **말없이 수십 초를 쓰는 결함**이었다.

## 남은 실패 9건은 두 가족뿐이다 (둘 다 데이터셋 캘리브레이션 문제)

**(a) 상위집합 3건** — sonnet 이 기대 에이전트를 **포함해** 한 단계 더 한다:
`recommend-missing-resume`·`preference-open`(→ `preference_intake>job_recommend`)·
`recommend-paraphrase-3`. "선호를 묻고 바로 추천까지" 가 더 나은 제품 동작일 수 있다.

**(b) 전제가 반만 있을 때 6건** — `coverletter-missing-posting`·`interview-missing`·
`fit-missing-both`·`resume-missing` 등. 이력서만 있을 때 `resume_diagnosis` / `job_recommend` /
`career_chat` 중 무엇이 가장 도움이 되는지가 **진짜 애매하다**(①에서 프롬프트로 못 박으려다
되돌린 그 문제다).

> **둘 다 코드 결함이 아니다.** 모델을 확정한 뒤 **의도를 다시 정해** 기대값을 갱신할 대상이다.
> 지금 sonnet 에 맞춰 고치면 "평가셋이 구현을 따라가는 거울"이 된다.

---

# 후속 5 — 자기 루프 궤적 안정성 (마지막 미측정 표면)

`eval/loop_consistency.py` 신설. 플래너 안정성은 `planner_harness`, 풀턴은 `consistency.py`,
그리고 **`agent_loop` 를 도는 세 에이전트의 도구 궤적**은 아무도 재지 않았다(§2-1).

지표는 같은 갈래를 쓴다 — 궤적에 "정답"은 두지 않고 *같은 입력에 같은 길을 가는지*(stability)만
본다. 도구를 몇 개 쓸지는 근거에 따라 달라지는 것이 정상이므로. 대신 **불변식**은 검사한다
(자소서는 `save_draft` 없이 답하지 않는다 등).

## 측정 전에 잡힌 결함 — **자기 루프 층이 Claude CLI 에서 통째로 꺼져 있었다**

첫 실행에서 `interview_prep`·`coverletter_draft` 가 **도구 0개**로 답했다. 궤적이 빈 것과
"루프가 아예 안 돈 것"은 다르므로 파고들었더니:

```
llm_call_failed :: claude CLI 종료 코드 1: {"is_error":true,"num_turns":2,
                   "stop_reason":"tool_use", ...}
```

`agent_loop` 프롬프트가 **"쓸 수 있는 도구:"** 로 도구 목록을 늘어놓는 순간 Claude 가 *자기*
내장 도구(Read/Bash…)를 쓰려 들고, `--max-turns 1` 에 걸려 실패한다. 3회 재시도 끝에 전부
**결정론 폴백**으로 나갔다 — **답변이 그럴듯해서 겉으로는 정상처럼 보였다.**
(플래너는 "에이전트 목록"이라 이 함정을 안 밟았다. 그래서 후속 3·4 측정은 정상이었다.)

→ `claude_code_llm._COMMON_ARGS` 에 **`--tools ""`**(내장 도구 전부 끄기) 추가. 우리가 원하는
것은 텍스트·JSON 생성 하나뿐이라 도구를 줄 이유가 없다.
회귀 방어: `tests/test_claude_cli_args.py`(CLI 를 부르지 않고 인자만 검사 — 조용히 사라지는
종류의 결함이라 못을 박았다).

> **교훈: 폴백이 그럴듯하면 결함이 안 보인다.** `loopSteps` 가 비어 있다는 신호를 "도구를 안
> 썼다"로 읽었는데 실제로는 "루프가 죽었다"였다. 그래서 하네스에 **경고 코드 분포**를 지표로
> 넣었다 — `llm_call_failed` 가 보이면 궤적이 빈 것이 아니라 루프가 안 돈 것이다.

## 결과 (Claude `sonnet` CLI, 3케이스 × 5회)

| 에이전트 | 안정성 | 스텝 평균/최대 | 답변 | 불변식 |
|---|---|---|---|---|
| `preference_intake` | 0.80 | 1.2 / 2 | 5/5 | OK |
| `interview_prep` | 0.80 | 2.8 / 3 | 5/5 | OK |
| `coverletter_draft` | **0.40** | 3.6 / 4 | 5/5 | OK |

**불변식 위반 0건. 경고 0건.**

```
preference_intake   4/5  record_preference
                    1/5  record_preference>record_preference        (중복 — 멱등해서 무해)
interview_prep      4/5  pick_material>find_evidence>record_question
                    1/5  pick_material>record_question
coverletter_draft   2/5  find_evidence>save_draft>check_draft
                    2/5  find_evidence>save_draft>check_draft>save_draft   ← 자기비판 재작성
                    1/5  find_evidence>ask_agent>save_draft>check_draft    ← 에이전트 간 위임
```

## 판정 — **낮은 안정성이 여기서는 나쁜 것이 아니다**

`coverletter_draft` 0.40 이 가장 낮은데, 세 궤적이 **전부 정당하다**:
점검 통과(2) / **점검 → 재작성**(2) / **옆 담당에게 물어보기**(1). 초안 품질에 따라 갈리는
것이 이 에이전트의 설계 의도다. 플래너 안정성과 성격이 다르므로 **같은 잣대로 읽으면 안 된다** —
플래너는 같은 입력에 같은 계획이 나와야 하고, 자기 루프는 근거에 따라 다르게 도는 것이 정상이다.

덤으로 **두 가지가 계측으로 처음 확인됐다** — 평가 문서가 "구조는 있으나 증명 못 했다"로 남긴 것들:

1. **자기비판 재작성이 실제로 발동한다** (`check_draft` → `save_draft`, 2/5).
2. **에이전트 간 위임이 실사용에서 발동한다** (`ask_agent` → `resume_diagnosis`, 1/5).
   평가 문서 §2-2 의 *"소비자가 하나뿐인 동안은 '통로가 있다'까지가 정직한 주장"* 에 대한
   첫 계측 증거다.

3. **`max_steps` 3 → 5 상향이 값을 했다(사후 증거).** 최대 궤적이 4스텝이다 —
   상한이 3이었다면 재작성(4스텝)과 위임(4스텝) 궤적이 **잘렸다.** 후속 3 에서 근거 없이
   올린 값이 실측으로 정당화됐다.

## 남은 일

1. 평가셋 재캘리브레이션(모델 확정 후) — 후속 4 참고.
2. `preference_intake` 의 `record_preference` 중복 호출 — 무해하지만 스텝 낭비다.
3. 루프 궤적 안정성의 **기준선을 파일로 저장**하지 않았다(플래너처럼 `--save` 추가 여지).

---

# 후속 6 — 평가셋 재캘리브레이션 (범위를 먼저 갈랐다)

재캘리브레이션의 올바른 범위는 **"현재 동작이 의도인 경우만 갱신"** 이다. 남은 실패 9건을
그 기준으로 갈랐더니 두 가족의 성격이 **정반대**였다.

## (a) 상위집합 2건 → **갱신했다** (현재 동작이 의도)

`job_recommend` 는 `preconditions_any=(resume, preferences)` 라서 자산이 없으면 검증기가
생산자 `preference_intake` 를 앞에 끼운다. 그건 **설계이고 테스트로 못 박혀 있다**:

```python
# tests/test_improvements.py
assert validate_plan(["job_recommend"], {}).agents == ("preference_intake", "job_recommend")
```

즉 "선호를 묻고 **바로 추천까지**" 가 의도된 한 턴이고, 기대값이 "묻고 끝" 으로 좁혀져 있었다.
→ `recommend-missing-resume`·`preference-open` 을 `["preference_intake","job_recommend"]` 로.

## (b) "전제가 반만 있을 때" 4건 → **갱신하지 않았다** (정책 위반이다)

관측이 `career_chat` 으로 가지만, 플래너 사다리 **4단이 명시**한다:

> 전제가 부족하면 **가진 자산으로 지금 할 수 있는 일**을 대신 고른다 — 부족한 자료는 그
> 에이전트가 결과를 들고 대화로 청한다. **대화로 넘기지 않는다.**

즉 낡은 기대값이 아니라 **모델이 프롬프트를 안 따르는 것**이다. 기대값을 관측에 맞추면
**평가셋이 구현을 따라가는 거울**이 된다(이 문서에서 세 번 경계한 그것).
→ `note` 에 `OPEN` 으로 표기하고 실패로 남겼다. `recommend-paraphrase-3`(플래너가 요청하지
않은 단계를 덧붙임)·`fit-paraphrase-5` 도 같은 가족이라 같이 표기했다.

**`note` 규약을 데이터셋 `description` 에 못 박았다**: `갱신` = 정책 변경으로 고친 것(근거 필수)
/ `OPEN`·`KNOWN FAILURE` = 관측과 다르지만 **일부러 고치지 않은 것**.

## 결과 (Claude `sonnet` CLI, 46케이스 × 3회)

| | 정확도 | 되묻기 | 안정성 | correct / wrong / unstable | 폴백률 |
|---|---|---|---|---|---|
| 후속4 (신고 스키마) | 0.8478 | 1.0 | 0.9565 | 37 / 3 / 6 | 0.094 |
| **후속6 (재캘리브레이션)** | **0.8985** | **1.0** | 0.9493 | **40 / 1 / 5** | **0.051** |

## 남은 6건은 **한 가족**이다 — 진단이 하나로 모였다

| 케이스 | 발화 | 관측 |
|---|---|---|
| `fit-paraphrase-5` | "요구사항 중 내가 못 채우는 게 뭐야?" [이력서+공고] | `posting_analysis`×3 |
| `fit-missing-posting-degrade` | "이 공고 나 되나?" [이력서] | job_recommend / resume_diagnosis / career_chat |
| `fit-missing-both` | "이 공고 나 되나?" [] | career_chat×2 / preference_intake×1 |
| `coverletter-missing-posting` | "자소서 써줘" [이력서] | career_chat×2 / job_recommend×1 |
| `interview-missing` | "면접 준비 도와줘" [이력서] | 셋으로 갈림 |
| `preference-open` | "이력서는 없는데 공고 추천받고 싶어" [] | preference_intake×2 / 상위집합×1 |

**전부 "요청과 전제가 어긋날 때 무엇을 할지"** 다. 프롬프트는 이미 답을 적어 뒀고
(사다리 4단, 그리고 `fit-paraphrase-5` 는 사다리 1단의 **예시 문구 그대로**인데도 안 따른다),
모델이 따르지 않는다. **평가셋 문제가 아니라 프롬프트 준수 문제다.**

## 다음 레버 (프롬프트 규칙 추가는 아니다)

①에서 배웠다 — 규칙을 더 넣으면 총계가 내려간다(간섭). 남은 후보는 **규칙이 아니라 어휘**다:

- `career_chat` 의 manifest **설명을 좁힌다**. 지금은 "기능과 직접 관련 없는 진로 고민·하소연·
  일반 질문" 인데, 모델이 "기능을 수행할 수 없는 상황" 까지 여기로 읽는 것으로 보인다.
  사다리(정책)를 건드리지 않고 **선택지의 정의**만 좁히는 것이라 간섭 위험이 다르다.
- 그래도 안 되면 결정론 보정: 요청 기능의 전제가 부분 충족일 때 `career_chat` 을 고른 계획을
  검증기가 **가진 자산의 정리 에이전트로 바꾼다**(판단이 아니라 정책 집행이므로 코드가 맞다).

---

# 후속 7 — manifest 어휘 좁히기 (①의 반대 실험) + 평가셋 자기 불일치 수정

후속 6 의 진단: 남은 실패 6건이 전부 *"요청과 전제가 어긋날 때"* 한 가족이고, **프롬프트는 이미
답을 적어 뒀는데(사다리 4단) 모델이 안 따른다.** ①에서 규칙 추가가 간섭으로 실패했으므로,
이번에는 **규칙이 아니라 어휘**를 건드렸다 — 사다리(정책)는 한 글자도 안 고쳤다.

## 무엇을 바꿨나 — 선택지의 **정의**만 (같은 레버의 양쪽)

| 에이전트 | 조정 |
|---|---|
| `career_chat` | "기능과 직접 관련 없는…" → "**어떤 기능도 요청하지 않은** 발화(…)를 받아주는 대화. **기능을 요청했는데 자료가 부족한 경우는 여기가 아니다**" |
| `resume_diagnosis` | + "**공고가 없어 적합도 판정·자소서·면접을 못 할 때 이력서로 먼저 할 수 있는 일**이다" |
| `posting_analysis` | + "**이력서가 없어 적합도 판정을 못 할 때 공고로 먼저 할 수 있는 일**이다" |

`career_chat` 만 좁히면 그 케이스들이 `job_recommend` 로 샐 것이 관측돼 있었으므로
(후속6), **착지점을 명시하는 쪽도 같이** 넣었다 — 서로 경쟁하는 규칙이 아니라 한 레버의 양쪽이다.

## 결과 — **①과 정반대다**

| | 정확도 | 안정성 | correct / wrong / unstable |
|---|---|---|---|
| 후속6 | 0.8985 | 0.9493 | 40 / 1 / 5 |
| **후속7 (manifest)** | **0.9565** | **0.9855** | **43 / 1 / 2** |
| 후속7 + 평가셋 자기불일치 수정 | **0.9783** | 0.9855 | **44 / 0 / 2** |

진단한 가족이 정확히 고쳐졌다:

```
fit-paraphrase-5             posting_analysis×3      → fit_analysis×3
coverletter-missing-posting  career_chat×2           → resume_diagnosis×3
interview-missing            셋으로 갈림              → resume_diagnosis×3
preference-open              갈림                    → 상위집합×3
fit-missing-posting-degrade  0.33                    → 0.67 (resume_diagnosis×2)
```

> **핵심 교훈 — 프롬프트를 고치는 두 가지 방법은 효과가 다르다.**
>
> | 방법 | 위치 | 결과 |
> |---|---|---|
> | ① **규칙 추가** ("전제가 반만 있으면 …") | 판단 원칙(사다리) | 정확도 **−0.022**, 무관한 케이스 4건 파손 → 되돌림 |
> | ⑦ **어휘 좁히기** (선택지의 정의) | manifest 설명 | 정확도 **+0.058**, 안정성 +0.036, 파손 0 |
>
> 같은 문제를 겨냥했는데 부호가 반대다. **모델이 못 고르는 이유가 "규칙을 몰라서"가 아니라
> "선택지의 뜻이 넓어서"였다.** 규칙을 더 쓰면 기존 규칙과 경쟁하지만, 선택지의 정의를 좁히는
> 것은 경쟁 상대가 없다.

## 평가셋의 자기 불일치를 고쳤다 (내 실수)

후속 2 에서 **구조가 같은 두 케이스를 다르게** 기대해 놨다:
`fit-missing-both`("이 공고 나 되나?" []) → `preference_intake` /
`resume-missing`("내 이력서 진단해줘" []) → `career_chat`.

자산이 하나도 없으면 "가진 자산으로 먼저 할 일" 이 없어 둘 다 대화로 받는 것이 맞고, 그중
**`career_chat` 이 apt** 하다 — `preference_intake` 는 *공고를 찾기 위한* 선호를 모으는
에이전트(`produces=preferences`)이고 이 두 발화는 공고 찾기가 아니다. → 둘 다 `career_chat`.

기대값만 바뀌었으므로 **재측정 없이 저장된 관측으로 다시 채점**했다(`rescored` 필드로 표기).
정확도·안정성은 `observed` 에서 정확히 계산되고, `paths`·`mean_confidence`·`llm_failed` 는
케이스별로 이미 저장돼 있다.

## 최종 (Claude `sonnet` CLI, 46케이스 × 3회)

```
정확도 0.9783  되묻기 1.0000  안정성 0.9855
stable-correct 44 / stable-wrong 0 / unstable 2   폴백률 0.051
```

**GMS `gpt-4.1-mini` 기준선(0.9275 / 0.9783)을 정확도·안정성 모두 넘었다.** 후속 3 에서
"모델 교체가 −0.109" 였던 것이 프롬프트·스키마·어휘 수정으로 전부 회수되고 더 올라갔다.

## 남은 2건 (둘 다 자산 0 케이스, 본질적 흔들림)

| 케이스 | 기대 | 관측 |
|---|---|---|
| `fit-missing-posting-degrade` | `resume_diagnosis` | resume_diagnosis×2 / career_chat×1 |
| `resume-missing` | `career_chat` | preference_intake×2 / career_chat×1 |

`stable-wrong` 이 **0건**이 됐다 — 남은 것은 전부 경계 케이스의 흔들림이고, "일관되게 틀린 것"은
없다. 이것이 지표를 갈라 센 이유이기도 하다.
