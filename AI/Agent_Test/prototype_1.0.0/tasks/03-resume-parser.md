# 03. 이력서 파서 (docx → profile)

- **선행:** 01 (UserProfile 스키마) · 02 (get_structured_llm 창구)
- **참조:** AGENTS §2.1(profile) · §3(파이프라인·디렉토리) · §5.5(mid 티어) · 정본 §3
- **상태:** ✅ 완료 (2026-07-27)

## 목표
docx 이력서 파일을 `UserProfile`로 변환하는 **agent 밖 전처리 파서**를 만든다(AGENTS §0). task 01 스키마 + task 02 창구가 여기서 결합한다. task 01에서 미룬 "**docx 실테스트**"가 여기서 실현.

## 파이프라인 (정본 §3 / AGENTS §3)
```
docx → [docx_to_text] python-docx 문단 추출 (표 없는 텍스트 이력서 가정)
     → resume_text
     → [get_structured_llm("mid", UserProfile)] 스키마 강제 추출
     → UserProfile
```

## 재사용 자산 (신규 작성 금지)
| 용도 | 재사용 대상 |
|---|---|
| profile 스키마 | `schemas/UserProfile` (task 01) |
| LLM 창구(스키마 강제) | `llm.get_structured_llm("mid", ...)` (task 02) |
| 실제 이력서 | `sample_data/이력서_이서현_프론트엔드.docx` |
| docx 파싱 | `python-docx` (requirements 설치됨) |

## ⚠️ 선행 검증 게이트
- [x] **실제 docx가 python-docx 문단 추출로 내용이 나오는가** → **통과** (문단 64개·3091자, 키워드 React·TypeScript·이서현·프로젝트 다 포함). 표 1개 있으나 정보는 문단에 텍스트 형태로 존재 → 문단 추출로 충분.

## 작업 항목
### `preprocess/` 파서
- [x] `preprocess/resume_parser.py`
  - [x] `docx_to_text(path) -> str` : python-docx 문단 텍스트 join
  - [x] `parse_resume(path) -> UserProfile` : `docx_to_text` → `get_structured_llm("mid", UserProfile).invoke(prompt)`
  - [x] 추출 프롬프트(**최소 지시**): "실제 있는 내용만 · 없는 섹션 `[]` · 없는 값 `null` · 지어내지 말 것"
- [x] `preprocess/__init__.py` (재수출)

## 완료 기준 (DoD)
- [x] `docx_to_text(실제 docx)` → **비어있지 않은 텍스트**(3091자), "React" 포함
- [x] `parse_resume(실제 docx)` → **`UserProfile` 인스턴스** 반환 (실제 GMS 호출, mid)
- [x] **로드베어링 sanity**: `skills`(25개)·`projects`(3개) 추출됨. ※ `experiences`는 **신입이라 `[]`가 정상** → 하드 assert 안 함(아래 구현 메모)
- [x] 반환이 `UserProfile` 스키마 검증 통과 (structured)
- [x] 스모크: `parse_resume` 크래시 없이 완료

## 주의
- **실제 LLM 호출 = 크레딧**(mid 티어). 파싱 1회로 검증.
- **파싱 품질/미탐은 판정 대상 아님** — 구조·로드베어링 필드 **존재**만 확인.
- 프롬프트는 **최소 추출 지시로 시작.** 품질 튜닝은 범위 밖.
- 반환은 **UserProfile 객체(in-memory)**. 저장·agent 전달 방식은 task 07.
- **범위: 파서만.**

---
↓ 이하는 **구현 후에** 채운다 ↓

## 검증 메모 (2026-07-27)
- ✅ `docx_to_text`: 문단 64개·3091자. 표 1개 있으나 정보가 문단에 텍스트로 존재 → 문단 추출로 충분.
- ✅ `parse_resume` (실제 GMS, mid=gpt-4.1-mini) → `UserProfile`:
  - skills **25개** (React 18·TypeScript·Next.js·Zustand·Jest…)
  - projects **3개** (Marketly·CoNote·seohyun.dev)
  - education 국민대 소프트웨어학부 4학년 · certifications 2(정보처리기사 필기·컴활1급) · languages(TOEIC·OPIc)
  - **`experiences: []`** — 신입이라 정당한 빈 섹션. awards·bootcamp도 `[]`.
- ✅ **"없는 섹션 → []" 규칙이 실데이터로 검증됨** (task 01 §2 규칙 + task 03 실증).
- 💳 크레딧: mid 1회 소량.
- 📦 산출: `preprocess/{resume_parser,__init__}.py`

## 구현 메모 — 채택 방식 결정 (계획과 다르게 간 경우만)
- DoD 초안은 "skills·**experiences** 비어있지 않음"이었으나, 실제 이서현은 **신입(경력 없음)**이라 `experiences=[]`가 정상.
  → sanity를 **skills 필수 + projects 기대**로 조정(experiences 하드 assert 제거). "없는 섹션 []"이 실데이터에서 맞게 동작함을 오히려 검증.
- **후속 프롬프트 튜닝 (2026-07-27)**: 결과 눈검토에서 quality quirk 2개 발견 — ① 프로젝트가 `experiences`에 중복 분류 ② 어학(TOEIC·OPIc)이 `certifications`에도 중복. 시스템 프롬프트에 **분류 규칙 3줄** 추가(experiences=실제 재직 경력만 / projects 분리 / 어학은 languages에만). **2회 재실행 모두 개선 확인**(experiences=0, 어학 중복 없음). ※ 프롬프트는 경향 개선일 뿐 비결정성 완전 제거는 아님. 구조 판정과 별개의 품질 개선.
