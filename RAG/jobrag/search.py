"""하이브리드 검색 — dense(의미) + BM25(어휘) 2축 RRF 병합 + 조건 완화.

설계 원칙 (구현 전 정리한 함정 대응):
  1. 랭킹 단위는 '공고'. dense/BM25 모두 청크 단위라 공고당 최고 청크만
     남긴 뒤 병합한다 — 안 그러면 청크 많은 긴 공고가 상위를 독식한다.
  2. 축 역할 분리: 지역·연차·직군은 하드필터, dense·BM25만 랭킹 축.
     BM25는 chunks.text 전체에 대해 진짜 Okapi BM25(rank_bm25)로 계산한다
     (예전 tech[] 배열 매치 개수 흉내가 아니라 자유 텍스트 역색인 랭킹).
  3. 필터는 후보 생성 시점에 적용. top-k를 뽑고 나서 거르면 후보가 고갈된다.
  4. 연차 방향: 지원자 연차 >= 공고 요구 최소연차. exp_min IS NULL(무관)은 항상 포함.
  5. 결과가 부족하면 축을 순서대로 완화(지역 -> 연차)하되, 원 조건을 만족하는
     공고가 항상 위에 오도록 계층 정렬한다.
  6. 크로스인코더 재순위(§_apply_rerank)는 RRF 병합 후 상위 RERANK_TOP_N개에만
     적용하고 exact/relaxed 계층은 그대로 유지한다 — 재순위가 완화 결과를
     정확 매치보다 위로 올리면 하드필터가 무의미해진다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from rank_bm25 import BM25Okapi

from . import reranker
from .embedding import embed_texts
from .query_parser import QuerySpec

RRF_K = 60          # RRF 상수 (표준값)
CANDIDATE_K = 30    # 축별 후보 수
RERANK_TOP_N = 15   # 재순위 대상 상한 — 크로스인코더는 후보 30개 전부에 걸 정도로 싸지 않다
RELAX_ORDER = ("region", "exp")   # 완화 순서 — 지역이 가장 자주 과도하게 좁힌다

_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")


def _tokenize(text: str) -> list[str]:
    """형태소 분석기 없이 쓰는 단순 토크나이저(영숫자+한글 음절 블록, 소문자화).

    한국어 조사/어미가 그대로 토큰에 붙어(예: "스프링부트를") BM25 매칭이 다소
    거칠어지지만, 이 프로젝트에 형태소 분석 의존성이 없으므로 실용적 절충안이다.
    """
    return _TOKEN_RE.findall(text.lower())


@dataclass
class SearchHit:
    posting_uid: str
    company: str
    title: str
    url: str
    regions: list[str]
    tech: list[str]
    exp_min: int | None
    role_category: str = ""
    employment_type: str = ""
    dense_rank: int | None = None
    bm25_rank: int | None = None
    dense_score: float | None = None      # 코사인 유사도 (1 - 거리)
    bm25_score: float | None = None       # Okapi BM25 raw score (chunks.text 기준)
    rrf: float = 0.0
    exact: bool = True                    # 완화 전 조건까지 만족하는가
    best_chunk_id: str | None = None
    rerank_score: float | None = None     # 크로스인코더 raw logit (미적용/실패 시 None)


@dataclass
class SearchResult:
    spec: QuerySpec
    hits: list[SearchHit]
    relaxed: list[str] = field(default_factory=list)
    dense_candidates: int = 0
    bm25_candidates: int = 0
    reranked: bool = False
    reranker_backend: str = ""

    def metrics(self) -> dict:
        return {
            "returned": len(self.hits),
            "dense_candidates": self.dense_candidates,
            "bm25_candidates": self.bm25_candidates,
            "relaxed": self.relaxed,
            "exact_hits": sum(1 for h in self.hits if h.exact),
            "reranked": self.reranked,
            "reranker_backend": self.reranker_backend,
        }


def _filters(spec: QuerySpec, relaxed: tuple[str, ...]) -> tuple[str, list]:
    clauses = ["p.is_active"]
    params: list = []
    if spec.regions and "region" not in relaxed:
        clauses.append("p.regions && %s::text[]")
        params.append(spec.regions)
    if spec.exp_years is not None and "exp" not in relaxed:
        # 공고가 요구하는 최소 연차가 지원자 연차 이하일 때만 지원 가능
        clauses.append("(p.exp_min IS NULL OR p.exp_min <= %s)")
        params.append(spec.exp_years)
    # role_category 하드필터 제거 — role_taxonomy 분류기 오분류(fullstack/backend 등)가
    # 검색 자체를 막는 문제가 있어, 직군 매칭은 dense+BM25 랭킹에 맡기고 하드필터에서 뺐다.
    return " AND ".join(clauses), params


def _dense_axis(conn, vec, spec, relaxed) -> list[tuple[str, str, float]]:
    where, fp = _filters(spec, relaxed)
    sql = f"""
        SELECT t.posting_uid, t.chunk_id, t.dist FROM (
            SELECT DISTINCT ON (c.posting_uid)
                   c.posting_uid, c.chunk_id, (c.embedding <=> %s::vector) AS dist
            FROM chunks c JOIN postings p ON p.uid = c.posting_uid
            WHERE {where} AND c.embedding IS NOT NULL
            ORDER BY c.posting_uid, c.embedding <=> %s::vector
        ) t ORDER BY t.dist LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, [vec, *fp, vec, CANDIDATE_K])
        return cur.fetchall()


