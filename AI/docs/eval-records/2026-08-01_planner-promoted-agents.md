# 2026-08-01 플래너 재측정 — 정리 도구 2종의 대화형 승격(D97)

**측정**: `python -m jobis_ai.eval.planner_harness evals/planner_dataset.json --runs 3`
**환경**: provider=claude_code(Claude CLI) / 라우팅 티어 = Opus 5(D74) — **GMS 미사용**
(하네스 헤더가 인쇄하는 `model=sonnet` 은 기본 모델 라벨이다. 플래너는 `tier="router"` 로
호출되므로 실제 모델은 `CLAUDE_CODE_MODEL_ROUTER` 다.)
**저장**: `evals/planner_baseline_promoted_agents.json`
**변경분**: `posting_analysis`·`resume_diagnosis` 의 **description(플래너 어휘의 정의)** 이 바뀌었다
— 도구에서 대화형 담당으로 승격(D97). 코드 변경(루프·도구·폴백)은 플래너 입력에 닿지 않고,
어휘에 닿는 것은 이 두 문장뿐이다. 데이터셋은 그대로 48케이스.

## 요약 (비교: planner_baseline_claude_opus_router.json, 같은 48케이스)

| 지표 | 이전 | 1차 | **최종** |
|---|---|---|---|
| sequence_accuracy | 0.9861 | 0.9931 | **1.0** |
| mean_stability | 0.9861 | 0.9931 | **1.0** |
| stable_correct | 46/48 | 47/48 | **48/48** |
| stable_wrong | 0 | 0 | **0** |
| unstable | 2 | 1 | **0** |
| ask_accuracy | 1.0 | 1.0 | 1.0 |
| blocked_accuracy | 1.0 | 1.0 | 1.0 |
| mean_confidence | 0.896 | 0.904 | 0.902 |
| fallback_rate | 0.0 | 0.0 | 0.0 |

## 케이스별 판정 (§3-3 — 총계가 아니라 케이스별로 본다)

**1차 측정에서 총계는 올랐는데 한 건이 깨져 있었다.** 총계만 보고 넘기면 놓치는 자리다.

| 케이스 | 이전 | 1차 | 최종 |
|---|---|---|---|
| `recommend-paraphrase-2` | 불안정 | **1.00** | 1.00 |
| `preference-open` | 불안정 | **1.00** | 1.00 |
| `fit-missing-posting-degrade` | 1.00 | **0.67 (회귀)** | **1.00** |
| 나머지 45건 | 1.00 | 1.00 | 1.00 |

### 회귀의 원인과 처방

`fit-missing-posting-degrade` = 이력서만 있고 공고가 없는 상태에서 적합도 요청 →
기대 `resume_diagnosis`. 1차 관측: `resume_diagnosis`×2 / `career_chat`×1.

원인은 description 편집이다. 승격으로 **능력 서술**(무엇을 할 수 있나)을 늘리면서 기존의
**역할 문장**을 지웠다:

> "**공고가 없어 적합도 판정·자소서·면접을 못 할 때 이력서로 먼저 할 수 있는 일**이다"

그 문장이 정확히 이 케이스의 라우팅 근거였다. **능력과 역할은 다른 정보이고, 둘 다 있어야
한다** — 능력만 적으면 "이 상황에서 이걸 대신 골라라"가 사라진다. 문장을 복원하니 3/3.

짝인 `posting_analysis` 는 승격 문장에 "이력서 없이 가능하다 — 사용자 정보를 요구하지
않는다"를 남겨 뒀고, `fit-missing-resume-degrade` 가 1차부터 1.00 을 유지했다. 대칭 확인.

## 이번 측정이 확인한 것

- **어휘 정의를 넓히는 변경이 라우팅을 깨지 않았다.** §3-1 은 "선택지의 정의를 좁히면
  오른다"를 실측했는데, 이번은 **정의를 정확하게** 만든 경우다(없던 능력을 적은 것이 아니라
  `job_posting`·`resume` 자산으로 원래 답할 수 있던 범위를 적었다). 새 어휘는 0개.
- 승격의 계기였던 실측 케이스("공고 기준으로 무엇을 공부할까")가 **이 시점의 평가셋에 없었다.**
  즉 여기까지의 1.0 은 기존 48케이스에 대한 것이고 승격이 노린 능력은 재지 않았다.
  → **아래 "추가 측정"에서 케이스를 넣고, 그 케이스에 판별력이 있는지까지 확인했다.**

