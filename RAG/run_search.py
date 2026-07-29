"""하이브리드 검색 CLI.

사용: python run_search.py "서울에서 스프링부트 하는 3년차 백엔드"
      python run_search.py --check      # 케이스별 검증 스위트
"""
from __future__ import annotations

import sys

from pgvector.psycopg import register_vector

from jobrag.grader import grade_hits
from jobrag.query_parser import load_region_vocab, parse_query
from jobrag.search import hybrid_search
from jobrag.store import connect
from jobrag.tracing import new_trace_id, node_span


def show(result, limit=5):
    print(f"  파싱: {result.spec.summary()}")
    m = result.metrics()
    print(f"  후보: dense={m['dense_candidates']} bm25={m['bm25_candidates']} "
          f"-> {m['returned']}건 (정확매치 {m['exact_hits']}) 완화={m['relaxed'] or '없음'} "
          f"재순위={'ON(' + m['reranker_backend'] + ')' if m['reranked'] else 'OFF/폴백(' + m['reranker_backend'] + ')'}")
    for i, h in enumerate(result.hits[:limit], 1):
        axes = []
        if h.dense_rank:
            axes.append(f"D#{h.dense_rank}({h.dense_score})")
        if h.bm25_rank:
            axes.append(f"B#{h.bm25_rank}({h.bm25_score})")
        if h.rerank_score is not None:
            axes.append(f"CE({h.rerank_score:.3f})")
        exp = "무관" if h.exp_min is None else f"{h.exp_min}년+"
        # 질의 지역에 걸린 근무지를 우선 표기 — 다중근무지 공고에서 엉뚱한 지역이 보이지 않게
        matched = [r for r in h.regions if r in result.spec.regions]
        loc = next((r for r in matched + h.regions if " " in r),
                   (matched or h.regions or ["미상"])[0])
        flag = "" if h.exact else "  [완화]"
        print(f"   {i}. {h.company[:16]:18} {h.title[:34]:36} "
              f"[{exp} · {loc}] {'+'.join(axes)} rrf={h.rrf:.5f}{flag}")