_bm25_cache: dict | None = None   # {"bm25": BM25Okapi, "chunks": [(posting_uid, chunk_id)]}


def _load_bm25_index(conn) -> dict:
    """chunks.text 전체에 대한 Okapi BM25 인덱스. 프로세스 수명 동안 1회만 구축한다.

    dense 임베딩과 달리 BM25는 코퍼스(IDF)가 바뀌지 않는 한 매 쿼리마다 다시
    만들 이유가 없다 — 재구축 비용을 아끼려고 모듈 전역에 캐시한다. 배치 재적재로
    코퍼스가 바뀌면 새 프로세스(재기동)에서 자연히 갱신된다.
    """
    global _bm25_cache
    if _bm25_cache is not None:
        return _bm25_cache
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.posting_uid, c.chunk_id, c.text
            FROM chunks c JOIN postings p ON p.uid = c.posting_uid
            WHERE p.is_active
        """)
        rows = cur.fetchall()
    chunks = [(uid, chunk_id) for uid, chunk_id, _ in rows]
    corpus = [_tokenize(text) for _, _, text in rows]
    _bm25_cache = {"bm25": BM25Okapi(corpus or [[]]), "chunks": chunks}
    return _bm25_cache


def _bm25_axis(conn, spec, relaxed) -> list[tuple[str, str, float]]:
    """BM25 어휘 축 — 자유 텍스트(spec.text) 대상 Okapi BM25 랭킹.

    dense와 동일하게 청크 단위로 채점된 걸 공고 단위(최고 청크)로 접는다.
    하드필터는 postings 테이블에서 자격 있는 uid 집합을 뽑아 교집합으로 적용한다
    (BM25 자체는 인메모리 계산이라 SQL WHERE에 못 태운다).
    """
    query_tokens = _tokenize(spec.text)
    if not query_tokens:
        return []
    index = _load_bm25_index(conn)
    scores = index["bm25"].get_scores(query_tokens)

    where, fp = _filters(spec, relaxed)
    with conn.cursor() as cur:
        cur.execute(f"SELECT p.uid FROM postings p WHERE {where}", fp)
        eligible = {r[0] for r in cur.fetchall()}

    best: dict[str, tuple[str, float]] = {}
    for (uid, chunk_id), score in zip(index["chunks"], scores):
        if score <= 0 or uid not in eligible:
            continue
        cur_best = best.get(uid)
        if cur_best is None or score > cur_best[1]:
            best[uid] = (chunk_id, float(score))

    ordered = sorted(best.items(), key=lambda kv: (-kv[1][1], kv[0]))[:CANDIDATE_K]
    return [(uid, chunk_id, score) for uid, (chunk_id, score) in ordered]


def _fetch_postings(conn, uids: list[str]) -> dict[str, dict]:
    if not uids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """SELECT uid, company, title, url, regions, tech, exp_min,
                      role_category, employment_type
               FROM postings WHERE uid = ANY(%s)""",
            (uids,),
        )
        cols = ("uid", "company", "title", "url", "regions", "tech", "exp_min",
                "role_category", "employment_type")
        return {r[0]: dict(zip(cols, r)) for r in cur.fetchall()}


def _satisfies(row: dict, spec: QuerySpec) -> bool:
    """완화 전 원 조건 충족 여부 — 완화 검색에서도 정확 매치를 위로 올리기 위함."""
    if spec.regions and not set(row["regions"]) & set(spec.regions):
        return False
    if spec.exp_years is not None:
        if row["exp_min"] is not None and row["exp_min"] > spec.exp_years:
            return False
    return True


def _search_once(conn, vec, spec, relaxed, top_k) -> SearchResult:
    dense = _dense_axis(conn, vec, spec, relaxed)
    bm25 = _bm25_axis(conn, spec, relaxed)

    scores: dict[str, dict] = {}
    for rank, (uid, chunk_id, dist) in enumerate(dense, start=1):
        scores.setdefault(uid, {})["dense"] = (rank, chunk_id, 1.0 - float(dist))
    # 동점은 같은 순위로 묶는다(경쟁 순위). 순차 부여하면 남은 순서를 uid가 정하게 되고
    # 그 무의미한 차이가 RRF 점수에 그대로 흘러든다. 동점이면 dense 축이 타이브레이크한다.
    prev_score, prev_rank = None, 0
    for i, (uid, chunk_id, score) in enumerate(bm25, start=1):
        score = float(score)
        rank = prev_rank if score == prev_score else i
        prev_score, prev_rank = score, rank
        scores.setdefault(uid, {})["bm25"] = (rank, chunk_id, score)

    rows = _fetch_postings(conn, list(scores))
    hits: list[SearchHit] = []
    for uid, axes in scores.items():
        row = rows.get(uid)
        if row is None:
            continue
        rrf = 0.0
        d = axes.get("dense")
        b = axes.get("bm25")
        if d:
            rrf += 1.0 / (RRF_K + d[0])
        if b:
            rrf += 1.0 / (RRF_K + b[0])
        hits.append(SearchHit(
            posting_uid=uid, company=row["company"], title=row["title"], url=row["url"],
            regions=row["regions"], tech=row["tech"], exp_min=row["exp_min"],
            role_category=row["role_category"] or "", employment_type=row["employment_type"] or "",
            dense_rank=d[0] if d else None, best_chunk_id=d[1] if d else (b[1] if b else None),
            dense_score=round(d[2], 4) if d else None,
            bm25_rank=b[0] if b else None,
            bm25_score=round(b[2], 4) if b else None,
            rrf=round(rrf, 6), exact=_satisfies(row, spec),
        ))
    # 원 조건 충족분을 먼저, 그 안에서 RRF 순 (완화해도 정확 매치가 밀리지 않음).
    # RRF까지 같으면 uid로 확정 — 정렬 키를 완전하게 두지 않으면 남은 순서가
    # 입력 순서(=DB 반환 순서)에 좌우되어 결과가 재현되지 않는다.
    hits.sort(key=lambda h: (not h.exact, -h.rrf, h.posting_uid))
    return SearchResult(spec=spec, hits=hits[:top_k], relaxed=list(relaxed),
                        dense_candidates=len(dense), bm25_candidates=len(bm25))


def _fetch_rerank_texts(conn, hits: list[SearchHit]) -> dict[str, str]:
    """재순위용 대표 청크 텍스트. dense 축에서 이미 찾은 최고 청크가 있으면 그걸 쓰고,
    tech 축으로만 잡힌 공고(dense 미스)는 통짜 청크를 대표로 조회한다."""
    texts: dict[str, str] = {}
    have_chunk = {h.posting_uid: h.best_chunk_id for h in hits if h.best_chunk_id}
    if have_chunk:
        with conn.cursor() as cur:
            cur.execute("SELECT chunk_id, text FROM chunks WHERE chunk_id = ANY(%s)",
                       (list(have_chunk.values()),))
            by_chunk = dict(cur.fetchall())
        for uid, cid in have_chunk.items():
            if cid in by_chunk:
                texts[uid] = by_chunk[cid]

    need_repr = [h.posting_uid for h in hits if h.posting_uid not in texts]
    if need_repr:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT DISTINCT ON (posting_uid) posting_uid, text FROM chunks
                   WHERE posting_uid = ANY(%s)
                   ORDER BY posting_uid, (part = 'full') DESC, chunk_id""",
                (need_repr,),
            )
            texts.update(dict(cur.fetchall()))
    return texts


