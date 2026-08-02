# 실행 인계서 — RAG 평가 1·2단계 마무리

> 대상: 이 저장소를 처음 보는 AI 에이전트(Opus 등).
> 준비는 전부 끝났고, 이 문서의 실행 단계만 수행하면 된다. **이미 만들어진 것을 다시 만들지 말 것.**

## 0. 환경 (먼저 확인)

- Python 3.12, 의존성 설치됨 (`ragas 0.4.3`, `google-genai`, `instructor` 포함)
- DB: PostgreSQL+pgvector, 접속 env는 **`PG_DSN`** (`DATABASE_URL` 아님), `.env`에 있음
- LLM judge: GMS 게이트웨이 gemini — env `GMS_KEY`, `GMS_BASE_URL`, `GMS_MODEL`(기본 gemini-2.5-flash-lite)
- Windows 콘솔 한글 깨짐 → 모든 실행은 **`python -X utf8`**
- CSV 파일이 Excel에 열려 있으면 쓰기 실패(PermissionError) → 사용자에게 닫아달라고 요청

> **2026-07-29 실행 완료분** (상세: [APPLIED.md](APPLIED.md) §8–§9, [PLAN_v5.md](PLAN_v5.md) §6.6–§6.7)
> - **§2-A RAGAS 완료** → `ragas_report.json`. ID기반 precision 0.6222 / recall 0.4057 (15/15),
>   faithfulness 0.7115 (13/15), answer_relevancy 0.7814 (15/15), `n_failed=2`.
> - **§3-B judge 모델 A/B 완료 → REJECT.** 이후 사람 기준으로 이 기각이 옳았음이 확인됐다
>   (flash는 사람 대비 κ 0.4535 < lite 0.5921).
> - **§3-A 사람 채점 완료** → `anchor/anchor_report_human.json`, `report_spec.json`.
>   게이트 3 κ=**0.5921** (CI [0.434, 0.736]) → FAIL이나 **CI가 기준 0.60을 포함해 판정 불가**.
>   게이트 3b 사람 자기일관성 κ=**0.855** PASS (이 게이트 첫 실제 작동).
>   본평가 최고 rrf_ce **0.6853**, arm 순위 두 qrels에서 동일(라벨 강건).
> - 결과 대시보드: `dashboard_human_standalone.html` (브라우저로 직접 열기, 용어 해설 포함)
> - **§2-A·§3-A·§3-B는 완료. 다시 실행하지 말 것.**

## 1. 현재 상태 (2026-07-29 기준, 재작업 금지 목록)

| 자산 | 경로 | 상태 |
|---|---|---|
| 본평가 리포트 (자연어 30질의, v5) | `eval/report.json` | 완료. gate_failed 배너 有(게이트 3) |
| 계획·실행 기록 | `eval/PLAN_v5.md` (§6.5까지), `eval/APPLIED.md` | 완료 |
| 명세서 계약 어댑터 | `jobrag/spec_adapter.py` + `eval/contract.py` Tier 0 31/31 PASS | 완료 |
| 정규화 질의 앵커 트랙 | `eval/spec_anchor.py`, `eval/pool_spec.json`(439쌍), `eval/judgments_spec.json`(gemini v3 전량) | 완료 |
| 앵커 시트 | `eval/anchor/session_{easy,ambiguous,recheck}.csv` — **사람 채점 완료(118+20쌍). 라벨 정규화됨, 원본은 `_human_raw_backup/`** | 완료 |
| Claude 앵커 라벨 | `eval/anchor/session_*_claude.csv` (120쌍) + `anchor_report.json` (κ=0.445 FAIL) | 완료 |
| RAGAS 준비 | `eval/ragas_prep.py`, `eval/ragas_dataset.json`(15샘플), `eval/ragas_run.py`(4축 배선, 미실행) | 완료 |
| 구버전 아카이브 | `eval/_archive/` | 보존. 삭제 금지 |

