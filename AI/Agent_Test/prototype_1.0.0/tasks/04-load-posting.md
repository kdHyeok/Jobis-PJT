# 04. load_posting (공고 URL로 DB 조회)

- **선행:** 01 (Posting·ToolError 스키마)
- **참조:** AGENTS §4.1(툴 계약) · §7(NOT_FOUND) · §2.2(공고) · 정본 §4.3 · **D10**
- **상태:** ✅ 완료 (2026-07-27)

## 목표
공고 URL로 로컬 공고 DB(샘플 JSON)에서 공고 1건을 조회하는 **첫 툴**을 만든다. **조회만**(가공·구조화 안 함). 없는 URL은 크래시 없이 `NOT_FOUND` 반환. LLM 안 씀 = **결정적 툴**.

## 재사용 자산 (신규 작성 금지)
| 용도 | 재사용 대상 |
|---|---|
| 공고 스키마 | `schemas/Posting` (task 01) |
| 에러 봉투 | `schemas/ToolError` (task 01) |
| 공고 DB(샘플) | `sample_data/db내 공고파일/*.json` (jobkorea·wanted) |

## ⚠️ 선행 검증 게이트
- [x] **url 필드가 조회 키로 유효** → **통과**: 총 2,053건 **전부 url 유니크**(중복 0, null 0). url = 완벽한 조회 키.

## 확정된 설계 결정 (D10)
1. **반환 타입 = `Posting`** (dict 아님). 설계는 미결정이었고 이번에 확정 — 파이프라인 Pydantic 일관·타입 안전. `.model_dump()`로 dict 복원 가능.
2. **URL 정확 일치** (정규화는 백로그).

## 작업 항목
### `tools/` 첫 툴
- [x] `tools/load_posting.py`
  - [x] `_load_db() -> dict[str, dict]` : 두 JSON 로드 → `{url: 공고}` 인덱스 (모듈 레벨 1회 캐시)
  - [x] `load_posting(url) -> Posting | ToolError` : 조회 → `Posting` / 없으면 `ToolError(NOT_FOUND)`
  - [x] **raise 금지** — `ToolError(error, source, detail)` 반환
- [x] `tools/__init__.py`

## 완료 기준 (DoD)
- [x] `load_posting(실제 url)` → **`Posting` 반환**, 핵심 필드(title·company·url) 원본과 일치
- [x] `load_posting(없는 url)` → **`ToolError(error="NOT_FOUND", source="load_posting")`**, 크래시 없음
- [x] 반환이 `Posting | ToolError` (raise 안 함)
- [x] 스모크: 2케이스 크래시 없이 완료

## 주의
- **DB = 샘플 JSON.** 데이터팀 실제 DB 연동은 범위 밖(계약 동일).
- **URL 정확 일치**(정규화는 백로그).
- **조회만** — 가공·구조화 안 함. `need_ocr` 필터도 안 함(순수 조회) → 사용성 판단은 analyze_gap/agent 몫.
- **범위: 이 툴만.** agent 루프에서의 호출은 task 07.

---
↓ 이하는 **구현 후에** 채운다 ↓

## 검증 메모 (2026-07-27)
- ✅ **게이트**: 공고 2,053건(jobkorea 1300+wanted 753) 전부 url 유니크(중복 0·null 0) → dict 인덱스 조회 안전.
- ✅ **DoD**:
  - 실제 url(jobkorea 49494618) → `Posting` (title·company·need_ocr='O' 등 원본 그대로)
  - 없는 url → `ToolError(error="NOT_FOUND", source="load_posting")`
  - raise 없이 `Posting | ToolError` 반환
- 🔎 인덱스는 `need_ocr` 무관 **전체 2,053건** (load_posting은 순수 조회). 예: 위 샘플은 `need_ocr='O'`라 detail_text 비었을 수 있음 → 그 처리는 analyze_gap/agent·OCR 백로그.
- 📦 산출: `tools/{load_posting,__init__}.py`

## 구현 메모 — 채택 방식 결정 (계획과 다르게 간 경우만)
- 반환 타입 `Posting`은 **설계 미결정 항목을 이번에 새로 확정**(D10). "기존에 Posting으로 정함"이 사실 아님을 문서 재확인으로 밝히고, 근거(파이프라인 Pydantic 일관) 위에 결정.
- 인덱스는 모듈 레벨 1회 캐시(`_INDEX`) — 매 호출 재로드 안 함.
