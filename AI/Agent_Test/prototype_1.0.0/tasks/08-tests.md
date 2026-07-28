# 08. 성공판정 테스트 정형화

- **선행:** 01~07 (전 부품)
- **참조:** design.md §8(성공판정 5기준) · AGENTS §8 · D11·D12
- **상태:** ✅ 완료 (2026-07-27)

## 목표
수동으로 검증한 **성공판정 5기준 + 6시나리오 + 실패 케이스**를 **반복 실행 가능한 검증 셋**으로 정형화. `python -m tests.checks` 한 번에 자동 판정 (매번 손으로 안 돌리게).

## 재사용 자산 (신규 작성 금지)
| 용도 | 재사용 대상 |
|---|---|
| 검증 대상 | `agent.run_agent` · `tools/*` · `schemas/*` (01~07) |
| profile | `parse_resume(docx)` (라이브) / 인라인 예시 (결정적) |
| 판정 재료 | `RunAgentResult.meta`(tools_called·level) |

## ⟨확인 필요⟩ 결정 3개
**1. 도구**: **플레인 스크립트**(추천 — 의존성 X, PASS/FAIL 출력) vs pytest(표준, dep 추가).
**2. LLM 비결정성·크레딧 처리 = 2층 분리** (추천):
- **결정적 체크**(무료·항상): route_after_tools·채점 임계치·스키마·load_posting·search_postings
- **라이브 체크**(실 LLM·`--live` 플래그, on-demand): `run_agent` 몇 케이스 → 구조 불변식
**3. 라이브 assert 수준**: **구조 불변식만** (`search 발동 ⟺ level 중/하` / 크래시 없음 / max_steps). **문자열·품질 assert 금지**(비결정성).

## 작업 항목
### `tests/`
- [x] `tests/checks.py` — 진입점 `python -m tests.checks [--live]`, PASS/FAIL 요약 출력
- [x] **결정적 체크** (크레딧 0):
  - `route_after_tools`: 상→agent / 중·하→auto_search (기준 2·3 코어)
  - `analyze_gap` 채점: score→level 임계치(0.70/0.40), uncertain 제외 (task 06)
  - 스키마: `GapResult.level` Literal 거부, 실 공고 → `Posting` 파싱
  - `load_posting`: 실 url→`Posting` / 없는 url→`NOT_FOUND`(기준4 코어)
  - `search_postings`: 0건→`[]` / top_k=3 / score 내림차순 / match_reason 3필드
- [x] **라이브 체크** (`--live`, 실 LLM):
  - 기준1: S3(이력서+공고URL) → `analyze_gap` in tools_called
  - 기준2·3: 불변식 `search 발동 ⟺ level 중/하`
  - 기준4: 없는 URL → 크래시 없이 안내
  - 기준5: 모든 케이스 max_steps 이내 (정상 종료)
- [x] `tests/__init__.py`

## 완료 기준 (DoD)
- [x] `python -m tests.checks` → **결정적 체크 전부 PASS** (크레딧 0, 빠름)
- [x] `python -m tests.checks --live` → **라이브 구조 불변식 PASS**
- [x] 5기준·6시나리오 커버 (체크 목록으로 확인)
- [x] PASS/FAIL 요약이 명확 (몇 개 통과/실패)

## 주의
- **라이브 = 실 LLM = 크레딧·비결정성.** 기본은 결정적만, `--live`는 on-demand.
- **품질(추천 적합도·매칭 정확도) 판정 안 함** — 구조만 (design.md §8 원칙).
- 라이브가 비결정성으로 가끔 흔들릴 수 있음(기준1 LLM 의존) → 불변식 위주로 완화.

---
↓ 구현 후 채움 ↓
## 검증 메모 (2026-07-27)
- ✅ `python -m tests.checks` → **결정적 15/15 PASS** (크레딧 0): 조건엣지(상/중/하)·채점 임계치·스키마 Literal·load_posting(실url/NOT_FOUND)·search_postings(top_k·정렬·3필드·0건)
- ✅ `python -m tests.checks --live` → **라이브 4/4 PASS**: 기준1(analyze_gap 호출)·기준2·3(불변식 search⟺중/하)·기준4(없는 URL 크래시X)·기준5(max_steps)
- ✅ **총 19/19** — 5기준 + 6시나리오 구조 커버
- 📦 산출: `tests/{checks,__init__}.py` + `tools/analyze_gap.py`(`_level_of` 추출)

## 구현 메모 — 채택 방식 결정
- **플레인 스크립트** 채택(pytest 아님): 의존성 0, `python -m tests.checks`로 PASS/FAIL 출력.
- **2층**: 결정적(무료·항상) + 라이브(`--live`·실LLM). 크레딧·비결정성을 라이브로 격리.
- 라이브 assert = **구조 불변식만**(문자열·품질 X — 비결정성 대응).
- 소폭 리팩터: `analyze_gap._level_of(score)` 추출 → 임계치 결정적 테스트 가능.
- Windows 콘솔: `sys.stdout.reconfigure(utf-8)`로 이모지·한글 크래시 방지.
