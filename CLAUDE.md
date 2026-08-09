# AI 작업자 안내

@AGENTS.md

도구별 별도 실행 계약을 두지 않는다. 모든 AI 작업자는 저장소 루트의 [AGENTS.md](AGENTS.md)를
먼저 읽고, 배포 작업은 [ops/DEPLOYMENT.md](ops/DEPLOYMENT.md)를 따른다.

현재 정본 AI 서버는 `AI/src/jobis_ai/v2bridge/app.py`다. `fake-ai`, 별도 `ai-server`,
MySQL/Hibernate 자동 스키마, 옛 WebSocket 실행법을 현행 계약으로 사용하지 않는다.
