# CLAUDE.md — 커리어 코치 Agent (Prototype 1.0.0)

이 프로젝트의 **코딩 규약·계약은 `AGENTS.md`(코딩 헌법)가 단일 출처**입니다.
아래로 자동 임포트합니다 — 코딩·실행 시 항상 이 규약을 따르세요.

@AGENTS.md

## 문서 지도 (배경 근거 — 사람이 읽는 근거)
- **설계 정본**: `agent 설계 명세서/agent_prototype_1.0.0.md` (툴·시나리오·스키마)
- **진행 기록**: `prototype_1.0.0/` — `README.md`(인덱스) · `decisions.md`(결정 로그 D1~) · `tasks/`(태스크 계약+검증) · `checkpoints/`(점검)
- **개발 방법론**: `agent_ver_VIBE-CODING-PLAYBOOK.md`
- **RAG 계약**: `rag_입출력 관련 명세서/RAG_입출력_명세서.md`

> **권위(decisions.md D6):** 설계 개념 충돌 → 정본 우선 / 구현 디테일 충돌 → **AGENTS.md 우선**.
> 새 태스크는 플레이북대로 `tasks/NN-*.md` 명세 → 컨펌 → 코드 → 검증 → 기록.
