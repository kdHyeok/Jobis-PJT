# 크로스인코더 재순위(CE rerank) 트레이드오프 (2026-08-04)

`RAG/webapp/server.py` 커넥션 풀 교체(`ab1d3ab`) 후 동시성 벤치마크에서, 재순위 단계가
유일한 처리량 병목으로 확인됐다. 재순위를 켜고 끌지 결정하기 위한 정리.

## 0. 동시성(concurrency) 구현 — 커넥션 풀 적용 (`ab1d3ab`)

### 이전 상태 (문제)

`webapp/server.py`는 `ThreadingHTTPServer`로 요청마다 스레드를 띄우는데, DB 커넥션은
모듈 전역 싱글턴 `_conn` 하나를 전 스레드가 공유했다.

| # | 문제 | 증상 |
|---|---|---|
| 1 | 커넥션 1개 공유 | 모든 쿼리 직렬화(동시성 1), 한 스레드 실패 시 트랜잭션 aborted → 다른 스레드까지 연쇄 500 |
| 2 | `_ensure_ready()` lazy-init race | 초기화 완료 전에 다른 스레드가 통과해 `_vocab=None` 상태로 `parse_query` 호출 |
| 3 | BM25 인덱스 lazy-init race (`search.py`) | 동시 첫 요청 시 전체 코퍼스 인덱스 중복 구축 |
| 4 | 모델 무제한 동시 추론 | GPU 메모리 배수 증가, thread-safety 미보장 |

### 적용한 조치 (A: 커넥션 풀)

`psycopg_pool.ConnectionPool`로 교체:

```python
_pool = ConnectionPool(
    get_dsn(),
    min_size=2, max_size=10,
    configure=register_vector,       # 커넥션마다 자동 등록
    kwargs={"autocommit": True},     # 읽기 전용 → 트랜잭션 오염 원천 차단
)

# 요청 핸들러
with _pool.connection() as conn:
    result = hybrid_search(conn, spec, ...)
```

- 요청마다 풀에서 독립 커넥션을 빌려 쓰고 반납 — 한 요청의 실패가 다른 요청에 전파되지 않음
- `autocommit=True`로 트랜잭션 상태 자체가 없어 aborted 연쇄가 불가능
- 풀 생성·`_vocab` 로딩을 `main()`에서 `serve_forever()` 이전에 완료(`_init_pool()`) →
  요청 핸들러 안의 lazy-init 제거, 문제 2 해결
- 문제 3(BM25)·4(모델 동시 추론)는 **아직 미적용** — 별도 조치(B·C) 필요

### 검증

동시 10스레드로 실제 PostgreSQL(pgvector)에 검색 요청 → 에러 0, 스레드별 독립 커넥션 확인.
이후 §2 벤치마크에서도 커넥션 풀·pgvector·BM25·임베딩 단계는 동시 20개까지 문제없이 확장됨
(재순위 OFF 시 24.6 QPS) — 남은 병목은 재순위 하나뿐임을 이 벤치마크로 특정.

## 1. 품질: 켜면 얼마나 좋아지는가

출처: `eval/RESULTS_v2.md` (평가 v2, dev 30질의, claude cli judge, 쌍대 부트스트랩 95% CI)

| arm | 정규화 nDCG@3 | raw nDCG@3 |
|---|---|---|
| rrf_ce (재순위 ON) | **0.840** | **0.872** |
| rrf (재순위 OFF) | 0.734 | 0.808 |
| 차이 | **−0.106 (−12.6%)** | −0.064 (−7.3%) |

95% CI `[0.024, 0.189]` — 0을 포함하지 않는 유의한 하락. 평가 결론은 "CE 리랭커 유지".
소실 퍼널에서 fusion_rank(RRF가 top-3로 못 올린 32건)를 CE가 상당 부분 교정하는 것으로 확인됨.

`RERANK_TOP_N`을 15→30으로 올린 튜닝 적용 기준(`search.py`)으로는 0.851 → 0.734,
**−0.117 (−13.7%)**.

## 2. 처리량: 끄면 얼마나 빨라지는가

출처: 로컬 벤치마크, postings 6,116 / chunks 7,671, GPU(cuda) `bge-reranker-v2-m3`,
`RERANK_TOP_N=15`, LLM 생성 단계는 제외(검색 단계만).

| 동시 요청 | 재순위 ON 소요 | 재순위 ON 처리량 | 재순위 OFF 소요 | 재순위 OFF 처리량 |
|---|---|---|---|---|
| 1개 | 812ms | 1.23 QPS | — | — |
| 5개 | 3,744ms | 1.34 QPS | — | — |
| 10개 | 7,482ms (최악) | 1.34 QPS | 633ms (최악 622ms) | 15.8 QPS |
| 20개 | — | — | 812ms (최악 798ms) | 24.6 QPS |

재순위 ON은 동시 1개→10개로 늘려도 QPS가 1.23→1.34로 거의 그대로다 — GPU 크로스인코더가
완전히 직렬화되어 동시성 이득이 없다는 뜻. 10명이 동시에 요청하면 마지막 사용자는 약 7.5초
대기(+LLM 생성 1~3초 별도).

## 3. 교환 요약

| 구성 | 정규화 nDCG@3 | 처리량 | 동시 10개 최악 지연 |
|---|---|---|---|
| 재순위 ON | 0.840 | 1.34 QPS | 7,472ms |
| 재순위 OFF | 0.734 (−12.6%) | 15.8 QPS | 622ms |

품질 12.6%를 내주고 처리량 약 12배를 얻는 관계.

## 4. 결론 및 권고

재순위를 끄는 것은 권하지 않는다 — 검색 정확도 손실이 유의하고, 실제로 랭킹을 교정하는
역할이 소실 퍼널 분석으로 확인돼 있다. 대신 **재순위 배치화**로 품질을 유지한 채 처리량만
올리는 쪽이 맞다.

현재는 요청마다 15쌍을 개별로 GPU에 넘겨 완전 직렬화된다. 동시에 대기 중인 요청들의 쌍을
모아 하나의 배치로 `CrossEncoder.predict()`에 넘기면(예: 10요청 × 15쌍 = 150쌍 일괄 추론)
GPU 활용률이 올라가 품질 손실 없이 처리량 4~5배 개선이 기대된다. (`RAG/jobrag/reranker.py`
수정 필요 — 아직 미적용.)

## 참고

- 품질 수치 출처: `eval/RESULTS_v2.md`, `eval/report_v2.json`, `eval/pool_v2.json`
  (해당 커밋은 원격 `feat/ai/rag-pipeline`에서 유실됨 — 로컬 reflog에만 존재, 복구 필요)
- 처리량 수치는 LLM 생성(GMS) 제외, 검색 단계(쿼리 임베딩 + BM25 + pgvector HNSW + CE rerank)만
- GMS API 쿼터가 별도 하드 상한으로 작용할 수 있음(미확인) — 재순위 개선과 무관하게 확인 필요
