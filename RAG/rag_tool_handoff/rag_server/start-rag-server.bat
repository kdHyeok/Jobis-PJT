@echo off
rem RAG 툴 서버 기동 — AI Agent가 Tool로 호출하는 검색 서비스 (포트 8765)
rem 사전조건: PostgreSQL(pgvector) 기동, .env에 PG_DSN/GMS_KEY 설정
rem warmup(모델 로드 + BM25 인덱스)에 수십 초 걸림 — "warmup done - ready" 로그가 뜨면 사용 가능
cd /d "%~dp0"
set PYTHONUTF8=1
python -m uvicorn webapp.tool_server:app --host 127.0.0.1 --port 8765
pause
