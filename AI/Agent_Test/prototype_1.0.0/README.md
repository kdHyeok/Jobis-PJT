# Prototype 1.0.0 — 진행 기록 (인덱스)

> 커리어 코치 Agent 프로토타입 개발의 **진행 기록 전용** 폴더.
> 코드는 `Agent_Test/` 루트에 둔다(플레이북 §3). 이 폴더는 "무엇을 왜 정했고, 어디까지 했나"만 담는다.

## 기록 3종
| 파일/폴더 | 역할 |
|---|---|
| [`decisions.md`](./decisions.md) | 결정 로그 — "무엇을 왜 정했나" (짧은 성장 로그, 단일 파일) |
| `tasks/` | 태스크 계약 + 검증 결과 (긴 자립 문서, 폴더) |
| `checkpoints/` | 특정 시점 전체 점검 리포트 (긴 자립 문서, 폴더 — 마일스톤마다) |
| `test_logs/` | 테스트 **실행 이력** (날짜·대상·결과·피드백 — 돌릴 때마다). ※ `tests/`=코드, 여기=결과 |

## 문서 지도 (역할·권위 — 상세는 decisions.md D6)
> **코딩 중 LLM이 보는 문서는 `AGENTS.md` 하나.** 아래 설계 문서는 사람이 읽는 배경 근거다.

| 문서 | 역할 | 코딩 시 |
|---|---|---|
| [`../agent 설계 명세서/agent_prototype_1.0.0.md`](../agent%20설계%20명세서/agent_prototype_1.0.0.md) | 설계 확정 **스냅샷(정본)** — 툴·시나리오·스키마·구조·RAG 계약 | 배경 근거 |
| [`../../ai-agent-repo/week-6/design.md`](../../ai-agent-repo/week-6/design.md) | **week-6 과제 제출물** — 에러코드·공고 샘플/경로·예외흐름·trace가 임시 유일 출처(→ AGENTS.md로 필요분만 이식 후 동결) | 배경 근거 |
| [`../../AGENTS.md`](../../AGENTS.md) | **구현 규약(코딩 헌법)** — 자동 로드 | ★ **LLM 유일 참조** |
| [`../agent_ver_VIBE-CODING-PLAYBOOK.md`](../agent_ver_VIBE-CODING-PLAYBOOK.md) | 개발 규약(방법론) | 세션 진행 규약 |
| [`../rag_입출력 관련 명세서/RAG_입출력_명세서.md`](../rag_입출력%20관련%20명세서/RAG_입출력_명세서.md) | RAG 입출력 계약 | search_postings 구현 시 |

> **권위:** 설계 개념 충돌 → 스냅샷 우선 / 구현 디테일 충돌 → AGENTS.md 우선.

## 현재 상태
- ✅ 설계 명세 확정 (툴 3개·싱글턴·ReAct)
- ✅ 바이브코딩 플레이북 재단본 작성
- ✅ 아키텍처 결정 (서버 없는 core / 모듈화 / 정적 모델 티어링 / FastAPI 후순위)
- ✅ `AGENTS.md` 작성 (코딩 헌법) · `AGENTS.md`가 코딩 시 유일 참조
- ✅ 환경 셋업 (Python 3.11 `.venv` / `requirements.txt` 버전 핀)
- 🎉 **프로토타입 1.0.0 개발·검증 완결** (01~08·10) — 검사 19/19 · Eval 8/8 3/3 · 수동 S1~S4 + 성공기준 5개 런타임 시연
- FastAPI(09)는 **고도화로 연기**(D13, Java 연결 시점에). 그 외 고도화 백로그: 실제 RAG·멀티턴·Eval 심화 등

## 태스크 진행판
> 착수하면서 채운다. 상태: ⬜ 대기 / 🟦 진행 / ✅ 완료
| # | 태스크 | 상태 |
|---|---|:---:|
| 01 | 스키마 정의 (Pydantic) | ✅ |
| 02 | llm/ 창구 (모델 티어 매핑) | ✅ |
| 03 | 이력서 파싱 (docx→profile) | ✅ |
| 04 | load_posting (실데이터) | ✅ |
| 05 | search_postings (mock) | ✅ |
| 06 | analyze_gap (LLM+채점) | ✅ |
| 07 | agent 루프·라우팅 (ReAct)·run_agent | ✅ |
| 08 | 성공 판정 케이스 검증 | ✅ |
| 09 | FastAPI 얇은 층 (Java 연결) | ⏸ 고도화로 연기(D13) |
| 10 | Agent Eval (다중실행 일관성·궤적) | ✅ |

## 다음 할 일 (고도화 로드맵 — 상세 decisions D14)
- [ ] **1.0.1** (구조 유지): 다중 입력 강건화(여러 **텍스트** 이력서·다양 케이스) · analyze_gap 정교화 · mock 검색 품질↑ (표파싱 유보)
- [ ] **1.1.0** (구조 진화): 멀티턴 · Agent Eval 심화(LLM-judge) · analyze_gap 정교화 지속
- [ ] 후순위: FastAPI(Java 연결) / 우리 밖: 실제 RAG(RAG팀)·OCR(데이터팀)