def _apply_rerank(conn, spec: QuerySpec, result: SearchResult) -> None:
    """크로스인코더로 계층(exact/relaxed) 내부만 재정렬. 계층 자체는 안 섞는다 —
    재순위가 완화 결과를 정확 매치보다 위로 올리면 하드필터 의미가 없어진다.
    실패 시 조용히 RRF 순서를 유지(폴백).

    상위 RERANK_TOP_N개만 재점수한다. result.hits는 이미 RRF로 tier 정렬돼
    있으므로 나머지(N번째 밖)는 어차피 최종 top_k 컷 밖으로 밀릴 확률이 높고,
    무제한으로 넣으면 GPU 비용이 선형으로 커진다."""
    if not result.hits:
        return
    pool, rest = result.hits[:RERANK_TOP_N], result.hits[RERANK_TOP_N:]
    texts = _fetch_rerank_texts(conn, pool)
    pairs = [(h.posting_uid, texts[h.posting_uid]) for h in pool if h.posting_uid in texts]
    scores = reranker.rerank(spec.text, pairs)
    result.reranker_backend = reranker.backend()
    if scores is None:
        result.reranked = False
        return
    score_map = {uid: s for (uid, _), s in zip(pairs, scores)}
    for h in pool:
        h.rerank_score = score_map.get(h.posting_uid)
    pool.sort(key=lambda h: (
        not h.exact,
        -(h.rerank_score if h.rerank_score is not None else float("-inf")),
        -h.rrf, h.posting_uid,
    ))
    result.hits = pool + rest
    result.reranked = True


