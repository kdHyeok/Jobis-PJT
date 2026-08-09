# RAG 작업자 진입점

@AGENTS.md

## Claude Code

- CI 환경에는 numpy·rank_bm25·psycopg·python-dotenv 만 있다. 테스트가 torch·pgvector 를
  끌어오는 모듈을 import 하면 파이프라인이 깨진다 — 순수 계산은 별도 모듈로 떼어 테스트한다.
- 검사를 추가할 일이 생기면 `Jenkinsfile` 이 아니라 `RAG/ci-checks` 를 고친다.
