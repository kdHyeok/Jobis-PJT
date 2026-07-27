# LLM 플래너 전환 설계 — 표 라우팅 → capability manifest 기반 에이전트 선택 (2026-07-24)

> 팀 결정: 오케스트레이터가 (의도 × 자산) 대응표로 에이전트를 확정하는 방식에서,
> **"이러한 에이전트들이 있다"를 LLM에게 알려주고 LLM이 직접 호출할 에이전트를 고르는**
> 방식으로 전환한다. 멀티에이전트 구조의 핵심(에이전트 선택의 자율성)을 오케스트레이터에 부여한다.

---

## 1. 배경과 결정

### 기존 (중간회고 §3.3)

```
발화 → 의도분류 LLM(7라벨만) → 라우팅 대응표(순수 파이썬) → 에이전트 실행
```

- LLM의 자율성은 "라벨 번역"까지. 어떤 에이전트를 부를지는 표가 확정.
- 장점: 라우팅 전수 테스트 18케이스. 단점: 표에 없는 조합 불가, 새 에이전트 추가 시 표 수정 필요,
  "멀티에이전트를 LLM이 조율한다"는 구조적 정체성이 약함.

### 신규 (이 문서)

```
발화 + 세션 자산 상태 + 에이전트 목록(capability manifest)
   → 플래너 LLM: 호출할 에이전트를 직접 선택 (스키마로 선택지 제한)
   → 검증기(순수 파이썬): 전제조건 검사 · 전제 에이전트 자동 삽입 · 불가 시 되묻기
   → 에이전트 실행 (기존과 동일)
```

- LLM 자율성이 "라벨 번역"에서 **"에이전트 선택"으로 승격** — 회고 §6-12의
  tool-calling 플래너를 앞당기되, 하네스는 유지한다.

## 2. 유지하는 하네스 원칙 (변하지 않는 것)

| 원칙 | 구현 |
|---|---|
| 줄 수 없는 답은 스키마에서 뺀다 | 플래너 출력은 `agents: list[Literal[등록된 6개 이름]]` + confidence뿐. 존재하지 않는 에이전트 호출(환각)은 **Pydantic 검증 단계에서 구조적으로 불가능** |
| 판단의 위치 분리 | LLM은 "무엇을 부를지"만 고른다. **부를 수 있는지(전제조건)와 순서 보정은 코드 검증기**가 확정 |
| 전수 테스트 가능성 | 검증기 `validate_plan()`은 순수 함수 — (선택 에이전트 × 자산) 조합 전수 테스트로 기존 라우팅 표 테스트를 대체 |
| 실패의 정직한 처리 | 플래너 LLM 실패·미설정 시 **기존 경로(키워드 의도분류 + 대응표)로 폴백** — 표는 삭제하지 않고 폴백으로 강등. 테스트는 LLM 없이 기존과 동일하게 돈다 |
| 저신뢰 되묻기 | `confidence < 0.6`(기존 상수 재사용) 또는 빈 선택이면 실행 대신 되묻기 |
| 라우팅 가시화 | 검증기가 note 생성("~를 실행할게요"), ChatResponse에 dispatched 노출 — 오선택을 사용자가 정정 가능 |

## 3. 컴포넌트 설계

### 3.1 `orchestrator/planner.py` (신규)

- `AgentName = Literal["fit_analysis", "job_recommend", "resume_diagnosis", "interview_prep", "coverletter_draft", "roadmap_manager"]`
- 출력 스키마 `AgentPlan`:
  ```python
  class AgentPlan(BaseModel):
      agents: list[AgentName] = []      # 호출할 에이전트 — 목표만, 전제 삽입은 검증기
      target: str = ""                  # 발화 속 대상 참조 (추측 금지)
      confidence: float = 0.0           # 선택 확신도
  ```
  판단 필드(적합도·조언 등) 없음 — IntentRead와 같은 전략.
- 시스템 프롬프트는 **레지스트리에서 동적 생성**: 각 `AgentSpec`의 name/description/preconditions를
  나열. 에이전트 추가 시 레지스트리만 고치면 플래너가 자동 인지 — 표 수정 불필요.
- 사용자 컨텐츠에 **세션 자산 상태**(이력서 있음/없음, 공고 있음/없음, 분석·로드맵 보유 여부)를 주입 —
  "사용자 상태는 이력서·공고의 있고 없음으로 분류"를 프롬프트 컨텍스트로 제공.
