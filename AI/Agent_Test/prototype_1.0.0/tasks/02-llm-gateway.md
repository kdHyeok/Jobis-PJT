# 02. llm/ 창구 (GMS 클라이언트 + 모델 티어 매핑)

- **선행:** 01 (schemas — structured output 검증에 사용)
- **참조:** AGENTS §0(GMS·인증) · §5.5(티어 매핑) · §6(모델 선택 컨벤션) · §4.1
- **상태:** ✅ 완료 (2026-07-27)

## 목표
모든 LLM 호출이 거쳐가는 **단일 창구 `llm/`**를 만든다. GMS(OpenAI-compat) 연결 + 정적 티어 매핑 + `get_llm`/`get_structured_llm`. task 03~의 파서·툴·agent가 **이 창구에만** 의존한다.

## 재사용 자산 (신규 작성 금지)
| 용도 | 재사용 대상 |
|---|---|
| 티어 매핑 | AGENTS §5.5 (cheap/mid/strong) |
| GMS 연결(base_url·인증) | AGENTS §0 |
| structured 검증용 스키마 | `schemas/` (task 01) — 또는 작은 `_Ping` 테스트 스키마 |
| 라이브러리 | `requirements.txt` (langchain·langchain-openai·python-dotenv 설치됨) |

## ⚠️ 선행 검증 게이트 (D7 실증 — 이 태스크의 핵심)
- [x] **GMS OpenAI-compat 호출 성공**: `get_llm("cheap").invoke("ping")` → `"2"` 응답. base_url·GMS_KEY 배선 확인.
- [x] **`with_structured_output`이 GMS 프록시 너머로 작동** ★ → **PASS** (`_Ping(answer=2)` 반환). **Plan B 불필요.**
- [x] **티어별 정확한 모델 문자열 확정**: `gpt-4o-mini`·`gpt-4.1-mini`·`gpt-4.1` **전부 GMS에서 유효** → §5.5 갱신 불필요.

## 작업 항목
### `llm/` 창구
- [x] `.env` 로딩 (`python-dotenv`): `GMS_KEY`, `OPENAI_API_BASE`. ※ 브리지 대신 **base_url·api_key를 명시 전달** 채택(아래 구현 메모)
- [x] `MODEL_TIER` 상수 (cheap/mid/strong → 모델 문자열, §5.5) — `llm/config.py`
- [x] `get_llm(tier)` → ChatModel (`init_chat_model(model, model_provider="openai", base_url=, api_key=)`) — non-stream
- [x] `get_structured_llm(tier, schema)` → `get_llm(tier).with_structured_output(schema)`
- [x] 키 누락 시 **명확한 에러**로 조기 실패 (`get_gms_key`)
### 환경 파일
- [x] `.env.example` (키 없이 템플릿, **커밋**) + `.env` (실제 GMS_KEY, **gitignore됨**)

## 완료 기준 (DoD)
- [x] `get_llm("cheap").invoke("1+1?")` → 텍스트 응답 (실제 GMS 호출 성공)
- [x] `get_structured_llm("cheap", _Ping).invoke(...)` → `_Ping` 객체 반환 (structured over GMS ✔)
- [x] cheap·mid·strong **3티어 다 호출 성공**
- [x] `.env` 없이 실행 시 **명확한 에러 메시지** (키 누락 감지)
- [x] 모델 문자열·base_url이 **`llm/config.py` 안에만** (grep: 다른 .py엔 없음 — AGENTS §6)
- [x] 스모크: 게이트 스크립트 크래시 없이 완료

## 주의
- **실제 GMS 호출 = 크레딧 소모.** cheap 위주 최소 호출로 검증. (잔여는 `key-info`로 확인)
- `GMS_KEY`는 `.env`에만, **절대 커밋 금지** (`.gitignore` 확인 — `!! .env`).
- structured 미지원 시 Plan B — **해당 없음(통과)**.
- **범위: 창구만.** 프롬프트 내용·파서·툴·agent 루프는 task 03~.
- **스트리밍 안 씀** (non-stream `.invoke`).

---
↓ 이하는 **구현 후에** 채운다 ↓

## 검증 메모 (2026-07-27)
- ✅ **D7 게이트 전부 통과** (실제 GMS 호출):
  - Gate1 GMS 실호출 OK (`"2"`)
  - Gate2 ★ **structured over GMS PASS** (`_Ping(answer=2)`) → **Plan B 불필요**
  - Gate3 3티어(gpt-4o-mini·gpt-4.1-mini·gpt-4.1) 전부 유효
- ✅ **DoD**: 키 누락 시 명확한 에러 / 모델·base_url이 `llm/config.py`에만 격리(grep 확인) / import·스모크 OK.
- 💳 크레딧: 잔여 73,855 / 100,000 (테스트 소량), 만료 2026-08-14.
- 📦 **산출**: `llm/{config,gateway,__init__}.py` + `.env.example` (`.env`는 로컬·gitignore).

## 구현 메모 — 채택 방식 결정 (계획과 다르게 간 경우만)
- 명세의 "`GMS_KEY → OPENAI_API_KEY` 환경 브리지" 대신 **`init_chat_model(..., base_url=, api_key=)` 명시 전달** 채택.
  - 사유 1) env 이름 gotcha(`OPENAI_API_BASE` vs `OPENAI_BASE_URL`) 회피.
  - 사유 2) 명시적이라 배선이 명확하고 테스트 쉬움. (인터페이스·계약 불변)