---

## 추가 측정 (같은 날, 평가셋 확장 후) — **케이스의 판별력을 먼저 검증했다**

위 48/48 은 **기존 48케이스에 대한 것**이고 승격이 노린 능력을 재는 케이스가 없었다.
그래서 4건을 추가했다. 다만 추가만으로는 부족하다 — **한 번에 통과한 케이스는 그것만으로
아무것도 증명하지 않는다.** 승격 전 description 으로도 통과하면 그 케이스는 승격을 재는 게
아니라 구현을 따라가는 거울이다(§3-5).

그래서 새 케이스마다 **승격 전 description 을 주입해 다시 돌렸다**(`get_agent_registry` 를
감싸 두 담당의 description 만 D97 이전 문구로 되돌리고 하네스를 그대로 태웠다).

| 케이스 | 자산 | 승격 전(주입) | 승격 후 | 판별력 |
|---|---|---|---|---|
| `posting-study-plan` | resume + job_posting | **ASK 3/3** — `fit_analysis` 를 끼워 "수십 초 걸리는데 진행할까요?" | `posting_analysis` 3/3 | **있음** |
| `posting-study-plan-with-analysis` | resume + job_posting + analysis | **`application_plan` 3/3** | `posting_analysis` 3/3 | **있음** |
| `posting-detail-question` | job_posting | `posting_analysis` 3/3 | `posting_analysis` 3/3 | 없음(회귀 고정) |
| `resume-strengths-with-posting` | resume + job_posting | `resume_diagnosis` 3/3 | `resume_diagnosis` 3/3 | 없음(회귀 고정) |

### 이 검증이 바로잡은 것

**처음 만든 `posting-study-plan` 은 자산이 `["job_posting"]` 뿐이었고 판별력이 0 이었다.**
승격 전 어휘로도 3/3 통과했다. 원래 로그를 다시 읽어 보니 실패한 턴의 자산은
`['history', 'job_posting', 'last_message', 'posting_library', 'posting_summary', 'resume']`
— **이력서가 있었다.** 공고만 있는 상황은 애초에 라우팅이 맞던 쪽이고, 갈림길은 이력서가
있을 때다(그때 플래너가 무거운 판정으로 끌려간다). 자산을 실제 실패 상황으로 바꾸니
판별력이 생겼다.

판별력이 없는 두 건은 **없다고 데이터셋 `note` 에 적어 뒀다.** 지우지 않은 이유는 다음에
description 을 좁히는 사람이 이 라우팅을 깨지 않게 잠가 두는 값이기 때문이다 — 다만
"승격이 검증됐다"의 근거로 세면 안 된다.

### 여전히 못 재는 것 (솔직하게)

`posting-detail-question` 이 승격 전에도 통과했다는 사실이 가리키는 것: **승격이 바꾼 큰
부분은 라우팅이 아니라 답의 내용이다.** 같은 담당에게 갔어도 승격 전에는 요약만 냈고 지금은
학습 순서·프로젝트를 답한다. 그 차이는 플래너 하네스가 원리적으로 못 잰다 — 답변 품질을
재는 하네스가 따로 필요하다(외부 리뷰가 제안한 **제네릭 점수**: 서로 다른 공고에 같은 답이
나오면 감점, 출력 간 코사인 유사도로 자동 측정). 다음 작업으로 남긴다.

## 최종 (52케이스 × 3회, 2026-08-01T19:20)

| 지표 | 값 |
|---|---|
| sequence_accuracy | **1.0** |
| mean_stability | **1.0** |
| stable_correct | **52/52** |
| stable_wrong / unstable | **0 / 0** |
| ask_accuracy · blocked_accuracy | 1.0 · 1.0 |
| mean_confidence | 0.901 |

## 재현

```bash
# 공식 baseline
uv run --extra prototype python -m jobis_ai.eval.planner_harness \
    evals/planner_dataset.json --runs 3 --save evals/planner_baseline_promoted_agents.json

# 판별력 확인(승격 전 description 주입) — 스크립트는 세션 산출물이라 저장하지 않았다.
# get_agent_registry 를 감싸 posting_analysis·resume_diagnosis 의 description 만
# `git show <D97 커밋>^:AI/src/jobis_ai/agents/__init__.py` 의 문구로 replace 한 뒤
# run_dataset(부분셋, runs=3) 을 호출하면 위 표가 재현된다.
```