- LLM 실패·미설정 → `None` 반환 (호출부가 기존 경로로 폴백).

### 3.2 `agents/__init__.py` — `AgentSpec.produces` 추가

각 에이전트가 세션에 **만들어 넣는 자산**을 선언한다. 검증기가 전제 자동 삽입 시
"fit_analysis를 먼저 실행하면 analysis가 생긴다"를 하드코딩 없이 추론하는 근거.

| 에이전트 | preconditions | produces |
|---|---|---|
| fit_analysis | resume, job_posting | analysis, roadmap |
| job_recommend | resume | recommendations |
| resume_diagnosis | resume | — |
| interview_prep | analysis | — |
| coverletter_draft | resume, analysis | coverletter |
| roadmap_manager | roadmap | — |

### 3.3 `router.py` — `validate_plan()` (신규 함수, 기존 `route()` 유지)

순수 결정론. LLM이 고른 시퀀스를 받아:

1. 중복 제거(순서 유지) 후, 각 에이전트의 preconditions를 **자산 시뮬레이션**으로 검사
   (실행하면 produces가 자산에 추가된다고 가정).
2. 결측 자산이 **다른 에이전트의 produces로 채워질 수 있으면 그 에이전트를 앞에 자동 삽입**
   (예: analysis 결측 + resume·job_posting 보유 → fit_analysis 삽입). 기존 ⊕ 합성의 일반화.
3. 삽입으로도 못 채우면 실행하지 않고 되묻기 — 기존 ASK_RESUME/ASK_POSTING/ASK_NO_ROADMAP 재사용.
4. 통과 시 최종 실행 시퀀스 + 가시화 note 반환 (`Dispatch` 재사용).

기존 `route()`는 삭제하지 않는다 — LLM 미설정 폴백 경로가 그대로 사용.

### 3.4 `chat.py` — 흐름 변경

```
1) plan_agents(message, session)  ← 플래너 LLM
2-a) 플랜 성공: 저신뢰/빈 선택 → 되묻기 / 아니면 validate_plan() → 실행
2-b) 플랜 실패(LLM 미설정 등): classify_intent() + route()  ← 기존 경로 그대로 (폴백)
3) 실행 루프는 변경 없음 (dispatch only, followUpQuestions 시 중단)
```

`ChatResponse.intent`에는 플래너 경로일 때 첫 선택 에이전트 이름을 실어 가시화를 유지한다.

## 4. 테스트 전략

| 대상 | 방법 |
|---|---|
| `validate_plan()` | (선택 시퀀스 × 자산) 전수 parametrize — 전제 자동 삽입·되묻기·중복 제거 포함 |
| `AgentPlan` 스키마 | 미등록 에이전트 이름이 ValidationError로 거부되는지 |
| 폴백 경로 | conftest가 LLM을 강제 차단하므로 **기존 테스트 전부가 폴백 경로 회귀 테스트**가 됨 — 수정 없이 통과해야 함 |
| 플래너 실측 | 기존 계획(회고 §6-1)의 의도분류 평가셋을 "에이전트 선택 평가셋"으로 승격 — 발화 30~50개 × 기대 에이전트 시퀀스 |

## 5. 마이그레이션 단계

1. `AgentSpec.produces` 추가 (기존 코드 무영향)
2. `router.validate_plan()` 추가 + 전수 테스트 (기존 `route()` 무변경)
3. `planner.py` 신규 + 스키마 테스트
4. `chat.py` 플래너 우선 + 폴백 배선 — 기존 테스트 전체 통과 확인
5. 실 LLM 평가셋으로 선택 정확도 측정 → 안정되면 문서(`agent-structure-current.md`,
   `AI중간회고.md` §3.3) 갱신

## 6. 리스크와 트레이드오프 (정직하게)

- **비결정 지점이 1곳(의도분류) → 여전히 1곳(플래너)**이지만, 출력 공간이 7라벨에서
  "에이전트 시퀀스"로 넓어져 오선택 표면적이 커진다. → 검증기 + 평가셋 + 가시화(정정 가능)로 상쇄.
- 플래너 프롬프트가 레지스트리 설명 품질에 의존한다. description이 곧 라우팅 정확도 —
  에이전트 추가 시 설명을 신중히 쓸 것.
- 회고 §3.3("dispatch만, judge 금지")의 서사 수정 필요: "LLM은 여전히 판정하지 않는다.
  선택하되, 선택의 실행 가능 여부는 코드가 확정한다"로 갱신.