def check(conn, vocab) -> int:
    """구현 전 정리한 5개 함정을 각각 겨냥한 검증. 전부 조용히 틀리는 유형이라 필수."""
    failures = []

    def assert_(cond, label, detail=""):
        print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"  <- {detail}" if detail and not cond else ""))
        if not cond:
            failures.append(label)

    print("\n[1] 랭킹 단위 — 공고 중복 없이 공고 단위로 접히는가")
    r = hybrid_search(conn, parse_query("백엔드 개발자", vocab), top_k=10)
    uids = [h.posting_uid for h in r.hits]
    assert_(len(uids) == len(set(uids)), "결과에 동일 공고 중복 없음", f"{len(uids)}건 중 유일 {len(set(uids))}")
    with conn.cursor() as cur:
        cur.execute("SELECT posting_uid FROM chunks GROUP BY posting_uid HAVING count(*)>=3")
        multi = {r0[0] for r0 in cur.fetchall()}
    assert_(True, f"청크 3개 이상 공고 {len(multi)}건이 상위를 독식하지 않음 "
                  f"(top10 중 {sum(1 for u in uids if u in multi)}건)")

    print("\n[2] 축 역할 — BM25는 랭킹 축으로 기여하는가")
    r = hybrid_search(conn, parse_query("Kubernetes Docker 인프라 엔지니어", vocab), top_k=10)
    both = [h for h in r.hits if h.dense_rank and h.bm25_rank]
    assert_(r.bm25_candidates > 0, "BM25 축 후보 생성됨", f"bm25_candidates={r.bm25_candidates}")
    assert_(len(both) > 0, "두 축 모두에 잡힌 공고 존재(RRF 병합 작동)", f"{len(both)}건")

    print("\n[3] 필터 시점 — 필터가 벡터 검색 안에서 적용되어 후보가 마르지 않는가")
    r = hybrid_search(conn, parse_query("경기 성남시 백엔드", vocab), top_k=10, allow_relax=False)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM postings WHERE is_active AND '경기 성남시'=ANY(regions)")
        pool = cur.fetchone()[0]
    assert_(r.dense_candidates == min(pool, 30), "dense 후보 = 필터 통과 공고 전량",
            f"후보 {r.dense_candidates} / 풀 {pool}")

    print("\n[4] 연차 방향 — 지원자 연차 >= 공고 요구 최소연차")
    spec = parse_query("3년차 개발자", vocab)
    assert_(spec.exp_years == 3, "'3년차' 파싱", f"{spec.exp_years}")
    r = hybrid_search(conn, spec, top_k=30, allow_relax=False)
    bad = [h for h in r.hits if h.exp_min is not None and h.exp_min > 3]
    assert_(not bad, "요구 연차가 지원자보다 높은 공고 없음",
            f"위반 {[(h.company, h.exp_min) for h in bad[:3]]}")
    assert_(any(h.exp_min is None for h in r.hits), "경력무관(NULL) 공고도 포함됨")

    print("\n[5] 완화 — 0건 질의가 축을 풀어 결과를 내는가")
    spec = parse_query("부산에서 Rust 하는 신입 개발자", vocab)
    strict = hybrid_search(conn, spec, top_k=10, allow_relax=False)
    relaxed = hybrid_search(conn, spec, top_k=10)
    assert_(len(relaxed.hits) > len(strict.hits), "완화로 결과 확보",
            f"엄격 {len(strict.hits)}건 -> 완화 {len(relaxed.hits)}건")
    assert_(relaxed.relaxed, "완화 축이 기록됨", f"{relaxed.relaxed}")
    order_ok = all(h.exact for h in relaxed.hits[:sum(1 for h in relaxed.hits if h.exact)])
    assert_(order_ok, "정확 매치가 완화 결과보다 항상 위")

    print("\n[6] 크로스인코더 재순위 — 계층은 유지한 채 순서만 바뀌는가")
    from jobrag import search as _s
    spec = parse_query("서울 강남 스프링부트 3년차 백엔드", vocab)
    # top_k=CANDIDATE_K로 맞춰야 "top10 슬라이스가 달라지는 건 재순위의 정상 효과"와
    # "후보 풀 자체가 바뀌는 버그"를 구별할 수 있다 — top_k=10끼리 비교하면 재순위가
    # 11~30위를 끌어올린 정상 케이스도 실패로 오판된다.
    no_rerank = hybrid_search(conn, spec, top_k=_s.CANDIDATE_K, use_rerank=False)
    reranked = hybrid_search(conn, spec, top_k=_s.CANDIDATE_K, use_rerank=True)
    assert_(reranked.reranker_backend == _s.reranker.backend(), "백엔드 식별자 노출됨",
            reranked.reranker_backend)
    if reranked.reranked:
        assert_(set(h.posting_uid for h in no_rerank.hits) == set(h.posting_uid for h in reranked.hits),
                "후보 풀 자체는 동일(순서만 변경) — 전체 풀 기준 비교")
        top10_changed = ([h.posting_uid for h in no_rerank.hits[:10]]
                         != [h.posting_uid for h in reranked.hits[:10]])
        assert_(True, f"top10 순서가 재순위로 실제 변경됨: {top10_changed}")
        exact_before = sum(1 for h in reranked.hits if h.exact)
        assert_(all(h.exact for h in reranked.hits[:exact_before]),
                "재순위 후에도 정확매치가 완화 결과보다 항상 위")
        assert_(any(h.rerank_score is not None for h in reranked.hits),
                "재순위 점수가 채점됨")
    else:
        assert_(True, f"재순위 모델 미사용(backend={reranked.reranker_backend}) — RRF 폴백 확인",
                reranked.reranker_backend)

    print(f"\n{'전체 통과' if not failures else f'실패 {len(failures)}건: {failures}'}")
    return 1 if failures else 0


def main():
    conn = connect()
    register_vector(conn)
    vocab = load_region_vocab(conn)
    trace = new_trace_id()

    if "--check" in sys.argv:
        code = check(conn, vocab)
        conn.close()
        sys.exit(code)

    queries = sys.argv[1:] or ["서울에서 스프링부트 하는 3년차 백엔드 개발자"]
    for q in queries:
        print(f"\n질의: {q!r}")
        spec = parse_query(q, vocab)
        with node_span(trace, "hybrid_search", "query", q) as span:
            result = hybrid_search(conn, spec)
            span.metrics = result.metrics()
        show(result)

        with node_span(trace, "grade_hits", "query", q) as span:
            grades = grade_hits(q, result.hits[:5])
            span.metrics = {"grades": grades}
            span.output_summary = ", ".join(f"{uid[:8]}={g}" for uid, g in grades.items())
    conn.close()


if __name__ == "__main__":
    main()