def hybrid_search(conn, spec: QuerySpec, top_k: int = 10,
                  min_results: int = 5, allow_relax: bool = True,
                  use_rerank: bool = True) -> SearchResult:
    """조건이 과도하게 좁아 결과가 부족하면 축을 순서대로 풀어 재검색.

    완화 검색은 후보 창(CANDIDATE_K)이 넓은 풀에 걸리므로 엄격 검색에서 찾은
    공고가 그 창 밖으로 밀려날 수 있다. 그래서 교체하지 않고 병합한다.
    RRF 점수는 후보 풀이 다르면 서로 비교할 수 없으나, 정확 매치와 완화 결과를
    분리해 정렬하므로 각 계층 안에서는 같은 검색 결과끼리만 비교된다.
    """
    [vec], _ = embed_texts([spec.text])

    result = _search_once(conn, vec, spec, (), CANDIDATE_K)

    if allow_relax and len(result.hits) < min_results:
        exact = result.hits                   # 엄격 검색 결과 — 전부 정확 매치
        seen = {h.posting_uid for h in exact}
        for i in range(1, len(RELAX_ORDER) + 1):
            axes = RELAX_ORDER[:i]
            # 애초에 걸리지 않은 축만 푸는 시도는 결과가 같으므로 건너뛴다
            active = {"region": bool(spec.regions), "exp": spec.exp_years is not None}
            if not any(active[a] for a in axes):
                continue
            extra = _search_once(conn, vec, spec, axes, CANDIDATE_K)
            merged = exact + [h for h in extra.hits if h.posting_uid not in seen]
            seen |= {h.posting_uid for h in extra.hits}
            merged.sort(key=lambda h: (not h.exact, -h.rrf, h.posting_uid))
            result = SearchResult(spec=spec, hits=merged, relaxed=list(axes),
                                  dense_candidates=extra.dense_candidates,
                                  bm25_candidates=extra.bm25_candidates)
            if len(result.hits) >= min_results:
                break

    # 재순위는 top_k로 자르기 전, 후보 전체(exact/relaxed 계층 유지)에 적용해야
    # 순위를 바꿀 여지가 있다 — 먼저 잘라내면 크로스인코더가 볼 것이 없어진다.
    if use_rerank:
        _apply_rerank(conn, spec, result)

    result.hits = result.hits[:top_k]
    return result