핵심 미해결 (2026-07-29 갱신): **게이트 3은 FAIL이 아니라 판정 불가**다 — 사람 기준 κ=0.5921,
CI [0.434, 0.736]이 기준 0.60을 포함한다. 양성 부풀림 자체는 사람 기준에서 거의 해소됐다
(McNemar b=10, c=13 균형). 남은 문제는 **표본 부족**이고, 해소 경로는 앵커 확대(§5-4)다.

또 하나: **상위 3개 arm(rrf_ce·rrf·bm25)이 통계적으로 구분되지 않는다** — 순위 결론은
라벨 강건성이 확인됐지만(두 qrels 동일) 질의 15종으로는 검정력이 없다. "rrf_ce가 최적"은
아직 방어 가능한 결론이 아니다.

## 2. 1단계 실행 — RAGAS

### 2-A. 즉시 실행 (사람 입력 불요, ~10분)

```
python -X utf8 -m eval.ragas_run
```

- 산출: `eval/ragas_report.json` — 4축 (context_precision/recall = ID기반 결정적 본측정, faithfulness/answer_relevancy = 템플릿 response 기준 하네스 검증값)
- 옵션 `--llm-context`: LLM 판정판 context precision/recall 병행 (gemini 호출 ~30건 추가)
- 실패 예상 지점: GMS 429(백오프 재시도), instructor의 구조화 출력 파싱 실패(gemini-lite가 형식을 깨는 전례 有 — 실패 시 해당 샘플 skip하고 리포트에 n_failed 기록, 억지로 프롬프트 고치지 말 것)

### 2-B. 본 측정 승격 (사용자가 Agent 생성 출력을 주면)

1. 질의 15종(`eval/ragas_dataset.json`의 `question`)에 대한 Agent 실출력 텍스트를 받는다
2. 각 샘플의 `response` 필드 교체 + `response_source`를 실출처로 갱신
3. 2-A 재실행 → faithfulness/relevancy가 본 측정이 됨

## 3. 2단계 실행 — 도메인 평가 게이트 3 해소

### 3-A. 사람 채점 반영 (사용자가 시트를 채우면) ← 최우선

1. 사용자가 `eval/anchor/session_easy.csv`(100) / `session_ambiguous.csv`(20) / `session_recheck.csv`(20)의 label 열을 Correct/Ambiguous/Incorrect로 채움 (약 90분)
   - 채점 전 사용자에게 경계 기준 2건 확정 요청: ① 신입·인턴 전용 공고 vs 경력 질의, ② 풀스택 공고 vs 백엔드 질의. 확정된 기준을 PLAN_v5에 기록
2. 반영: `python -X utf8 -m eval.anchor --score`
   - 주의: `score()`는 `session_*.csv` 전부(glob)를 읽는다. 사람 시트와 `*_claude.csv`가 같이 잡히므로, 사람 채점본 반영 시 **`*_claude.csv`를 임시로 `eval/_archive/`에 옮기고** 채점→복원, 또는 3자 비교 스크립트를 따로 작성
3. 산출 κ로 게이트 3 판정 갱신 → `eval/anchor/anchor_report.json`
4. gemini/Claude/사람 3자 비교표를 PLAN_v5 §6.5에 추가 (어느 LLM이 사람과 가까운지)

### 3-B. (대안, 사람 채점 전 병행 가능) judge 모델 상향 A/B

- `GMS_MODEL=gemini-2.5-flash`(비-lite)로 앵커 120쌍만 재판정 → Claude 앵커 대비 κ 비교
- 채택 기준 사전 등록: κ ≥ 0.60 또는 v3-lite(0.445) 대비 +0.10 이상
- 방법: `eval/judge.py`는 `GMS_MODEL` env를 읽으므로 env만 바꿔 별도 파일로 판정 저장 (기존 `judgments_spec.json` 덮어쓰기 금지 — 백업 후 진행)
- 채택 시: 439쌍 전량 재판정 → 시트 재생성(`python -X utf8 -m eval.spec_anchor --sheets`) → 재채점 필요해지므로 **사람 채점 전에 이걸 먼저 끝내는 게 순서상 유리**

