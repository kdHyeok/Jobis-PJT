# 2026-07-29 (밤) — LLM 사용량 계측 첫 실측 + confidence 필수화 A/B

> 대상 결정: D59(콜·토큰 수집기) · D60(confidence 필수 필드).
> 프로바이더 **GMS `gpt-4.1-mini`**(고급) / `gpt-4.1-nano`(경량), temperature 0.3.
> 원본: `evals/loop_baseline.json` · `evals/consistency_baseline.json` ·
> `evals/planner_baseline.json`(재측정) · `evals/planner_ab_confidence_default.json`(A/B 대조군).
> 모든 저장 파일에 `meta`(provider·model·measuredAt)가 맨 앞에 있다(D58).

## 1. 자기 루프 — 콜·토큰·상한도달·hand-off (3케이스 × 5회)

`python -m jobis_ai.eval.loop_consistency --runs 5 --save evals/loop_baseline.json`

| 에이전트 | 안정 | 답변 | 스텝(평균/최대) | 콜 평균 | 토큰 평균(입→출) | 특이 |
|---|---|---|---|---|---|---|
| preference_intake | 1.00 | 5/5 | 1.0 / 1 | 2.0 | 2,159→84 | — |
| interview_prep | 0.80 | 5/5 | 2.6 / 5 | 3.6 | 3,223→106 | **상한 도달 1/5** |
| coverletter_draft | 0.60 | 5/5 | 4.0 / 5 | 5.0 | 7,422→493 | 재작성 루프 발동, `check_unresolved`×1 |

- 불변식 위반 0. 궤적 흔들림은 재작성 횟수 차이(자소서 3~5스텝)가 전부다.
- **hand-off 시도 0건 → 성공률 미정의.** 직전 기록의 "위임 1/5"는 Claude sonnet 기준이었다.
  gpt-4.1-mini 는 5회 중 한 번도 `ask_agent` 를 고르지 않았다 — **위임 발동 자체가 모델
  의존**임이 분모가 생기고서야 보였다. 0% 로 적지 않는다(시도가 없으면 비율이 없다).

## 2. 풀턴 — 턴당 콜·토큰 (7케이스 × 3회, confidence 필수화 후)

`python -m jobis_ai.eval.consistency --runs 3 --save evals/consistency_baseline.json`

**턴당 콜 평균 2.8 · 토큰 평균 4,347→301.** 케이스별 콜 2.0(대화)~4.3(동의게이트·다단),
토큰 3.3k~5.5k. 일관성 6/7 (이탈 2건 전부 S5 — 아래 §4).

프로토타입 비교분석 §2-6 이 "미확정"으로 남긴 콜 수 비교가 처음 성립한다:
프로토타입 3~4콜/턴(추정) vs 본체 **2.8콜/턴(실측)** — 멀티에이전트가 콜 수에서 더 비싸지
않다. 판단 계층이 LLM 0회라서다.

## 3. confidence 필수화 A/B (46케이스 × 3회 × 2)

계기: 풀턴 일관성이 6/7 → 3/7 로 무너진 것을 새 계측이 잡았다. S4 재현 5회에서 플래너가
`resume_diagnosis` 를 5/5 정확히 고르면서 confidence 를 3/5 회 0.00 으로 내 career_chat 후퇴.

| | 아침 baseline | 밤, 구 스키마(같은 코드) | 밤, **confidence 필수** |
|---|---|---|---|
| sequence_accuracy | 0.9275 | 0.3913 | **0.8623** |
| ask_accuracy | 1.00 | 0.913 | **1.00** |
| mean_stability | 0.9783 | 0.8623 | **0.9928** |
| stable_correct / wrong / unstable | 41 / 2 / 3 | 11 / 18 / 17 | 39 / 6 / **1** |
| fallback_rate | (미계측) | 0.5652 | **0.0217** |
| mean_confidence | (미계측) | 0.393 | **0.885** |

- **같은 코드가 아침(0.9275)과 밤(0.3913)에 달랐다** — GMS 모델 거동 드리프트.
  baseline 은 코드만이 아니라 모델 거동에도 물려 있다.
- 필수화 직후 단건 재현 10/10 confidence 0.9. 부수 효과로 `requestedAgents` 도 일관되게 채워짐.
- **stable-wrong 6 중 4건**(`fit-missing-both`·`recommend-missing-resume`·`preference-open`·
  `interview-with-analysis`)은 `preference_intake` 과선택 패턴으로 **구 스키마 A/B 에서도
  동일** — 이 변경과 무관한 당일 드리프트다. 기대값을 고치지 않고 OPEN 으로 남긴다.
  나머지 2건은 기존 KNOWN(`fit-missing-posting-degrade`)·OPEN(`resume-missing`).

## 4. S5 동의 게이트 — D50 잔여의 실측 형태

"자소서 써줘"(이력서·공고 보유) 3회: 게이트가 물은 것 **1회**, 나머지 2회는 플래너가
`fit_analysis` 를 `requestedAgents` 에 신고해(사용자는 자소서만 청했다) 게이트를 통과했다.
D50 이 "실 LLM ask_accuracy 재측정"으로 남겨 둔 항목의 실측 형태다 — planner_harness 의
ask_accuracy 1.00 과 풀턴의 1/3 이 갈리는 것은, 하네스 되묻기 케이스에는 "전제 신고를
정직하게 하는가"를 보는 입력이 없어서다. 기대값은 고치지 않는다(KNOWN FAILURE 유지).
