# AI 모듈 작업자 진입점

@AGENTS.md

@작업로그/지금상태.md

모든 작업자는 `AGENTS.md`를 우선한다. 현재 HTTP 서버는
`src/jobis_ai/v2bridge/app.py`, 실행법은 `README.md`, 결정 이력은
`docs/decisions.md`, 배포는 루트 `../ops/DEPLOYMENT.md`가 정본이다.

옛 WebSocket webbridge와 별도 계약 어댑터 실행법은 제거됐으며 현행 서버로 사용하지 않는다.

문서 지도:

- 현재 구조: `docs/agent-structure-current.md`
- 발전 과정: `docs/agent-structure-evolution.md`
- 결정 이력: `docs/decisions.md`
- 장애 실측: `docs/troubleshooting.md`
- v2 HTTP 계약: `docs/v2bridge.md`
- 백엔드 인계: `docs/ai-backend-handoff.md`
- RAG adapter: `docs/rag-adapter-contract.md`
- RAG 팀 계약: `docs/rag-team-interface-spec.md`
- Git 규칙: `docs/git-conventions.md`
- 운영 배포: `../ops/DEPLOYMENT.md`
