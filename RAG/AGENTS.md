# RAG 작업 지침

루트 [AGENTS.md](../AGENTS.md) 를 먼저 읽는다.

## CI — 가벼운 환경에서 통과해야 한다

이 영역의 검사는 **[RAG/ci-checks](ci-checks)** 가 정한다.

```
./RAG/ci-checks test   # required — compileall + unittest discover
./RAG/ci-checks lint   # advisory — ruff
```

`RAG/**` 또는 `DATA/**` 가 바뀐 MR 에서만 돈다.

**CI 환경에는 numpy·rank_bm25·psycopg·python-dotenv 만 있다.** torch·sentence-transformers·
pgvector 는 없다. 그래서 테스트가 무거운 모듈을 import 하면 `ModuleNotFoundError` 로
파이프라인이 깨진다 — 실제로 한 번 깨졌다.

## 순수 계산은 실행 스크립트에서 떼어낸다

`run_ingest_additive.py` 같은 실행 스크립트는 상단에서 pgvector·임베딩 백엔드를
가져온다. 그 안의 순수 계산을 테스트하려면 **별도 모듈로 옮기고 그것을 테스트한다.**

전례: `plan_windows` 를 `jobrag/ingest_windows.py` 로 옮겼다. 테스트는
`from jobrag.ingest_windows import plan_windows` 로 가볍게 import 한다.

DB·임베딩이 실제로 필요한 검증은 CI 가 아니라 로컬이나 파이프라인 DAG 에서 한다.
