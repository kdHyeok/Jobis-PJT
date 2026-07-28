# 06. analyze_gap (갭분석) 🎯 핵심 툴 — 결정론 우선(차용판)

- **선행:** 01 (GapResult·ToolError) · 02 (get_structured_llm) · 03 (profile) · 04 (Posting)
- **참조:** AGENTS §5.1 · §4.1 · §7 · 정본 §4.1 · **[참고] 아류 프로젝트 `gap_matcher`(아이디어 차용, 통째 포팅 아님)**
- **상태:** ✅ 완료 (2026-07-27)

## 목표
이력서(profile)와 공고를 비교해 **지원 가능성을 상/중/하로 산출**하는 핵심 툴. 출력 `level`이 agent 분기(§5.3) 트리거. **프로토타입 데모용 — 어떤 로직이든 걸러져 상/중/하가 나오면 됨.**

## 차용 원칙 (아류 `gap_matcher`에서, 우리 스택에 적응)
1. **판단은 결정론 우선** — 스킬 매칭은 **룰(LLM 없이)**. LLM은 ① 요건 추출 + ② 서술형 요건 폴백만.
2. **`uncertain` ≠ `not_met`** — 판정 못 한 요건은 "부족"이 아니라 "판정 불가". **score 분모에서 제외**(모르는 걸 0점 처리 안 함), missing_required에도 안 넣음.
3. **기재된 스킬 인정** — profile.skills에 있으면 근거 없어도 보유로 인정(사용자가 직접 적음).
> ※ 통째 포팅 안 함: taxonomy·연차사다리·domain_keyword·skillEvidence 등 리치 요소는 **범위 밖**(아류 프로젝트/고도화). 간단 정규화 매칭부터.

## 처리 파이프라인
```
profile + 공고(detail_text)
 → ① [LLM/mid]     detail_text → 요건 리스트 추출 [{text, type: required/preferred}]
 → ② 각 요건 판정:
      (a) [룰]     요건 text에 profile 스킬 토큰이 있으면 → met
      (b) [LLM/strong 폴백] 룰로 못 잡은 요건(서술형) 묶어 1회 판정 → met / not_met / uncertain
 → ③ [알고리즘]    가중치 합산(uncertain 제외) → score → level(상/중/하)
 → GapResult
```

## 재사용 자산 (신규 작성 금지)
| 용도 | 재사용 대상 |
|---|---|
| 출력 스키마 | `schemas/GapResult` (+ `uncertain` 필드 추가 — 아래) |
| 에러 봉투 | `schemas/ToolError` (INSUFFICIENT_INPUT) |
| LLM 창구 | `llm.get_structured_llm("mid"/"strong", ...)` |
| 입력 | `schemas/UserProfile`·`Posting` |

## ⟨확인 필요⟩ 결정
**1. `GapResult`에 `uncertain: list[str] = []` 추가** (task 01 스키마 소폭, 하위호환) — uncertain을 숨기지 않고 노출(차용 원칙 2 존중). matched/missing과 별개.
**2. 채점** (uncertain 제외, partial 생략해 단순화):
```
decided = 요건 중 status ∈ {met, not_met}   (uncertain 제외)
status_score: met=1.0, not_met=0.0    /    type_weight: required=1.0, preferred=0.5
score = Σ(status_score × weight) / Σ(weight)         over decided
level: score ≥ 0.70 → 상 / 0.40~0.70 → 중 / < 0.40 → 하
```
**3. 엣지** — decided 0개(전부 uncertain/요건 없음) → level **중**(판정불가 중립) + rationale 명시.

## 작업 항목
### `tools/analyze_gap.py`
- [x] **내부 스키마**(모듈 로컬): `_Requirements{required[], preferred[]}`, `_Fallback{statuses:[met/not_met/uncertain]}`
- [x] `analyze_gap(profile, posting) -> GapResult | ToolError`
  - [x] 입력 검증: `detail_text` 없음 or profile 로드베어링 전부 빔 → `ToolError(INSUFFICIENT_INPUT)`
  - [x] ① `get_structured_llm("mid", _Requirements)` — 요건 추출
  - [x] ② (a) 룰 매칭: profile 스킬 토큰(skills.name + projects.techStack, 정규화) ∈ 요건 text → met
  - [x] ② (b) 나머지 요건 → `get_structured_llm("strong", _Fallback)` 1회 → met/not_met/uncertain
  - [x] ③ 채점 → GapResult 조립 · **raise 금지**
- [x] `schemas/tool_io.py` GapResult += `uncertain`
- [x] `tools/__init__.py`에 `analyze_gap` 추가

## 완료 기준 (DoD)
- [x] `analyze_gap(profile, posting)` → `GapResult` (score float, level ∈ {상,중,하})
- [x] **level 변별**: 프론트 공고 → 상(0.727) / 백엔드 공고 → 중(0.429)
- [x] `missing_required`가 실제 공고 요건 문자열 · uncertain은 missing에 **안 섞임**
- [x] **INSUFFICIENT_INPUT**: detail_text 없는 공고 → `ToolError(...source="analyze_gap")`, 크래시 없음
- [x] 반환 `GapResult | ToolError` (raise 안 함)

## 주의
- **LLM 2회**(mid 추출 + strong 폴백) = 크레딧. DoD 2~3케이스 최소.
- **품질(매칭 정확도)은 판정 대상 아님** — 상/중/하가 걸러져 나오는 **구조**만. 정교화는 고도화(아류 엔진 교체 여지).
- 룰 매칭은 **간단 토큰 substring**(taxonomy 없음). 놓치는 건 LLM 폴백이 일부 보완.
- **범위: 이 툴만.** level→분기는 task 07.

---
↓ 이하는 **구현 후에** 채운다 ↓

## 검증 메모 (2026-07-27)
- ✅ **level 변별** (실제 LLM, 이서현 profile):
  - 프론트 공고(서울이동통신) → **score 0.727, level 상**. matched_required=React/TS·CSS/HTML/JS(룰), missing=경력2년(신입이라 정당), uncertain 2
  - 백엔드 공고(코콤) → **score 0.429, level 중**. matched=REST API, missing=Java&Spring·C/C++ TCP, uncertain 5
  - → 프론트 지원자에게 프론트(상) > 백엔드(중) 정확히 변별
- ✅ **uncertain 분리**: 판정불가(2·5건)가 missing_required에 안 섞임 (차용 원칙 2 작동)
- ✅ **룰 매칭이 실제 스킬 포착**(React/TypeScript/REST) + LLM 폴백이 서술형(경력·Java) 판정
- ✅ **INSUFFICIENT_INPUT**: detail_text 없음 → `ToolError(...source="analyze_gap")`
- 💳 LLM 2회(mid 추출 + strong 폴백) × 케이스
- 📦 산출: `tools/analyze_gap.py`, `schemas/tool_io.py`(GapResult += uncertain)

## 구현 메모 — 채택 방식 결정 (계획과 다르게 간 경우만)
- **결정론 우선 차용판**: 스킬 매칭=룰(토큰 substring, taxonomy 없이) / LLM은 요건추출·서술형 폴백만. 원래 "LLM 2번 매칭" 계획보다 신뢰성↑·크레딧↓.
- **partial 생략**(met/not_met만) — 프로토타입 단순화. `_MET_EVIDENCE_RATIO` 등 아류 엔진의 정교함은 고도화 여지.
- **uncertain 노출**: GapResult에 `uncertain` 필드 추가(하위호환) → 판정불가를 숨기지 않음.
