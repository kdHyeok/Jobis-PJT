# 05. search_postings (RAG Mock)

- **선행:** 01 (SearchResult·ScoredPosting·MatchReason)
- **참조:** AGENTS §2.3·§4.1 · **RAG 입출력 명세서(계약 단일 출처)** · 정본 §4.2
- **상태:** ✅ 완료 (2026-07-27)

## 목표
`search_postings` 인터페이스를 **계약대로** 구현하되 실제 검색은 **Mock(naive 키워드 매칭)**. 입력(직업명 or profile) → `SearchResult`. 실제 RAG 완성 시 **함수 몸통만 교체**(계약 불변).

## 재사용 자산 (신규 작성 금지)
| 용도 | 재사용 대상 |
|---|---|
| 출력 스키마 | `schemas/SearchResult·ScoredPosting·MatchReason` (task 01) |
| profile 입력 | `schemas/UserProfile` (task 01) |
| 계약 | RAG 입출력 명세서 |

## 계약 정합 수정 (완료)
- [x] **`MatchReason`에 `matched_keywords` 추가** (RAG 계약 3필드 정렬 — 현재 2필드라 누락). 하위호환.
- [x] **`MatchReason`에 `extra="allow"`** (RAG가 나중에 디버그 필드 추가해도 안 버림).
- [x] AGENTS §2.3 예시 3필드로 갱신.

## DB 접근 — 툴별 독립 (결정: 각자 로드)
`load_posting`은 `{url: 공고}`로 **키 조회**, search_postings는 **전체 순회**로 매칭.
**결정: 공유 로더 없이 각 툴이 자기 DB 접근을 갖는다.**
- **근거:** 프로덕션에선 백엔드가 갈림 — `load_posting`=데이터팀 DB(키 조회), `search_postings`=RAG(의미 검색). 지금 합치면 곧 갈라질 것을 잘못 결합. 파일 읽는 몇 줄은 도메인 로직 아닌 플럼빙(접근 방식도 dict vs 순회로 다름) → 재사용 원칙 위반 아님.
- **결과:** task 04(커밋됨) **안 건드림**. search_postings는 자체 `_load_postings()`(후보 리스트).

## 작업 항목
### 스키마 정합 (`schemas/tool_io.py`)
- [x] `MatchReason` += `matched_keywords` + `extra="allow"`
### `tools/` Mock 툴
- [x] `tools/search_postings.py`
  - [x] `search_postings(query: str | UserProfile | dict) -> SearchResult`
  - [x] `_load_postings()` — 후보(need_ocr=X & detail_text) 로드, 자체 캐시 (load_posting과 독립)
  - [x] **입력 정규화**: 직업명 → 토큰 / profile → `skills[].name` + `projects[].techStack`
  - [x] **naive 매칭**: 키워드가 `title`·`detail_text`에 substring(대소문자 무시) → 겹친 수로 `score`(mock, 0~1), `match_reason`(3필드) 채움
  - [x] 정렬 `score` 내림차순 → `TOP_K=3` → `ScoredPosting` 배열 → `SearchResult`
  - [x] 매칭 0건 → `SearchResult(postings=[])`
  - [x] **원본 공고 필드 변경 금지** (score·match_reason만 얹음)
- [x] `tools/__init__.py`에 `search_postings` 추가

## 완료 기준 (DoD)
- [x] `search_postings("백엔드")` → `SearchResult`, `postings`=3 ≤ 3, `score` 내림차순
- [x] `search_postings(profile)` → 관련 공고, `matched_skills`=['React','TypeScript','JavaScript'] 채워짐
- [x] 각 항목 `ScoredPosting`(원본 15필드 + score + match_reason), **원본 필드 == DB 원본**
- [x] `match_reason` **3필드**(matched_skills·matched_keywords·matched_fields) 존재
- [x] **0건 케이스**: 없는 쿼리 → `postings=[]`
- [x] 반환 `SearchResult` (raise 안 함) · **LLM 호출 0**(크레딧 안 씀)

## 주의
- **Mock임.** 실제 RAG 완성 시 **함수 몸통만 교체**, 계약 불변.
- `score`는 **mock 임의값**. 데모·테스트 정합용.
- **원본 공고 필드 변경 절대 금지** (RAG 명세서 핵심 규칙).
- **범위: 이 툴만.**

---
↓ 이하는 **구현 후에** 채운다 ↓

## 검증 메모 (2026-07-27)
- ✅ **DoD** (LLM 0, 결정적):
  - `"백엔드"` → 3건, score 내림차순, match_reason={matched_keywords:['백엔드'], fields:['query']}
  - profile(React·TS·JS) → matched_skills=['React','TypeScript','JavaScript'], fields=['projects.techStack','skills']
  - 없는 쿼리 → `[]` (0건)
  - 원본 15필드 + score + match_reason 보존
- ✅ 스키마 정합: `MatchReason` 3필드 + extra="allow". AGENTS §2.3 갱신.
- 📦 산출: `tools/search_postings.py`, `schemas/tool_io.py`(수정), `tools/__init__.py`(수정)

## 구현 메모 — 채택 방식 결정 (계획과 다르게 간 경우만)
- **DB 접근 = 툴별 독립** 채택(공유 로더 A 폐기). 근거: 프로덕션 백엔드 분리(데이터팀 DB vs RAG) → 잘못된 결합 방지 + task 04 미변경.
- **Mock 스코어링 coarse**: 단일 키워드 쿼리는 매칭 시 전부 score=1.0(동점) → top_k는 순회 순 앞 3개. 실제 유사도 아님(mock 한계, 계약엔 무관). 실제 RAG가 정교화.
- **직업명 검색 = title 매칭 (후속 개선)**: 초기엔 본문(detail_text) substring이라 false positive 심함(`"프론트엔드"`→백엔드 공고). → 직업명(str)은 **제목(title)에서만** 매칭하도록 변경 → `"프론트엔드"`→제목에 프론트엔드 든 실제 공고. **profile은 본문 매칭 유지**(잘 됨). 조기종료는 **미채택**(full scan, 정렬 보존 — 1743건 in-memory라 수 ms, 조기종료 시 "best 3"가 "first 3"로 깨짐).