### 3-C. 게이트 3 PASS 후

1. 정규화 질의 트랙을 본평가로 승격할지 사용자에게 확인 (PLAN_v5 §6 Tier 1: 입력 A 직군 12종 질의셋 / 입력 B golden profile ~8건)
2. `eval/report_dashboard.html` 수치 갱신 (DATA 상수에 report.json 주입 방식)

## 4. 보고 원칙 (모든 산출물 공통)

- 게이트 FAIL 상태의 절대 수치는 헤드라인 인용 금지, "모델 간 교차검증 기준" 명시
- 프롬프트/모델/코퍼스 버전 스탬프를 리포트에 포함 (기존 report.json `version` 블록 관례 따름)
- 앵커에 과적합 금지: judge 프롬프트 수정은 "확인된 결함 1건 단위 + 사전 등록 채택 기준" 원칙 유지 (PLAN_v5 §2)

## 5. 우선순위 요약

1. ~~**2-A** RAGAS 실행~~ — 완료 (`ragas_report.json`)
2. ~~**3-B** judge 모델 상향 A/B~~ — 완료, **REJECT** (사람 기준으로 재확인됨)
3. ~~**3-A** 사람 채점 반영~~ — 완료 (`anchor_report_human.json`, `report_spec.json`)
4. ~~**`exp_min` 본문 보강 추출**~~ — 2026-07-29 완료 (APPLIED §11)
4b. **코퍼스 5,000건 적재 → 재평가 1회** ← **현재 최우선.** 파서 수정이 이미 반영돼 있으므로
   지금 적재하면 신규 공고도 연차가 채워진다. 적재 후 풀 재구성(**depth 30 권장**) →
   판정(재사용 88.7%) → 앵커 증분 채점 순서. 재평가를 두 번 하지 않도록 아래 5·6과 묶을 것
5. **앵커 표본 확대** 게이트 3이 FAIL이 아니라 *판정 불가*다.
   현재 CI 반폭 ±0.15로 기준선 0.60을 배제하지 못한다. 배제하려면 앵커 **250~300쌍**
   (추가 사람 라벨링 130~180쌍, 약 60~90분) 필요
   - 선행: **경력 요건 경계 기준 문서화**. 사후 역추출 결과 최대 불안정 구간이
     경력 질의(불일치 22.1%)였다. 풀스택↔백엔드(8.3%)는 문제가 아니었으므로 그건 접어도 된다
6. **질의 수 확대 (15 → 60+)** — arm 선택을 위해 별도로 필요. 상위 3개 arm이 통계적으로
   구분되지 않는다. 4번과 함께 설계해야 사람 라벨링을 두 번 하지 않는다
7. ~~**2-B Agent 출력 반영**~~ — 운영 생성부(gemini-lite)로 완료(APPLIED §10). Claude 교차검증만 대기 — `eval/ragas_responses.py` 준비됨 (`--emit`으로 프롬프트 팩 방출,
   `--ingest`로 수거, `--generate-production`으로 운영 생성부 대조군). 사용자 입력 대기

## 6. 새로 생긴 자산 (2026-07-29)

| 자산 | 경로 | 비고 |
|---|---|---|
| RAGAS 리포트 | `eval/ragas_report.json` | 4축 + `scored_coverage`/`n_failed` |
| judge 모델 A/B | `eval/judge_ab.py`, `anchor/ab_report_flash.json` | 미채택 |
| flash 판정본 | `eval/judgments_spec_flash.json` | **실험 기록. 본판정에 쓰지 말 것** |
| 사람 기준 대조 | `eval/anchor_human.py`, `anchor/anchor_report_human.json` | 게이트 3·3b·잡음천장·CI |
| 정규화 트랙 본평가 | `eval/run_spec.py`, `report_spec.json` | 두 qrels 대조 + 라벨 민감도 |
| 결과 대시보드 | `eval/make_dashboard.py`, `dashboard_human_standalone.html` | JSON에서 수치 자동 주입 |
| 2-B 응답 수집기 | `eval/ragas_responses.py` | 미사용 |
| 사람 시트 원본 | `anchor/_human_raw_backup/` | 대소문자 정규화 전 원본. 삭제 금지 |

