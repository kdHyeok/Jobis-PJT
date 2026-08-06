# CLAUDE.md — AI 모듈 진입점

**코딩 규약의 단일 출처는 `AGENTS.md`, 지금 상태는 `작업로그/지금상태.md`** 다.
아래로 자동 임포트한다 — 코딩·실행 시 항상 이 규약을 따른다.

@AGENTS.md

@작업로그/지금상태.md

---

## 문서 지도 (필요할 때 찾아가는 곳 — 자동 로드 아님)

> **자동 로드는 위 둘뿐이다.** 나머지는 여기 지도로 찾는다. 수치·구조를 자동 로드에 넣지 않는
> 이유는 그것이 낡기 때문이다 — 구조·상수는 `python -m jobis_ai.explain` 이 코드에서 파생해 준다
> (`AGENTS.md` §4).

| 무엇을 알고 싶은가 | 어디를 보나 |
|---|---|
| **AI가 어떻게 만들어져 있나 (비개발자용)** | `docs/멀티에이전트-구조-설명.md` |
| **이 결정이 언제 왜 정해졌나 / 뒤집혔나** | `docs/decisions.md` (D1~, 시간순·뒤집힘 표시) |
| 지금 구조가 어떻게 생겼나 | `docs/agent-structure-current.md` (스냅샷 정본) |
| 여기까지 왜 이렇게 왔나 | `docs/agent-structure-evolution.md` (발전사) |
| 실측으로 뭐가 터졌고 어떻게 고쳤나 | `docs/troubleshooting.md` |
| 평가·재현성 수치의 출처 | `docs/eval-records/` + `evals/*.json` (baseline) |
| 프로토타입(`Agent_Test`)과의 축별 비교 | `docs/멀티에이전트-프로토타입-비교분석.md` |
| 이어서 할 일 (상세) | `작업로그/다음작업.md` |
| 그날 무엇을 했나 | `작업로그/<날짜>.md` |
| 웹·백엔드 연결 계약 | `docs/webbridge.md` · `docs/contracts/` · `docs/ai-backend-handoff.md` |
| RAG 계약 | `docs/rag-adapter-contract.md` · `docs/rag-team-interface-spec.md` |
| Git 브랜치·커밋·PR 규칙 (상세) | `docs/git-conventions.md` |
| 서버 기동 순서 (MySQL → AI → backend) | 리포지토리 루트 `CLAUDE.md` |

**권위**: 코드 > `AGENTS.md` > 그 밖의 문서. 문서끼리 충돌하면
`docs/agent-structure-current.md`(현재 상태) 를 따르고, 어긋난 쪽을 고친다.
**"왜 이렇게 됐나"가 갈리면 `docs/decisions.md`** — 뒤집힌 결정을 지우지 않으므로 거기에 답이 있다.

**새 결정을 내리면 `docs/decisions.md` 에 한 항목을 append 한다**(결정·왜·뒤집힘·출처).
안 하기로 한 결정도 근거와 함께 남긴다 — 다음 사람이 같은 것을 다시 시도하지 않게.

---

## Git — 이 저장소에서 실제로 문제가 됐던 것만 (상세: `docs/git-conventions.md`)

- 커밋은 **작업 브랜치에서만.** `main`·`develop` 에 직접 push 금지.
- **MR·머지는 사용자가 명시로 요청할 때만.** 예고 없는 머지로 다른 팀 작업이 깨진 이력이 있다.
- 커밋 메시지는 Conventional Commits: `<타입>(<범위>): <제목>` (`feat`·`fix`·`docs`·`refactor`·
  `test`·`chore`·`perf`·`ci`). 제목은 명령형·50자 이내·마침표 없음.
- **하나의 커밋은 하나의 논리적 변경.** 특히 프롬프트 변경은 평가셋 재측정과 **같은 커밋에**
  (`AGENTS.md` §3-6).
- `.env`·비밀키·대용량 산출물은 절대 커밋하지 않는다.
