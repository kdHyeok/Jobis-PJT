# 2026-07-31 플래너 재측정 — blockedRequests(D72) + 혼합 제출 케이스(M8)

**측정**: `python -m jobis_ai.eval.planner_harness evals/planner_dataset.json --runs 3`
**환경**: provider=claude_code(Claude CLI) / model=sonnet / temperature=0.3 — **GMS 미사용**
**저장**: `evals/planner_baseline_claude_blocked.json`
**변경분**: 플래너 스키마 `blockedRequests` + 판단 원칙 4 한 문장(D72) /
데이터셋 46→48케이스(mixed-submit-fit-explicit·implicit, D69·D71 실측 재현) /
하네스가 제출 그라운딩(D66)·정리 삽입(D71)을 프로덕션과 **같은 함수**로 따라감 /
`expectBlocked` 신고 정확도 분리 채점.

## 요약 (비교: planner_baseline_claude_requested.json, 46케이스)

| 지표 | 이전 | 이번 |
|---|---|---|
| sequence_accuracy | 0.9783 | 0.9653 |
| mean_stability | 1.0 | 0.9861 |
| stable_correct | 45/46 | 45/48 |
| stable_wrong | 1 | 1 |
| unstable | 0 | 2 |
| **blocked_accuracy (신규, 2케이스)** | — | **1.0** |
| 신규 혼합 케이스 2건 | — | 둘 다 stable-correct |

## 케이스별 판정 (§3-3: 총계가 아니라 케이스별)

- **개선/신규 정답**: mixed-submit-fit-explicit·implicit 3/3 (실측 사고 시나리오 고정),
  fit-missing-*-degrade 의 blocked 신고 3/3(=blocked_accuracy 1.0).
- **불변(기존 결함)**: resume-missing stable-wrong — 이전 기준선에서도 동일 관측
  (preference_intake×3, 기대 career_chat). **이번 변경의 회귀가 아니다.** D72 관점에서는
  preference_intake+신고가 career_chat 보다 나은 행동일 수 있어 기대값 재검토 후보로 남긴다(OPEN).
- **flaky 전환 2건**: recommend-paraphrase-3(0.67 — 1회 resume_diagnosis),
  preference-open(0.67 — 1회 후속 추천 생략). 둘 다 경계 발화의 온도 흔들림(unstable)이며
  stable-wrong 이 아니다 — 처방은 프롬프트가 아니라 발화 정의 좁히기 또는 온도(§3-3).

**결론**: 프롬프트 한 문장의 비용은 flaky 2건(3회 중 1회 이탈), 이득은 신고 정확도 1.0과
사고 시나리오 회귀 고정. 채택한다.
