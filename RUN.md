# JOBISS 실행 안내

이 파일의 예전 `fake-ai`, WebSocket, Hibernate/MySQL 실행법은 제거됐다.

- 로컬 실행: [README.md](README.md)
- AI 설정: [AI/.env.example](AI/.env.example)
- Docker/CI/CD/운영: [ops/DEPLOYMENT.md](ops/DEPLOYMENT.md)
- Airflow/RAG: [infra/airflow/README.md](infra/airflow/README.md)

현재 순서는 PostgreSQL `55432` → AI/v2bridge `8000` → Spring `8080` → Vite `5173`이다.
