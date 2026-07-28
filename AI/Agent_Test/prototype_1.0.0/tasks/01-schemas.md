# 01. 스키마 정의 (Pydantic)

- **선행:** — (첫 태스크)
- **참조:** AGENTS §2(데이터 모델) · §4.1(툴 I/O) · §6(컨벤션) · §7(에러 봉투)
- **상태:** ✅ 완료 (2026-07-26)

## 목표
프로토타입 전체가 공유할 Pydantic 모델을 `schemas/`에 정의한다. 모든 모듈(`tools`·`preprocess`·`agent`)이 의존하는 **계약층** — 여기가 확정돼야 나머지가 그 위에 쌓인다.

## 재사용 자산 (신규 작성 금지)
| 용도 | 재사용 대상 |
|---|---|
| profile 필드 | AGENTS §2.1 (`_UserProfileRead` 10필드) |
| 공고 필드 | AGENTS §2.2 + **실제** `sample_data/db내 공고파일/*.json` |
| profile 예시값 | design.md §7.2 ② (검증용) |
| 툴 I/O | AGENTS §4.1 |
| run_agent 반환 | AGENTS §2.4 |
| 에러 봉투 | AGENTS §4.1 `{error, source, detail}` |

## ⚠️ 선행 검증 게이트
- [x] **실제 공고 JSON 필드가 AGENTS §2.2와 일치하는지 대조** (`jobkorea_job_postings.json`·`wanted_job_postings.json` 직접 열어 확인)
  - **통과:** 필드 100% 일치(누락·초과 0), 타입 전부 str + `image_urls` list → §2.2 그대로 모델링, 문서 갱신 불필요
- [x] Pydantic 버전 확정 → **v2 (2.13.4)**

## 작업 항목
### 스키마 계층 (`schemas/`)
- [x] `profile.py` — `UserProfile`(=`_UserProfileRead`) + 하위 모델: `Skill`·`Experience`·`Project`·`Education`·`Certification`·`Language`·`Bootcamp`·`Award`·`Evidence`. 10필드.
- [x] `posting.py` — `Posting`(공고, 약 15필드: source·posting_id·company·title·url·employment_type·experience·education·location·posted_date·deadline·detail_text·image_urls·need_ocr·collected_at)
- [x] `tool_io.py` — `GapResult`(score·level·matched_required·missing_required·matched_preferred·rationale) · `SearchResult`(`postings: list[ScoredPosting]`) · `ScoredPosting`(Posting + score + match_reason) · `ToolError`(error·source·detail)
- [x] `agent_io.py` — `RunAgentResult`(reply + `meta`{scenario·tools_called·level})
- [x] `level`은 `Literal["상","중","하"]`; `tools_called`는 `list[str]`
- [x] **규칙 반영**: 없는 섹션 → `[]`(기본값 `default_factory=list`) · 값 없는 스칼라 → `Optional[...] = None`
- [x] `schemas/`를 import 가능하게 (`__init__.py` 재수출 + 루트 실행 기준)

## 완료 기준 (DoD)
- [x] `python -c "import schemas.profile, schemas.posting, schemas.tool_io, schemas.agent_io"` → 크래시 없이 import 성공
- [x] **실제** `sample_data/db내 공고파일/wanted_job_postings.json`의 공고 1건을 `Posting`으로 파싱 성공
- [x] **profile 스키마 형태 확인**: profile 예시 dict(design §7.2 ② — 손으로 쓴 대표 예시)를 `UserProfile(**dict)`로 인스턴스화 → 에러 없이 성공. ※ 파서가 없어 예시 dict로 *형태*만 검증. **실제 `sample_data/이력서_이서현_프론트엔드.docx` → profile 파싱+검증은 task 03 DoD**(파서=LLM+GMS 필요).
- [x] 빈 섹션(`[]`)·`null` 스칼라가 **구조** 검증 통과 (없는 섹션 넣어도 에러 안 남) — ※ *형태*만 확인 (파싱 miss 미탐지는 범위 밖, 아래 주의)
- [x] `GapResult`에 `level="상"` 검증 성공 / `level="X"`는 검증 실패(Literal 강제 확인)

## 주의
- 실제 공고 JSON 필드가 §2.2와 다를 수 있음 → **선행 게이트에서 먼저 대조** (환각 방지)
- 필드명은 원본 그대로 (임의 개명·추가 금지 — AGENTS §6)
- 이 태스크는 **스키마만.** LLM 호출·파싱 로직·GMS 연동은 task 02~ 로 미룸 (범위 침범 금지)
- ⚠️ **스키마는 형태만 검증, 내용 완전성은 못 봄.** 원문엔 있는 섹션인데 파서가 `[]`로 빠뜨린 "파싱 miss(미탐)"는 스키마가 못 잡는다. "진짜 없음 vs miss" 구분은 백로그 `meta.sectionStatus`(design §8.2) 몫 — 프로토타입 1.0.0은 **profile을 유효로 가정**(AGENTS §0)하므로 이 태스크에서 다루지 않는다.

---
↓ 이하는 **구현 후에** 채운다 ↓

## 검증 메모 (2026-07-26)
- ✅ **환경 셋업**: Python 3.11.9 venv(`.venv`), pip 26.1.2. 전체 스택 설치·핀(`requirements.txt`): pydantic 2.13.4 / langgraph 1.2.9 / langchain 1.3.14 / langchain-openai 1.4.1 / python-docx 1.2.0 / python-dotenv 1.2.2.
- ✅ **선행 게이트**: 실제 공고(jobkorea 1300·wanted 753건) 필드 = AGENTS §2.2와 **100% 일치**(누락·초과 0). 타입 전부 `str` + `image_urls` list, 일부 null. → §2.2 갱신 불필요. 사용가능(need_ocr=X & detail_text) jobkorea 1000·wanted 743건.
- ✅ **DoD 실행** (`.venv/Scripts/python.exe`):
  - DoD1 4파일+패키지 import OK
  - DoD2 실제 wanted 공고(id=376543) → `Posting` 파싱 OK
  - DoD3 profile 예시(§7.2②) → `UserProfile` 검증 OK (skills=2, techStack 보존)
  - DoD4 빈섹션[]/null 구조 검증 OK
  - DoD5 `level="상"` 통과 / `"X"` 거부 OK (Literal 강제 확인)
  - 보너스 `ScoredPosting`(공고+score)·`RunAgentResult`(meta.tools_called) OK
- 📦 **산출**: `schemas/{__init__,profile,posting,tool_io,agent_io}.py`

## 구현 메모 — 채택 방식 결정 (계획과 다르게 간 경우만)
- 계획대로 진행. 특이사항 없음.
- 참고: 환경 미설치(pydantic 없음)로 DoD가 1차 막힘 → venv+전체스택 셋업 후 통과. (env 셋업은 task 01 사전조건, AGENTS §8)