## 6.5 최우선 발견 — 연차 필터가 무력화돼 있다 (2026-07-29)

**판정 기준 문제가 아니라 파이프라인 데이터 결함이다.** 상세: PLAN_v5 §6.8,
[JUDGING_CRITERIA.md](JUDGING_CRITERIA.md) §1.

- active 1,172건 중 `exp_min` NULL = **930건 (79.4%)**, 그중 본문에 "경력 N년" 명시 = **476건**
- 원인: `raw.experience`에 값 없이 라벨만 수집됨 (`'경력'` 785건 = 67%)
- `search.py:96`이 NULL을 항상 포함시켜 **연차 필터가 79% 코퍼스에서 작동하지 않는다**
- 명세서 입력 3요소(직군·기술·연차) 중 하나가 사실상 죽어 있다

**→ 2026-07-29 수정 완료** (APPLIED §11). `parse_exp_from_body()` 신설 + 백필 332건 +
재청킹 323건/477청크. **`exp_min` 확보 20.6% → 48.5%.** SA01 상위 3건이
5년+/6년+/7년+ → 미상/0년/3년으로 바뀌어 필터가 실제로 작동함을 확인했다.

### ⛔ 절대 하지 말 것 — `run_embed.py`로 재청킹

기본 입력 `../all_job_postings.json`은 **251건짜리 낡은 스냅샷**이고,
`upsert_postings`는 입력에 없는 공고를 `is_active=false`로 내린다.
2026-07-29에 이걸로 **활성 1,172 → 211건 붕괴**를 실제로 겪었다(복구 완료, 손실 없음).
재청킹은 **`run_rechunk_stale.py`** 를 쓸 것 — DB의 `raw`를 원본으로 삼고 `postings` 행을 건드리지 않는다.

### 평가 자산 상태 (중요)

`exp_min` 326건 변경 + 임베딩 477개 갱신으로 **검색 결과가 달라졌다.**
현 `report_spec.json`·`judgments_spec.json`·`ragas_report*.json`은 **수정 전 코퍼스 기준**이며
백필 직전 상태는 `_archive/pre_exp_backfill_20260729/`에 동결돼 있다.

재구성 시 예상 비용 (실측):

| 항목 | 수치 |
|---|---|
| 기존 judge 판정 재사용 | 252쌍 (신 풀의 88.7%) |
| 신규 judge 판정 필요 | 32쌍 (~10초) |
| **사람 라벨 118쌍 중 생존** | **73쌍 (61.9%)** |

사람 라벨의 62%는 그대로 유효하다 — 라벨은 (질의, 공고) 판단이고 연차 수정과 무관하다.
나머지 38%는 해당 공고가 상위 10건에서 밀려난 것으로, depth를 30으로 올리면 상당수 되살아난다.

## 7. 주의사항 (다음 실행자용)

- **사람 시트 라벨은 대소문자가 섞여 있다.** 읽을 때 반드시 `.lower()` 정규화.
  `anchor.score()`는 정확 일치만 인정하므로 그대로 쓰면 표본이 조용히 줄어든다
- **`anchor.score()`의 glob은 `*_claude.csv`까지 잡는다.** 사람 라벨 대조에는
  `anchor_human.py`를 쓸 것 (읽을 파일을 명시 지정한다)
- **LLM 앵커 κ를 사람 κ의 대용으로 쓰지 말 것.** 이번에 방향이 거꾸로 나온 사례가 나왔다
- 게이트 기준을 재설정할 때는 κ 절대값이 아니라 **사람 자기일관성(0.855) 대비 비율**로 잡을 것